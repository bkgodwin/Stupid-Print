"""Render label designs and encode a 203 dpi D30 raster."""

import base64
import io
import math
import os
import struct
import unicodedata
from functools import lru_cache
from pathlib import Path

import barcode
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .model import dimensions


DOTS_PER_MM = 8
HEAD_DOTS = 96
EMOJIS = ("★", "✓", "⚠", "♥", "☎", "✉", "⚡", "♻", "🏷️", "🔧", "📦", "🔌", "😀", "🚀")
BARCODES = {"Code 128": "code128", "Code 39": "code39", "EAN-13": "ean13", "UPC-A": "upca"}


def dots(mm):
    return round(float(mm) * DOTS_PER_MM)


@lru_cache(maxsize=1)
def font_catalog():
    if os.name == "nt":
        roots = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                 Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Microsoft/Windows/Fonts"]
    else:
        roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 Path.home() / ".local/share/fonts", Path.home() / ".fonts"]
    families = {}
    for root in roots:
        for path in root.rglob("*") if root.is_dir() else ():
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                family, style = ImageFont.truetype(str(path), 12).getname()
            except OSError:
                continue
            style = style.lower()
            weight = "bold" in style or "black" in style or "heavy" in style
            italic = "italic" in style or "oblique" in style
            variants = families.setdefault(family, {})
            priority = style in ("regular", "book", "normal", "roman", "bold", "italic",
                                 "oblique", "bold italic", "bold oblique")
            key = (weight, italic)
            if key not in variants or priority:
                variants[key] = str(path)
    return families


@lru_cache(maxsize=256)
def _font(family, size, bold=False, italic=False):
    catalog = font_catalog()
    if family not in catalog:
        family = next((name for name in ("Segoe UI", "DejaVu Sans", "Liberation Sans", "Arial")
                       if name in catalog), None)
    if family:
        variants = catalog[family]
        key = (bold, italic)
        actual = next(option for option in (key, (bold, False), (False, italic),
                                             (False, False), next(iter(variants)))
                      if option in variants)
        return ImageFont.truetype(variants[actual], size), bold and not actual[0], italic and not actual[1]
    return ImageFont.load_default(size=size), bold, italic


def _emoji_start(char):
    return ord(char) >= 0x1F000 or 0x2600 <= ord(char) <= 0x27BF or char in "★☆♥"


def _runs(text):
    """Keep variation selectors, skin tones and joined emoji with their base glyph."""
    pos = 0
    regular = ""
    while pos < len(text):
        start = pos
        char = text[pos]
        pos += 1
        flag = 0x1F1E6 <= ord(char) <= 0x1F1FF
        if flag and pos < len(text) and 0x1F1E6 <= ord(text[pos]) <= 0x1F1FF:
            pos += 1
        while pos < len(text):
            follow = text[pos]
            if follow == "\u200d" and pos + 1 < len(text):
                pos += 2
            elif (follow in "\ufe0e\ufe0f" or unicodedata.combining(follow)
                  or 0x1F3FB <= ord(follow) <= 0x1F3FF):
                pos += 1
            else:
                break
        cluster = text[start:pos]
        if _emoji_start(char):
            if regular:
                yield regular, False
                regular = ""
            yield cluster, True
        else:
            regular += cluster
    if regular:
        yield regular, False


@lru_cache(maxsize=512)
def _emoji_image(cluster, size):
    for family in ("Segoe UI Emoji", "Noto Color Emoji", "Noto Emoji", "Symbola",
                   "Segoe UI Symbol", "DejaVu Sans"):
        variants = font_catalog().get(family)
        if not variants:
            continue
        path = variants.get((False, False)) or next(iter(variants.values()))
        for font_size in (max(20, size * 2), 109):
            try:
                font = ImageFont.truetype(path, font_size)
                if font.getmask(cluster).getbbox() == font.getmask("\U0010FFFF").getbbox() and (
                    bytes(font.getmask(cluster)) == bytes(font.getmask("\U0010FFFF"))
                ):
                    break
                left, top, right, bottom = font.getbbox(cluster)
                if right <= left or bottom <= top:
                    break
                image = Image.new("RGBA", (right - left, bottom - top))
                ImageDraw.Draw(image).text((-left, -top), cluster, font=font,
                                           fill="black", embedded_color=True)
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                alpha = image.getchannel("A")
                gray = Image.new("L", image.size, 255)
                gray.paste(ImageOps.autocontrast(image.convert("L")).point(lambda p: min(p, 180)),
                           (0, 0), alpha)
                return gray
            except (OSError, ValueError):
                continue
    return None


