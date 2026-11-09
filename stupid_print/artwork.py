"""Built-in graphics on a 24-unit vector grid. Label files reference the keys."""

from dataclasses import dataclass
from math import cos, pi, sin

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class Graphic:
    name: str
    category: str
    parts: tuple
    stretch: bool = False


def box(bounds, fill=255, edge=0, weight=1.5, radius=0):
    return "box", bounds, fill, edge, weight, radius


def oval(bounds, fill=255, edge=0, weight=1.5):
    return "oval", bounds, fill, edge, weight, 0


def polygon(points, fill=255, edge=0, weight=1.5):
    return "polygon", points, fill, edge, weight, 0


def stroke(points, weight=1.5, ink=0):
    return "line", points, None, ink, weight, 0


def arc(bounds, start, end, weight=1.5):
    return "arc", bounds, None, 0, weight, (start, end)


def regular_polygon(sides, inner=0):
    count = sides * (2 if inner else 1)
    return tuple((12 + radius * cos(i * 2 * pi / count - pi / 2),
                  12 + radius * sin(i * 2 * pi / count - pi / 2))
                 for i in range(count) for radius in (inner if i % 2 and inner else 10,))


def inventory(name, *parts):
    return Graphic(name, "Inventory", parts)


def it(name, *parts):
    return Graphic(name, "IT", parts)


def symbol(name, *parts):
    return Graphic(name, "Symbols", parts)


def shape(name, *parts):
    return Graphic(name, "Shapes", parts, stretch=True)


