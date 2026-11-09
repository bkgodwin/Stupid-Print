"""Element geometry in label millimeters."""

from .model import dimensions


DOT = 0.125
PRINT_WIDTH = 12


def printable_area(doc):
    width, height = dimensions(doc)
    top = max(0, (height - PRINT_WIDTH) / 2)
    return 0, top, width, height - top


def bounds(items):
    return (min(item["x"] for item in items), min(item["y"] for item in items),
            max(item["x"] + item["w"] for item in items),
            max(item["y"] + item["h"] for item in items))


def move(items, origins, dx, dy, page, snap=False):
    left, top, right, bottom = origins
    if snap:
        dx = round(left + dx) - left
        dy = round(top + dy) - top
    dx = min(max(dx, -left), max(-left, page[0] - right))
    dy = min(max(dy, -top), max(-top, page[1] - bottom))
    for item in items:
        item["x"] = round(item["x"] + dx, 3)
        item["y"] = round(item["y"] + dy, 3)


def fit_box(item, page):
    width, height = page
    item["w"] = min(item["w"], width)
    item["h"] = min(item["h"], height)
    item["x"] = min(item["x"], width - item["w"])
    item["y"] = min(item["y"], height - item["h"])


def align(items, doc, axis, anchor, to_label=False):
    """Align members to each other, or move the selection as a block."""
    group = bounds(items)
    if to_label or len(items) == 1:
        target = printable_area(doc)
        group_point = group[axis] + anchor * (group[axis + 2] - group[axis])
        target_point = target[axis] + anchor * (target[axis + 2] - target[axis])
        offset = target_point - group_point
        move(items, group, offset if axis == 0 else 0, offset if axis == 1 else 0, dimensions(doc))
    else:
        position, size = ("x", "w") if axis == 0 else ("y", "h")
        for item in items:
            item[position] = round(group[axis] + anchor * (group[axis + 2] - group[axis] - item[size]), 3)


def distribute(items, axis):
    """Space the selected boxes evenly between their current outside edges."""
    if len(items) < 3:
        raise ValueError("Select at least three elements to distribute.")
    position, size = ("x", "w") if axis == 0 else ("y", "h")
    ordered = sorted(items, key=lambda item: (item[position], item[position] + item[size]))
    group = bounds(items)
    start, end = group[axis], group[axis + 2]
    gap = (end - start - sum(item[size] for item in ordered)) / (len(items) - 1)
    if gap < -1e-9:
        raise ValueError("Move the outer elements farther apart to make room for even spacing.")
    for item in ordered:
        item[position] = round(start, 3)
        start += item[size] + gap
