"""Render label designs and encode a 203 dpi D30 raster."""

import base64
import io
import math
from pathlib import Path
import re
import struct
import unicodedata
from functools import lru_cache

import barcode
import zxingcpp
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, features

from .artwork import EMOJI_GRAPHICS, graphic_layer, vector_image
from .fonts import font_catalog, select_font as _font
from .model import MAX_DATA_BYTES, MAX_LABEL_TEXT, dimensions


DPI = 203
DOTS_PER_MM = 8
HEAD_DOTS = 96
TEXT_SCALE = 3
BARCODES = {"Code 128": "code128", "Code 39": "code39", "EAN-13": "ean13", "UPC-A": "upca"}
MATRIX_FORMATS = {"QR Code": (zxingcpp.QRCode, 4), "Data Matrix": (zxingcpp.DataMatrix, 1)}
HAS_EMOJI_SHAPING = features.check("raqm")


def dots(mm):
    return round(float(mm) * DOTS_PER_MM)


def _emoji_start(char):
    return 0x1F000 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF or char in EMOJI_GRAPHICS


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
            elif (follow in "\ufe0e\ufe0f\u20e3" or unicodedata.combining(follow)
                  or 0x1F3FB <= ord(follow) <= 0x1F3FF or 0xE0020 <= ord(follow) <= 0xE007F):
                pos += 1
            else:
                break
        cluster = text[start:pos]
        if _emoji_start(char) or "\ufe0f" in cluster or cluster.endswith("\u20e3"):
            if regular:
                yield regular, False
                regular = ""
            yield cluster, True
        else:
            regular += cluster
    if regular:
        yield regular, False