GRAPHICS = {
    "package": inventory("Shipping box",
        polygon(((2, 6), (12, 2), (22, 6), (12, 10)), 232),
        polygon(((2, 6), (12, 10), (12, 22), (2, 17)), 246),
        polygon(((12, 10), (22, 6), (22, 17), (12, 22)), 162),
        stroke(((7, 4), (17, 8), (17, 13)), 1.5)),
    "tag": inventory("Asset tag",
        polygon(((2, 5), (15, 5), (22, 12), (15, 19), (2, 19)), 222),
        oval((15, 10, 19, 14), 255), stroke(((5, 10), (12, 10))), stroke(((5, 14), (10, 14)))),
    "shelf": inventory("Storage shelf",
        stroke(((3, 3), (3, 22)), 2), stroke(((21, 3), (21, 22)), 2),
        box((4, 12, 20, 15), 135), box((4, 19, 20, 21), 135),
        box((6, 6, 11, 12), 220), box((13, 8, 18, 12), 235)),
    "pallet": inventory("Pallet",
        box((3, 13, 21, 16), 135), box((2, 19, 22, 21), 135),
        box((4, 16, 7, 19), 175), box((17, 16, 20, 19), 175),
        box((4, 5, 11, 13), 237), box((12, 4, 20, 13), 208),
        stroke(((15, 4), (15, 8)))),
    "clipboard": inventory("Checklist",
        box((4, 4, 20, 22), 235, radius=2), box((8, 2, 16, 6), 155, radius=1),
        stroke(((7, 11), (9, 13), (12, 9))), stroke(((13, 12), (17, 12))),
        stroke(((7, 17), (9, 19), (12, 15))), stroke(((13, 18), (17, 18)))),
    "truck": inventory("Delivery truck",
        box((2, 5, 14, 17), 210),
        polygon(((14, 8), (18, 8), (22, 12), (22, 17), (14, 17)), 237),
        stroke(((16, 11), (18, 11), (20, 13))), oval((4, 15, 10, 21), 255),
        oval((15, 15, 21, 21), 255)),
    "pin": inventory("Location pin",
        polygon(((5, 11), (12, 22), (19, 11)), 190, None),
        oval((4, 2, 20, 18), 190, None), oval((9, 7, 15, 13), 255),
        stroke(((5, 13), (12, 22), (19, 13)), 1.8)),
    "fragile": inventory("Fragile",
        polygon(((6, 3), (18, 3), (17, 10), (14, 14), (10, 14), (7, 10)), 232),
        stroke(((12, 14), (12, 21)), 2), stroke(((7, 21), (17, 21)), 2),
        stroke(((12, 3), (10, 8), (13, 8), (11, 12)))),
    "tools": inventory("Wrench",
        polygon(((20, 2), (22, 7), (19, 11), (14, 12), (6, 21), (3, 21), (2, 18),
                 (12, 9), (12, 5), (16, 2), (17, 3), (15, 6), (17, 8), (20, 5)), 179),
        oval((4, 17, 7, 20), 255, None)),
    "recycle": inventory("Recycle",
        polygon(((8, 4), (11, 2), (15, 3), (18, 8), (20, 7), (19, 12), (14, 11),
                 (16, 10), (13, 5), (11, 5), (9, 8), (6, 7)), 0, None),
        polygon(((20, 13), (22, 16), (21, 20), (17, 22), (13, 22), (13, 24), (9, 20),
                 (13, 17), (13, 19), (18, 19), (19, 17), (17, 14)), 0, None),
        polygon(((6, 21), (3, 19), (2, 16), (5, 10), (3, 9), (8, 8), (10, 13),
                 (8, 12), (5, 17), (7, 18), (9, 18), (9, 21)), 0, None)),
    "monitor": it("Monitor",
        box((2, 3, 22, 17), 185, radius=2), box((4, 5, 20, 14), 247, None),
        stroke(((6, 12), (9, 9), (12, 11), (16, 7)), 1.3),
        stroke(((12, 17), (12, 21)), 2), stroke(((7, 21), (17, 21)), 2)),
    "laptop": it("Laptop",
        box((4, 3, 20, 16), 175, radius=1.5), box((6, 5, 18, 13), 242, None),
        polygon(((4, 16), (20, 16), (23, 21), (1, 21)), 212),
        stroke(((9, 19), (15, 19)), 1.2)),
    "server": it("Server rack",
        *(part for y in (3, 9, 15) for part in
          (box((3, y, 21, y + 5), 185, radius=1),
           oval((5, y + 1, 8, y + 4), 0, None), stroke(((12, y + 2.5), (18, y + 2.5)), 1)))),
    "switch": it("Network switch",
        box((2, 6, 22, 18), 190, radius=1.5),
        *(box((x, 9, x + 3, 13), 255, 0, 1) for x in (4, 8, 12, 16)),
        stroke(((4, 15), (19, 15)), 1)),
    "wifi": it("Wi-Fi",
        arc((1, 3, 23, 21), 211, 329, 2), arc((5, 8, 19, 21), 210, 330, 2),
        arc((9, 13, 15, 21), 210, 330, 1.7), oval((10.6, 18, 13.4, 21), 0, None)),
    "printer": it("Printer",
        box((6, 2, 18, 9), 248), box((2, 8, 22, 18), 176, radius=2),
        oval((17, 10, 20, 13), 255, None), box((6, 14, 18, 22), 248),
        stroke(((9, 17), (15, 17)), 1), stroke(((9, 19), (14, 19)), 1)),
    "drive": it("Hard drive",
        box((4, 2, 20, 22), 181, radius=2), oval((6, 4, 18, 16), 239),
        oval((10, 8, 14, 12), 255), stroke(((12, 10), (16, 17)), 1.5),
        stroke(((8, 19), (16, 19)), 1)),
    "battery": it("Battery",
        box((4, 6, 19, 18), 248), box((19, 9, 22, 15), 160),
        box((6, 8, 13, 16), 143, None), stroke(((8, 12), (11, 12)), 1.4)),
    "plug": it("Power plug",
        stroke(((8, 2), (8, 8)), 2), stroke(((16, 2), (16, 8)), 2),
        box((5, 8, 19, 15), 175, radius=1.5),
        polygon(((7, 15), (17, 15), (14, 18), (10, 18)), 218),
        stroke(((12, 18), (12, 22)), 2)),
    "lock": it("Padlock",
        arc((6, 2, 18, 15), 180, 360, 2),
        box((4, 9, 20, 22), 179, radius=2), oval((10, 12, 14, 16), 0, None),
        stroke(((12, 15), (12, 19)), 2)),
    "key": it("Key",
        polygon(((4, 18), (14, 8), (18, 12), (14, 16), (12, 16), (12, 18),
                 (10, 18), (10, 21), (4, 21)), 179),
        oval((11, 2, 22, 13), 213), oval((15, 5, 19, 9), 255)),
    "mobile": it("Mobile phone",
        box((6, 2, 18, 22), 180, radius=2), box((8, 5, 16, 17), 250, None),
        stroke(((10, 19.5), (14, 19.5)), 1.3)),
    "camera": it("Camera",
        box((7, 4, 13, 8), 190, radius=1), box((2, 7, 22, 20), 196, radius=2),
        oval((7, 8.5, 17, 18.5), 247), oval((10, 11.5, 14, 15.5), 145),
        stroke(((17, 10), (20, 10)), 1.5)),
    "cloud": it("Cloud",
        oval((2, 10, 13, 19), 195, None), oval((6, 5, 18, 19), 195, None),
        oval((13, 9, 22, 19), 195, None), stroke(((6, 19), (18, 19)), 1.8),
        arc((2, 10, 13, 19), 90, 245), arc((6, 5, 18, 19), 182, 338),
        arc((13, 9, 22, 19), 259, 450)),
    "warning": symbol("Warning",
        polygon(((12, 2), (22, 21), (2, 21)), 231),
        stroke(((12, 8), (12, 14)), 2.3), oval((10.8, 16.1, 13.2, 18.5), 0, None)),
    "check": symbol("Check mark", stroke(((3, 12), (9, 18), (21, 5)), 3.2)),
    "cross": symbol("Cross", stroke(((5, 5), (19, 19)), 3), stroke(((19, 5), (5, 19)), 3)),
    "star": symbol("Star", polygon(regular_polygon(5, 4.8), 0, None)),
    "bolt": symbol("Lightning",
        polygon(((13, 2), (5, 13), (11, 13), (9, 22), (20, 10), (14, 10), (17, 2)), 0, None)),
    "heart": symbol("Heart",
        oval((2, 4, 13, 15), 0, None), oval((11, 4, 22, 15), 0, None),
        polygon(((2, 10), (22, 10), (20, 14), (12, 22), (4, 14)), 0, None)),
    "mail": symbol("Envelope",
        box((2, 5, 22, 19), 221, radius=1), stroke(((2, 6), (12, 14), (22, 6))),
        stroke(((2, 18), (9, 12))), stroke(((22, 18), (15, 12)))),
    "telephone": symbol("Telephone",
        polygon(((4, 3), (8, 3), (11, 9), (8, 11), (12, 16), (15, 17), (17, 14),
                 (22, 17), (21, 21), (17, 22), (11, 20), (5, 14), (2, 7)), 0, None)),
    "smile": symbol("Smiling face",
        oval((2, 2, 22, 22), 239), oval((6, 7, 9, 11), 0, None),
        oval((15, 7, 18, 11), 0, None), arc((6, 8, 18, 18), 10, 170, 2)),
    "rocket": symbol("Rocket",
        polygon(((11, 14), (8, 20), (5, 19), (6, 14), (10, 10)), 158),
        polygon(((10, 14), (14, 7), (18, 3), (22, 2), (21, 7), (17, 13), (12, 17)), 226),
        oval((15, 6, 19, 10), 255), stroke(((8, 17), (3, 22)), 2)),
    "rectangle": shape("Rectangle", box((2, 3, 22, 21), 222)),
    "rounded": shape("Rounded rectangle", box((2, 3, 22, 21), 222, radius=3)),
    "oval": shape("Oval", oval((2, 2, 22, 22), 222)),
    "triangle": shape("Triangle", polygon(((12, 2), (22, 21), (2, 21)), 222)),
    "diamond": shape("Diamond", polygon(((12, 2), (22, 12), (12, 22), (2, 12)), 222)),
    "hexagon": shape("Hexagon", polygon(regular_polygon(6), 222)),
    "arrow": shape("Right arrow",
        polygon(((2, 8), (14, 8), (14, 3), (22, 12), (14, 21), (14, 16), (2, 16)), 180)),
    "rule": shape("Horizontal rule", box((1, 10, 23, 14), 0, None)),
}


