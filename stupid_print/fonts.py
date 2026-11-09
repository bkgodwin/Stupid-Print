"""Discover and check the system font faces used by the label editor."""

import os
from dataclasses import dataclass
from functools import lru_cache
from itertools import count
from pathlib import Path

from PIL import ImageFont


ENGLISH_FONTS = (
    "Segoe UI", "Arial", "Aptos", "Calibri", "Verdana", "Tahoma", "Helvetica",
    "DejaVu Sans", "Liberation Sans", "Noto Sans", "Roboto", "Times New Roman",
    "Liberation Serif", "Georgia", "Consolas", "DejaVu Sans Mono", "Liberation Mono",
)
DEFAULT_FONTS = ("Segoe UI", "DejaVu Sans", "Liberation Sans", "Arial", *ENGLISH_FONTS)


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int

    def load(self, size):
        return ImageFont.truetype(str(self.path), size, index=self.index)


def _font_faces(path):
    sizes = (12, 109) if "emoji" in path.stem.casefold() else (12,)
    for index in count():
        face = FontFace(path, index)
        for size in sizes:
            try:
                names = face.load(size).getname()
            except (OSError, ValueError):
                continue
            yield face, names
            break
        else:
            return
        if path.suffix.lower() not in (".ttc", ".otc"):
            return


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
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc", ".otc"):
                continue
            for face, (family, style) in _font_faces(path):
                style = style.lower()
                bold = any(word in style for word in ("bold", "black", "heavy"))
                italic = "italic" in style or "oblique" in style
                variants = families.setdefault(family, {})
                priority = style in ("regular", "book", "normal", "roman", "bold", "italic",
                                     "oblique", "bold italic", "bold oblique")
                if (bold, italic) not in variants or priority:
                    variants[bold, italic] = face
    return families


def _draws_text(face):
    try:
        font = face.load(24)
        missing = bytes(font.getmask("\U0010FFFF"))
        for sample in ("Aa0", "ΑβΓ", "АяЖ", "中文字", "あカ語", "한글값", "ابج", "אבג", "अकह", "กขค"):
            glyphs = [font.getmask(char) for char in sample]
            patterns = {bytes(glyph) for glyph in glyphs if glyph.getbbox()}
            if len(patterns) == len(glyphs) and missing not in patterns:
                return True
    except (OSError, ValueError):
        return False
    return False


@lru_cache(maxsize=1)
def font_picker_sections():
    working = {name for name, variants in font_catalog().items()
               if not any(symbol in name.casefold() for symbol in
                          ("emoji", "wingdings", "webdings", "amgdt", "aigdt", "symbol"))
               and any(_draws_text(face) for face in variants.values())}
    recommended = ("Default", *(name for name in ENGLISH_FONTS if name in working))
    return recommended, tuple(sorted(working.difference(recommended), key=str.casefold))


@lru_cache(maxsize=256)
def select_font(family, size, bold=False, italic=False):
    catalog = font_catalog()
    for name in dict.fromkeys((family, *DEFAULT_FONTS)):
        variants = catalog.get(name)
        if not variants:
            continue
        preferred = ((bold, italic), (bold, False), (False, italic), (False, False), *variants)
        for actual in dict.fromkeys(preferred):
            face = variants.get(actual)
            if face is None:
                continue
            try:
                return face.load(size), bold and not actual[0], italic and not actual[1]
            except (OSError, ValueError):
                continue
    return ImageFont.load_default(size=size), bold, italic