def _emoji_badge(value, size):
    image = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(image)
    font, _, _ = _font("Default", max(1, round(size * (.5 if len(value) > 1 else .65))), bold=True)
    draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=size // 6,
                           outline=0, width=max(1, size // 13))
    draw.text((size // 2, size // 2), value, font=font, fill=0, anchor="mm")
    return image


def _emoji_glyph(font, value):
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = measure.textbbox((0, 0), value, font=font, embedded_color=True)
    if right <= left or bottom <= top:
        return None
    image = Image.new("RGBA", (right - left, bottom - top))
    ImageDraw.Draw(image).text((-left, -top), value, font=font, fill="black", embedded_color=True)
    bounds = image.getchannel("A").getbbox()
    return image.crop(bounds) if bounds else None


def _system_emoji(cluster, size):
    for family in ("Segoe UI Emoji", "Noto Color Emoji", "Noto Emoji", "Symbola",
                   "Segoe UI Symbol", "DejaVu Sans"):
        variants = font_catalog().get(family)
        if not variants:
            continue
        face = variants.get((False, False)) or next(iter(variants.values()))
        for font_size in (max(20, size * 2), 109):
            try:
                font = face.load(font_size)
                image = _emoji_glyph(font, cluster)
                missing = _emoji_glyph(font, "\U0010FFFF")
                if image is None or (missing is not None and
                                     (image.size, image.tobytes()) == (missing.size, missing.tobytes())):
                    break
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                white = Image.new("RGBA", image.size, "white")
                gray = ImageOps.autocontrast(Image.alpha_composite(white, image).convert("L"))
                if ImageOps.invert(gray).getbbox() is None:
                    break
                return gray
            except (OSError, ValueError):
                continue
    return None


@lru_cache(maxsize=192)
def _emoji_image(cluster, size):
    plain = cluster.replace("\ufe0f", "").replace("\ufe0e", "")
    if key := EMOJI_GRAPHICS.get(plain):
        image = vector_image(key, (size, size))
        return image.crop(ImageOps.invert(image).getbbox())
    if len(plain) == 2 and plain[-1] == "\u20e3" and plain[0] in "#*0123456789":
        return _emoji_badge(plain[0], size)
    joined = "\u200d" in plain
    if not joined or HAS_EMOJI_SHAPING:
        if (image := _system_emoji(plain, size)) is not None:
            return image
    if joined:
        images = [_emoji_image(part, size) for part in plain.split("\u200d") if part]
        if images:
            gap = max(1, size // 12)
            strip = Image.new("L", (sum(image.width for image in images) + gap * (len(images) - 1), size), 255)
            left = 0
            for image in images:
                strip.paste(image, (left, (size - image.height) // 2))
                left += image.width + gap
            return strip
    if len(plain) == 2 and all(0x1F1E6 <= ord(char) <= 0x1F1FF for char in plain):
        return _emoji_badge("".join(chr(ord(char) - 0x1F1E6 + ord("A")) for char in plain), size)
    return _emoji_badge("?", size)


def _run_width(run, font, size, stroke):
    text, emoji = run
    image = _emoji_image(text, size) if emoji else None
    return image.width + max(1, size // 12) if image is not None else math.ceil(font.getlength(text)) + 2 * stroke


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


def _text_image(item, value, size, smooth=False):
    width, height = (side * TEXT_SCALE for side in size)
    points = float(item["size"])
    if not 3 <= points <= 96:
        raise ValueError("Text size must be between 3 and 96 pt.")
    start = round(points * DPI * TEXT_SCALE / 72)
    if item["fit"]:
        start = min(start, max(6 * TEXT_SCALE, height))
    minimum = min(start, 6 * TEXT_SCALE)
    # Include the minimum even when the initial size falls between native dots.
    candidates = [*range(start, minimum, -TEXT_SCALE), minimum]
    for pixels in candidates:
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
    result = Image.new("L", (width, height), 255)
    emoji_mask = None
    for line, line_width in zip(lines, widths):
        padding = 2 * TEXT_SCALE
        line_image = Image.new("L", (max(1, min(width + padding, line_width + shear + padding)), leading), 255)
        draw = ImageDraw.Draw(line_image)
        line_mask = None
        x = 0
        for run in line:
            content, emoji = run
            image = _emoji_image(content, pixels) if emoji else None
            if image is None:
                draw.text((x + stroke, ascent), content, font=font, fill=0, anchor="ls", stroke_width=stroke)
            else:
                y = max(0, (leading - image.height) // 2)
                line_image.paste(image, (x, y))
                if not smooth:
                    if line_mask is None:
                        line_mask = Image.new("L", line_image.size)
                    line_mask.paste(255, (x, y, x + image.width, y + image.height))
            x += _run_width(run, font, pixels, stroke)
        if item["underline"] and x:
            y = min(leading - 1, ascent + max(1, pixels // 14))
            draw.line((0, y, x - 1, y), fill=0, width=max(TEXT_SCALE, pixels // 13))
        if fake_italic:
            skew = (1, 0.2, -shear, 0, 1, 0)
            line_image = line_image.transform(line_image.size, Image.Transform.AFFINE,
                                              skew,
                                              resample=Image.Resampling.BICUBIC, fillcolor=255)
            if line_mask is not None:
                line_mask = line_mask.transform(line_mask.size, Image.Transform.AFFINE, skew)
        left = {"Left": 0, "Center": (width - line_width - shear) // 2,
                "Right": width - line_width - shear}[item["align"]]
        result.paste(line_image, (left, top))
        if line_mask is not None:
            if emoji_mask is None:
                emoji_mask = Image.new("L", result.size)
            emoji_mask.paste(line_mask, (left, top))
        top += leading
    if smooth:
        return result
    # Convert high-resolution coverage to native dots without the old dark cutoff
    # thickening every partially covered edge. Preserve light strokes in tiny type.
    threshold = 165 if pixels <= 16 * TEXT_SCALE else 145
    native = result.resize(size, Image.Resampling.LANCZOS)
    ink = native.point(lambda p: 0 if p < threshold else 255)
    if emoji_mask is not None:
        dithered = native.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
        ink.paste(dithered, (0, 0), emoji_mask.resize(size, Image.Resampling.NEAREST))
    return ink


def _barcode_image(item, value, size):
    name = item["symbology"]
    retail = name in ("EAN-13", "UPC-A")
    if retail:
        value = re.sub(r"[\s-]+", "", value)
        if name == "UPC-A" and len(value) == 13 and value.startswith("0"):
            value = value[1:]
        digits = 12 if name == "EAN-13" else 11
        if not value.isascii() or not value.isdigit() or len(value) not in (digits, digits + 1):
            example = " An EAN-13 scan with a leading zero also works." if name == "UPC-A" else ""
            raise ValueError(f"{name} needs {digits} digits plus an optional check digit.{example}")
    options = {"add_checksum": False} if name == "Code 39" else {}
    if not value:
        raise ValueError("Barcode value is empty.")
    try:
        code = barcode.get_barcode_class(BARCODES[name])(value, **options)
        canonical = code.get_fullcode()
        if retail and len(value) == len(canonical) and value != canonical:
            raise ValueError(f"{name} check digit should be {canonical[-1]}.")
        pattern = code.build()[0]
    except (barcode.errors.BarcodeError, UnicodeError, ValueError, IndexError) as exc:
        raise ValueError(f"{name}: {exc}") from exc
    width, height = size
    quiet_left, quiet_right = {"UPC-A": (9, 9), "EAN-13": (11, 7)}.get(name, (12, 12))
    module = width // (len(pattern) + quiet_left + quiet_right)
    minimum_height = 24 if retail else 16
    if not module or height < minimum_height:
        raise ValueError(f"Make the {name} box larger or use a shorter value.")
    if module == 1 and not item.get("compact", False):
        needed = (len(pattern) + quiet_left + quiet_right) * 2 / DOTS_PER_MM
        raise ValueError(f"The {name} needs a wider box for 2-dot modules ({needed:g} mm). "
                         "Use a wider box, shorten the value, or enable compact bars.")
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    spare = width - (len(pattern) + quiet_left + quiet_right) * module
    left = quiet_left * module + spare // 2
    caption = item["caption"] and height >= (38 if retail else 27)
    bars = height - 14 if caption else height
    for index, bit in enumerate(pattern):
        if bit != "0":
            x = left + index * module
            extension = 0
            if retail and caption:
                edge = 10 if name == "UPC-A" else 3
                if index < edge or 45 <= index < 50 or index >= len(pattern) - edge:
                    extension = min(5 * module, height - bars)
            draw.rectangle((x, 0, x + module - 1, bars + extension - 1), fill=0)
    if caption:
        font, _, _ = _font("Default", 11, bold=retail)
        if name == "UPC-A":
            labels = ((-4.5, canonical[0]), (27.5, canonical[1:6]),
                      (67.5, canonical[6:11]), (99.5, canonical[11]))
        elif name == "EAN-13":
            labels = ((-5.5, canonical[0]), (24, canonical[1:7]), (71, canonical[7:]))
        else:
            labels = (((width / 2 - left) / module, canonical),)
        for position, digits in labels:
            draw.text((round(left + position * module), height - 1),
                      digits, fill=0, font=font, anchor="ms")
    return image, bars


@lru_cache(maxsize=128)
def _matrix_modules(symbology, value, correction):
    format_code, _ = MATRIX_FORMATS[symbology]
    options = {"ec_level": correction} if symbology == "QR Code" else {}
    try:
        code = zxingcpp.create_barcode(value, format_code, **options)
        return Image.fromarray(code.to_image(scale=1, add_quiet_zones=False)).copy()
    except (RuntimeError, ValueError, UnicodeError) as exc:
        raise ValueError(f"Cannot encode the {symbology} value. Check the content or shorten it.") from exc


def _matrix_image(item, value, size):
    name = item["symbology"]
    if not value.strip():
        raise ValueError(f"Enter a value for the {name}.")
    modules = _matrix_modules(name, value, item["correction"])
    _, quiet = MATRIX_FORMATS[name]
    columns, rows = modules.width + 2 * quiet, modules.height + 2 * quiet
    module = min(size[0] // columns, size[1] // rows)
    if module < 2:
        raise ValueError(f"The {name} needs at least {columns * 2 / DOTS_PER_MM:g} × "
                         f"{rows * 2 / DOTS_PER_MM:g} mm for 2-dot modules. "
                         "Enlarge the box or shorten the value.")
    raster = modules.resize((modules.width * module, modules.height * module), Image.Resampling.NEAREST)
    layer = Image.new("L", size, 255)
    layer.paste(raster, ((size[0] - raster.width) // 2, (size[1] - raster.height) // 2))
    return layer


def embed_image(path):
    path = Path(path)
    if path.stat().st_size > MAX_DATA_BYTES:
        raise ValueError("Images must be 32 MB or smaller.")
    try:
        with Image.open(path, formats=("PNG", "JPEG", "BMP", "GIF", "WEBP", "TIFF")) as source:
            if source.width * source.height > 32_000_000:
                raise ValueError("Resize the image to 32 megapixels or smaller.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
            stream = io.BytesIO()
            image.save(stream, format="PNG", optimize=True)
    except Image.DecompressionBombError as exc:
        raise ValueError("Resize the image to 32 megapixels or smaller.") from exc
    return base64.b64encode(stream.getvalue()).decode("ascii")


@lru_cache(maxsize=4)
def _read_image(encoded):
    if len(encoded) > 12 * 1024 * 1024:
        raise ValueError("Embedded artwork is too large. Replace it with a smaller image.")
    try:
        with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)), formats=("PNG",)) as source:
            if max(source.size) > 1600 or min(source.size) > 1200:
                raise ValueError("Embedded artwork exceeds the supported size. Replace the image.")
            return source.convert("RGBA")
    except Image.DecompressionBombError as exc:
        raise ValueError("Embedded artwork is too large. Replace the image.") from exc


def _picture(item, size, smooth=False):
    source = ImageOps.contain(_read_image(item["image"]), size, Image.Resampling.LANCZOS)
    # Work on the artwork before adding the empty margins of the image box.
    gray = Image.new("L", source.size, 255)
    gray.paste(source.convert("L"), (0, 0), source.getchannel("A"))
    gray = ImageOps.autocontrast(gray, cutoff=1, preserve_tone=True)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=0.8, percent=85, threshold=3))
    gray = gray.point(lambda pixel: 255 if pixel >= 245 else (0 if pixel <= 12 else pixel))
    if not smooth and item["dither"]:
        gray = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    elif not smooth:
        gray = gray.point(lambda pixel: 0 if pixel < 155 else 255)
    layer = Image.new("L", size, 255)
    layer.paste(gray, ((size[0] - gray.width) // 2, (size[1] - gray.height) // 2))
    return layer


def render_label(doc, batch, index, *, smooth=False):
    """Compose the same design as native dots or high-resolution editor artwork."""
    scale = TEXT_SCALE if smooth else 1
    width, height = (dots(side) * scale for side in dimensions(doc))
    head = HEAD_DOTS * scale
    margin = max(0, ((height // scale - HEAD_DOTS) // 2) * scale)
    result = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(result)
    border = doc["border"]
    if border != "None":
        inset = dots(0.6) * scale
        top = max(inset, (height - head) // 2 + inset)
        box = (inset, top, width - inset - 1, height - top - 1)
        thickness = max(1, min(8, int(doc["border_width"]))) * scale
        if border == "Rounded":
            draw.rounded_rectangle(box, radius=dots(1.6) * scale, outline=0, width=thickness)
        else:
            draw.rectangle(box, outline=0, width=thickness)
            if border == "Double":
                gap = thickness + 3 * scale
                draw.rectangle((box[0] + gap, box[1] + gap, box[2] - gap, box[3] - gap),
                               outline=0, width=thickness)
    context = batch.context(index)
    scan_regions = []
    for item in doc["elements"]:
        x, y = dots(item["x"]) * scale, dots(item["y"]) * scale
        size = (dots(item["w"]), dots(item["h"]))
        if min(size) <= 0 or size[0] > 1600 or size[1] > 120:
            raise ValueError("An element has an invalid size.")
        kind = item["kind"]
        display_size = (size[0] * scale, size[1] * scale)
        if kind == "text":
            value = batch.expand(item["value"], context)
            if len(value) > MAX_LABEL_TEXT:
                raise ValueError(f"Label text must be {MAX_LABEL_TEXT:,} characters or fewer after field expansion.")
            rotation = item.get("rotation", "0°")
            text_size = size[::-1] if rotation in ("90°", "270°") else size
            layer = _text_image(item, value, text_size, smooth=smooth)
            if rotation != "0°":
                layer = layer.rotate(-int(rotation[:-1]), expand=True)
        elif kind in ("barcode", "matrix"):
            if (x < 0 or x + display_size[0] > width or y < margin
                    or y + display_size[1] > min(height, margin + head)):
                raise ValueError("Move the barcode box inside the printable area.")
            value = batch.expand(item["value"], context)
            if len(value) > 3000:
                raise ValueError("Shorten the barcode value to fit the label.")
            if kind == "matrix":
                layer, bars = _matrix_image(item, value, size), size[1]
            else:
                layer, bars = _barcode_image(item, value, size)
            if smooth:
                layer = layer.resize(display_size, Image.Resampling.NEAREST)
            # White spaces and quiet zones are part of a scannable symbol.
            result.paste(layer, (x, y))
            region = (x, y, x + display_size[0], y + bars * scale)
            scan_regions.append((region, layer.crop((0, 0, display_size[0], bars * scale))))
            continue
        elif kind == "line":
            layer = Image.new("L", display_size, 0)
        elif kind == "graphic":
            layer = graphic_layer(item["asset"], size, smooth=smooth, dither=item["dither"])
        elif kind == "image" and item["image"]:
            layer = _picture(item, display_size, smooth=smooth)
        else:
            continue
        # Composite black ink only. An element's white background leaves the design below visible.
        result.paste(0, (x, y, x + display_size[0], y + display_size[1]), ImageOps.invert(layer))
    for region, expected in scan_regions:
        if ImageChops.difference(result.crop(region), expected).getbbox():
            raise ValueError("Artwork covers part of the barcode. Move it or raise the barcode layer.")
    if height > head:
        result.paste(255, (0, 0, width, margin))
        result.paste(255, (0, margin + head, width, height))
    return result if smooth else result.convert("1", dither=Image.Dither.NONE)


def head_raster(image, rotation, extra_rows=0):
    rotated = image.convert("L").transpose(rotation)
    raster_height = rotated.height + extra_rows
    raster = Image.new("L", (HEAD_DOTS, raster_height), 255)
    # Center both padding and the crop so all media share the same centerline.
    raster.paste(rotated, ((HEAD_DOTS - rotated.width) // 2, 0))
    return raster


def raster_packet(image, continuous=False):
    raster = head_raster(image, Image.Transpose.ROTATE_270, 56 if continuous else 0)
    ink = ImageOps.invert(raster).convert("1", dither=Image.Dither.NONE).tobytes()
    return bytes.fromhex("1f1124001b401d763000") + struct.pack("<HH", HEAD_DOTS // 8, raster.height) + ink
