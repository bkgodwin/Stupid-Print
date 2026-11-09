"""Bundled designs that open as editable projects."""

from .model import element, new_document


def _text(value, x, y, w, h, size=9, **style):
    return element("text", value=value, x=x, y=y, w=w, h=h, size=size, **style)


def _graphic(asset, x=1.5, y=2, w=8, h=8):
    return element("graphic", asset=asset, x=x, y=y, w=w, h=h, dither=False)


def _code(value, symbology, x, y, side):
    return element("matrix", value=value, symbology=symbology, x=x, y=y, w=side, h=side)


def _rule(x, y, w, h=.2):
    return element("line", x=x, y=y, w=w, h=h)


def _design(title, elements, *, length=40, continuous=False, **batch):
    doc = new_document(title)
    doc.update(width=length, elements=elements)
    if continuous:
        doc["media"] = "Continuous tape"
    doc["batch"].update(batch)
    return doc


def _panel(ports):
    # Four 12-port sections stay within the editor's 200 mm limit.
    pitch = 13.5
    elements = []
    for port in range(12):
        x = port * pitch
        if port:
            elements.append(_rule(x, 2, .2, 8))
        elements.append(_text("{{port+" + str(port) + "}}", x + .5, 2, pitch - 1, 8, 16, bold=True))
    return _design(f"{ports}-port patch panel", elements, length=162, continuous=True,
                   count=str(ports // 12), port_step="12")


def bundled_templates():
    return {
        "asset": _design("Asset tag", [
            _text("PROPERTY OF", 1.5, .75, 24, 3.25, 8, align="Left"),
            _rule(1.5, 4.25, 23.5),
            _text("ASSET-{{serial}}", 1.5, 4.75, 25, 6, 13, align="Left", bold=True),
            _code("ASSET-{{serial}}", "QR Code", 28, .5, 11),
        ], serial_pad="4"),
        "flag": _design("Cable flag", [
            _text("{{hostname}}", 1, 1, 17, 10, 12, bold=True),
            _rule(19.875, 2, .25, 8),
            _text("{{hostname}}", 22, 1, 17, 10, 12, bold=True, rotation="180°"),
        ], continuous=True, hostname_prefix="LAN-", serial_pad="2"),
        "wrap": _design("Cable wrap", [
            _text("{{hostname}}", 1, 1, 11, 10, 10, bold=True, rotation="90°"),
            _text("{{hostname}}", 12.5, 1, 11, 10, 10, bold=True, rotation="90°"),
            _text("{{hostname}}", 24, 1, 11, 10, 10, bold=True, rotation="90°"),
        ], length=36, continuous=True, hostname_prefix="C-", serial_pad="2"),
        "panel24": _panel(24),
        "panel48": _panel(48),
        "rack": _design("Rack label", [
            _graphic("server"),
            _text("RACK {{serial}}", 11, 1, 27, 6, 14, bold=True, align="Left"),
            _text("ROW A  /  NETWORK", 11, 7, 27, 4, 8, align="Left"),
        ], serial_pad="2"),
        "lab": _design("Lab sample", [
            _text("SAMPLE {{serial}}", 1, 1, 17, 5, 10, bold=True, align="Left"),
            _text("{{date}}", 1, 6, 17, 4, 8, align="Left"),
            _code("S{{serial}}", "Data Matrix", 19, 1, 10),
        ], length=30, serial_pad="4"),
        "bin": _design("Inventory bin", [
            _graphic("shelf"),
            _text("AISLE A", 11, 1, 27, 4, 9, align="Left"),
            _text("BIN {{serial}}", 11, 5, 27, 6, 15, bold=True, align="Left"),
        ], serial_pad="2"),
        "calibration": _design("Calibration sticker", [
            _graphic("clipboard", 1.5, 2, 7, 8),
            _text("CALIBRATED  {{date}}", 10, 1, 29, 4.5, 8, align="Left"),
            _text("DUE  {{expiry}}", 10, 5.75, 29, 5.25, 11, bold=True, align="Left"),
        ], expiry_days="365"),
        "classroom": _design("Classroom name", [
            _text("Alex Morgan", 2, 1, 36, 6.5, 15, bold=True),
            _text("ROOM 204", 2, 7.5, 36, 3.5, 8),
        ]),
        "shipping": _design("Shipping carton", [
            _graphic("package"),
            _text("CARTON {{serial}}", 11, 1, 28, 6, 12, bold=True, align="Left"),
            _text("HANDLE WITH CARE", 11, 7, 28, 4, 8, align="Left"),
        ], serial_pad="3"),
        "network": _design("Network device", [
            _graphic("switch", 1, 1, 9, 10),
            _text("{{hostname}}", 11, 1, 27, 5.5, 12, bold=True, align="Left"),
            _text("{{mac}}", 11, 6.5, 27, 4.5, 8, align="Left"),
        ], serial_pad="2"),
    }