EMOJI_GRAPHICS = {
    "★": "star", "⭐": "star", "✓": "check", "✔": "check", "✅": "check", "❌": "cross",
    "⚠": "warning", "♥": "heart", "❤": "heart", "☎": "telephone", "✉": "mail",
    "⚡": "bolt", "♻": "recycle", "🏷": "tag", "🔧": "tools", "🛠": "tools",
    "📦": "package", "📋": "clipboard", "📍": "pin", "🚚": "truck", "🔌": "plug",
    "🔋": "battery", "🔒": "lock", "🔑": "key", "💻": "laptop", "🖥": "monitor",
    "🖨": "printer", "📱": "mobile", "📷": "camera", "☁": "cloud", "💾": "drive",
    "😀": "smile", "🙂": "smile", "🚀": "rocket", "➡": "arrow",
}


def vector_image(key, size):
    """Draw the built-in geometry into a grayscale image at the requested size."""
    graphic = GRAPHICS[key]
    width, height = size
    sx, sy = (width - 1) / 24, (height - 1) / 24
    if not graphic.stretch:
        sx = sy = min(sx, sy)
    ox, oy = (width - 1 - sx * 24) / 2, (height - 1 - sy * 24) / 2
    scale = min(sx, sy)

    def point(x, y):
        return round(ox + x * sx), round(oy + y * sy)

    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    for kind, coords, fill, edge, weight, extra in graphic.parts:
        thickness = max(1, round(weight * scale))
        if kind in ("line", "polygon"):
            vertices = [point(x, y) for x, y in coords]
            if kind == "line":
                draw.line(vertices, fill=edge, width=thickness, joint="curve")
            else:
                draw.polygon(vertices, fill=fill, outline=edge, width=thickness)
            continue
        left, top, right, bottom = coords
        bounds = (*point(left, top), *point(right, bottom))
        if kind == "box":
            draw.rounded_rectangle(bounds, radius=round(extra * scale), fill=fill,
                                   outline=edge, width=thickness)
        elif kind == "oval":
            draw.ellipse(bounds, fill=fill, outline=edge, width=thickness)
        else:
            draw.arc(bounds, *extra, fill=edge, width=thickness)
    return image


def graphic_layer(key, size, smooth=False, dither=True):
    layer = vector_image(key, (size[0] * 3, size[1] * 3))
    if smooth:
        return layer
    layer = layer.resize(size, Image.Resampling.LANCZOS)
    if dither:
        return layer.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    return layer.point(lambda pixel: 0 if pixel < 150 else 255)