def _run_width(run, font, size, stroke):
    text, emoji = run
    image = _emoji_image(text, size) if emoji else None
    return image.width + 1 if image is not None else math.ceil(font.getlength(text)) + 2 * stroke


def _lines(text, font, size, stroke, limit):
    def width(line):
        return sum(_run_width(run, font, size, stroke) for run in _runs(line))

    for paragraph in text.expandtabs(4).split("\n"):
        if width(paragraph) <= limit:
            yield paragraph
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and width(candidate) > limit:
                yield line
                line = word
            else:
                line = candidate
        yield line


def _text_image(item, value, size):
    width, height = size
    points = float(item["size"])
    if not 3 <= points <= 96:
        raise ValueError("Text size must be between 3 and 96 pt.")
    start = max(1, round(points * DOTS_PER_MM * 25.4 / 72))
    for pixels in range(start, max(5, min(start, 6)) - 1, -1):
        font, fake_bold, fake_italic = _font(item["font"], pixels, item["bold"], item["italic"])
        stroke = max(1, pixels // 22) if fake_bold else 0
        ascent, descent = font.getmetrics()
        leading = max(pixels, ascent + descent + stroke)
        shear = math.ceil(leading * 0.2) if fake_italic else 0
        lines = [list(_runs(line)) for line in _lines(value, font, pixels, stroke, max(1, width - shear))]
        widths = [sum(_run_width(run, font, pixels, stroke) for run in line) for line in lines]
        if (not item["fit"] or
                (max(widths, default=0) + shear <= width and len(lines) * leading <= height)):
            break
    total_height = leading * len(lines)
    top = {"Top": 0, "Middle": (height - total_height) // 2, "Bottom": height - total_height}[item["valign"]]
    result = Image.new("L", size, 255)
    for line, line_width in zip(lines, widths):
        line_image = Image.new("L", (max(1, min(width + 2, line_width + shear + 2)), leading), 255)
        draw = ImageDraw.Draw(line_image)
        x = 0
        for run in line:
            content, emoji = run
            image = _emoji_image(content, pixels) if emoji else None
            if image is None:
                draw.text((x + stroke, ascent), content, font=font, fill=0, anchor="ls", stroke_width=stroke)
            else:
                line_image.paste(image, (x, max(0, (leading - image.height) // 2)))
            x += _run_width(run, font, pixels, stroke)
        if item["underline"] and x:
            y = min(leading - 1, ascent + max(1, pixels // 14))
            draw.line((0, y, x - 1, y), fill=0, width=max(1, pixels // 13))
        if fake_italic:
            line_image = line_image.transform(line_image.size, Image.Transform.AFFINE,
                                              (1, 0.2, -shear, 0, 1, 0), fillcolor=255)
        left = {"Left": 0, "Center": (width - line_width - shear) // 2,
                "Right": width - line_width - shear}[item["align"]]
        result.paste(line_image, (left, top))
        top += leading
    return result


def _barcode_image(item, value, size):
    name = item["symbology"]
    if name in ("EAN-13", "UPC-A"):
        digits = 12 if name == "EAN-13" else 11
        if not value.isascii() or not value.isdigit() or len(value) not in (digits, digits + 1):
            raise ValueError(f"{name} needs {digits} digits plus an optional check digit.")
    options = {"add_checksum": False} if name == "Code 39" else {}
    if not value:
        raise ValueError("Barcode value is empty.")
    try:
        code = barcode.get_barcode_class(BARCODES[name])(value, **options)
        canonical = code.get_fullcode()
        if name in ("EAN-13", "UPC-A") and len(value) == len(canonical) and value != canonical:
            raise ValueError(f"{name} check digit should be {canonical[-1]}.")
        pattern = code.build()[0]
    except (barcode.errors.BarcodeError, UnicodeError, ValueError, IndexError) as exc:
        raise ValueError(f"{name}: {exc}") from exc
    width, height = size
    quiet = 12
    module = width // (len(pattern) + 2 * quiet)
    if not module or height < 16:
        raise ValueError(f"Make the {name} box larger or use a shorter value.")
    if module == 1 and not item.get("compact", False):
        raise ValueError(f"The {name} needs a wider box for 2-dot modules. "
                         "Shorten the value or enable compact bars.")
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    left = (width - len(pattern) * module) // 2
    caption = item["caption"] and height >= 27
    bars = height - 14 if caption else height
    for index, bit in enumerate(pattern):
        if bit != "0":
            x = left + index * module
            draw.rectangle((x, 0, x + module - 1, bars - 1), fill=0)
    if caption:
        font, _, _ = _font("Default", 11)
        draw.text((width // 2, height - 1), canonical, fill=0, font=font, anchor="ms")
    return image


def embed_image(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        image.save(stream, format="PNG", optimize=True)
    return base64.b64encode(stream.getvalue()).decode("ascii")


@lru_cache(maxsize=12)
def _read_image(encoded):
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as source:
        return source.convert("RGBA")


def render_label(doc, batch, index):
    width, height = map(dots, dimensions(doc))
    result = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(result)
    border = doc["border"]
    if border != "None":
        inset = dots(0.6)
        top = max(inset, (height - HEAD_DOTS) // 2 + inset)
        box = (inset, top, width - inset - 1, height - top - 1)
        thickness = max(1, min(8, int(doc["border_width"])))
        if border == "Rounded":
            draw.rounded_rectangle(box, radius=dots(1.6), outline=0, width=thickness)
        else:
            draw.rectangle(box, outline=0, width=thickness)
            if border == "Double":
                gap = thickness + 3
                draw.rectangle((box[0] + gap, box[1] + gap, box[2] - gap, box[3] - gap),
                               outline=0, width=thickness)
    context = batch.context(index)
    for item in doc["elements"]:
        x, y = dots(item["x"]), dots(item["y"])
        size = (dots(item["w"]), dots(item["h"]))
        if min(size) <= 0 or size[0] > 1600 or size[1] > 120:
            raise ValueError("An element has an invalid size.")
        kind = item["kind"]
        if kind == "text":
            value = batch.expand(item["value"], context)
            layer = _text_image(item, value, size)
        elif kind == "barcode":
            layer = _barcode_image(item, batch.expand(item["value"], context), size)
        elif kind == "line":
            layer = Image.new("L", size, 0)
        elif item["image"]:
            source = ImageOps.contain(_read_image(item["image"]), size, Image.Resampling.LANCZOS)
            layer = Image.new("L", size, 255)
            layer.paste(source.convert("L"), ((size[0] - source.width) // 2, (size[1] - source.height) // 2),
                        source.getchannel("A"))
            if item["dither"]:
                layer = layer.convert("1").convert("L")
        else:
            continue
        # Composite black ink only. An element's white background leaves the design below visible.
        result.paste(0, (x, y, x + size[0], y + size[1]), ImageOps.invert(layer))
    if height > HEAD_DOTS:
        margin = (height - HEAD_DOTS) // 2
        result.paste(255, (0, 0, width, margin))
        result.paste(255, (0, margin + HEAD_DOTS, width, height))
    return result.point(lambda pixel: 0 if pixel < 185 else 255, mode="1")


def raster_packet(image, continuous=False):
    rotated = image.convert("L").transpose(Image.Transpose.ROTATE_270)
    raster_height = rotated.height + (56 if continuous else 0)
    raster = Image.new("L", (HEAD_DOTS, raster_height), 255)
    # Center both padding and the crop so all media share the same centerline.
    raster.paste(rotated, ((HEAD_DOTS - rotated.width) // 2, 0))
    ink = ImageOps.invert(raster).convert("1", dither=Image.Dither.NONE).tobytes()
    return bytes.fromhex("1f1124001b401d763000") + struct.pack("<HH", HEAD_DOTS // 8, raster_height) + ink
