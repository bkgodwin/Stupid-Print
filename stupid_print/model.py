"""Portable documents, tabular data, and indexed batch expansion."""

import csv
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from .artwork import GRAPHICS


EXTENSION = ".stupidprint"
TOKEN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
DATE_OFFSET = re.compile(r"date([+-]\d+)d")
DATE_FORMATS = {"YYYY-MM-DD": "%Y-%m-%d", "MM/DD/YYYY": "%m/%d/%Y",
                "DD/MM/YYYY": "%d/%m/%Y", "DD MMM YYYY": "%d %b %Y"}
MAC_FORMATS = ("Colon", "Hyphen", "Dot")
MATRIX_CODES = ("QR Code", "Data Matrix")
QR_LEVELS = ("L", "M", "Q", "H")
BATCH_DEFAULTS = {
    "count": "1", "serial_start": "1", "serial_step": "1", "serial_pad": "0",
    "ip_start": "192.168.1.1", "ip_mask": "255.255.255.0", "ip_step": "1",
    "mac_oui": "02:00:00", "mac_start": "000001", "mac_step": "1", "mac_format": "Colon",
    "hostname_prefix": "host-", "port_start": "1", "port_step": "1",
    "date_format": "YYYY-MM-DD", "expiry_days": "30",
}
PORT_FIELD = re.compile(r"port(?:\+(\d+))?")
PRESETS = {"40 × 12 mm": (40, 12), "40 × 14 mm": (40, 14), "30 × 12 mm": (30, 12), "22 × 12 mm": (22, 12),
           "12 × 12 mm": (12, 12), "30 × 14 mm": (30, 14), "40 × 15 mm": (40, 15)}


def element(kind, **values):
    item = {"id": uuid4().hex, "kind": kind, "x": 2, "y": 2, "w": 36, "h": 8}
    if kind == "text":
        item.update(value="Your label", font="Default", size=12, align="Center",
                    valign="Middle", bold=False, italic=False, underline=False, fit=True, rotation="0°")
    elif kind == "barcode":
        item.update(value="12345", symbology="Code 128", caption=True, compact=False)
    elif kind == "matrix":
        item.update(value="ASSET-001", symbology="QR Code", correction="M")
    elif kind == "image":
        item.update(image="", filename="", dither=True)
    elif kind == "graphic":
        item.update(asset="package", dither=True)
    item.update(values)
    return item


def new_document(title="Untitled label", kind="project"):
    return {
        "version": 1, "id": uuid4().hex, "title": title, "kind": kind,
        "width": 40, "height": 12, "media": "Gap labels", "border": "None", "border_width": 1,
        "elements": [element("text")],
        "batch": BATCH_DEFAULTS.copy(),
        "data": {"name": "", "headers": [], "rows": []},
    }


def app_directory():
    if override := os.environ.get("STUPID_PRINT_DATA_DIR"):
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Stupid Print"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "stupid-print"


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False, newline="\n") as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def read_document(path):
    with Path(path).open(encoding="utf-8") as stream:
        doc = json.load(stream)
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ValueError("This file is not a supported Stupid Print document.")
    if not isinstance(doc.get("title"), str) or doc.get("kind") not in ("project", "template"):
        raise ValueError("The document is missing its name or type.")
    try:
        doc["width"], doc["height"] = dimensions(doc)
        if doc["media"] not in ("Gap labels", "Continuous tape"):
            raise ValueError("Unsupported media type.")
        if doc["border"] not in ("None", "Rectangle", "Rounded", "Double"):
            raise ValueError("Unsupported border.")
        border_width = float(doc["border_width"])
        if not 1 <= border_width <= 8:
            raise ValueError("Invalid border weight.")
        doc["border_width"] = round(border_width)
        used = set()
        if not isinstance(doc["elements"], list):
            raise ValueError("Invalid label elements.")
        for item in doc["elements"]:
            validate_element(item, used)
        batch = {**BATCH_DEFAULTS, **doc["batch"]}
        if any(not isinstance(batch[key], str) for key in BATCH_DEFAULTS):
            raise ValueError("Invalid batch settings.")
        doc["batch"] = batch
        data = doc["data"]
        headers, rows = data["headers"], data["rows"]
        if not isinstance(data["name"], str) or not isinstance(headers, list) or not isinstance(rows, list):
            raise ValueError("Invalid imported data.")
        if any(not isinstance(header, str) for header in headers) or len(set(headers)) != len(headers):
            raise ValueError("Invalid column names.")
        if any(not isinstance(row, list) or len(row) != len(headers)
               or any(not isinstance(value, str) for value in row) for row in rows):
            raise ValueError("Invalid imported rows.")
    except (KeyError, TypeError) as exc:
        raise ValueError("The document has missing or invalid settings.") from exc
    return doc


def validate_element(item, used):
    uid = item["id"]
    if not isinstance(uid, str) or not uid or uid in used:
        raise ValueError("Invalid element identifier.")
    used.add(uid)
    for key, low, high in (("x", 0, 200), ("y", 0, 15), ("w", 0.2, 200), ("h", 0.2, 15)):
        item[key] = float(item[key])
        if not low <= item[key] <= high:
            raise ValueError("Invalid element dimensions.")
    kind = item["kind"]
    if kind in ("text", "barcode", "matrix") and not isinstance(item["value"], str):
        raise ValueError("Invalid element text.")
    if kind == "text":
        item.setdefault("rotation", "0°")
        if (not isinstance(item["font"], str) or not 3 <= float(item["size"]) <= 96
                or item["align"] not in ("Left", "Center", "Right")
                or item["valign"] not in ("Top", "Middle", "Bottom")
                or item["rotation"] not in ("0°", "90°", "180°", "270°")
                or any(not isinstance(item[key], bool) for key in ("bold", "italic", "underline", "fit"))):
            raise ValueError("Invalid text format.")
    elif kind == "barcode":
        item.setdefault("compact", False)
        if (item["symbology"] not in ("Code 128", "Code 39", "EAN-13", "UPC-A")
                or any(not isinstance(item[key], bool) for key in ("caption", "compact"))):
            raise ValueError("Invalid barcode format.")
    elif kind == "matrix":
        if item["symbology"] not in MATRIX_CODES or item["correction"] not in QR_LEVELS:
            raise ValueError("Invalid 2D code format.")
    elif kind == "image":
        if not all(isinstance(item[key], str) for key in ("image", "filename")) or not isinstance(item["dither"], bool):
            raise ValueError("Invalid image format.")
    elif kind == "graphic":
        if (not isinstance(item["asset"], str) or item["asset"] not in GRAPHICS
                or not isinstance(item["dither"], bool)):
            raise ValueError("Invalid built-in graphic.")
    elif kind != "line":
        raise ValueError("Unknown label element type.")


def dimensions(doc):
    width = float(doc["width"])
    height = float(doc["height"])
    if not 10 <= width <= 200 or not 5 <= height <= 15:
        raise ValueError("Enter a length of 10–200 mm and a width of 5–15 mm.")
    return width, height


class Library:
    def __init__(self, path=None):
        self.path = Path(path) if path else app_directory()

    def save(self, doc):
        doc_id = doc["id"]
        if not re.fullmatch(r"[0-9a-f]{32}", doc_id):
            raise ValueError("Invalid library document identifier.")
        write_json(self.path / doc["kind"] / (doc_id + EXTENSION), doc)

    def list(self):
        return sorted(
            (path for path in self.path.glob(f"*/*{EXTENSION}")
             if path.parent.name in ("project", "template")),
            key=lambda path: path.stat().st_mtime, reverse=True,
        )

    def settings(self):
        path = self.path / "settings.json"
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            return settings if isinstance(settings, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, settings):
        write_json(self.path / "settings.json", settings)


def _data(name, records):
    iterator = iter(records)
    first = next((row for row in iterator if any(value.strip() for value in row)), None)
    if not first:
        raise ValueError("The data file needs a header row.")
    headers = [value.strip() or f"Column {i}" for i, value in enumerate(first, 1)]
    if len(headers) != len(set(headers)) or any("{" in h or "}" in h for h in headers):
        raise ValueError("Column names must be unique and cannot contain braces.")
    rows = []
    for row in iterator:
        if not any(value.strip() for value in row):
            continue
        if any(row[len(headers):]):
            raise ValueError("A data row has more values than the header row.")
        rows.append((list(row) + [""] * len(headers))[:len(headers)])
    if not rows:
        raise ValueError("The data file needs at least one row below the headers.")
    return {"name": name, "headers": headers, "rows": rows}


def excel_sheets(path):
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        return book.sheetnames
    finally:
        book.close()


def _cell_text(cell):
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat(sep=" ") if hasattr(value, "hour") else value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        pattern = cell.number_format or ""
        if re.fullmatch(r"0+", pattern) and (isinstance(value, int) or value.is_integer()):
            return str(int(value)).zfill(len(pattern))
    return str(value)


def import_data(path, sheet=None):
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            tab = book[sheet] if sheet else book.active
            return _data(f"{path.name} / {tab.title}",
                         ([_cell_text(cell) for cell in row] for row in tab.iter_rows()))
        finally:
            book.close()
    if path.suffix.lower() not in (".csv", ".tsv"):
        raise ValueError("Select a CSV, TSV, XLSX or XLSM file.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with path.open(encoding=encoding, newline="") as stream:
                sample = stream.read(8192)
                stream.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
                return _data(path.name, csv.reader(stream, dialect))
        except UnicodeDecodeError:
            if encoding == "cp1252":
                raise


def _integer(values, field, label):
    try:
        return int(values[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a whole number.") from exc


class Batch:
    """Compute any row on demand, including batches larger than the visible list."""

    def __init__(self, doc, *, today=None):
        self.doc = doc
        self.data = doc["data"]
        self.settings = {**BATCH_DEFAULTS, **doc["batch"]}
        self.count = _integer(self.settings, "count", "Label count")
        row_count = len(self.data["rows"])
        if self.count == 0 and row_count:
            self.count = row_count
        if self.count < 1 or (row_count and self.count > row_count):
            raise ValueError("Use 1 or more labels, or 0 to use every imported row. "
                             "With imported data, count cannot exceed the number of rows.")
        self.tokens = {token.strip().lower() for item in doc["elements"]
                       for token in TOKEN.findall(item.get("value", ""))}
        self.today = today or date.today()
        self.date_values = self._date_values()
        if self.tokens & {"serial", "hostname"}:
            self.serial_start = _integer(self.settings, "serial_start", "Serial start")
            self.serial_step = _integer(self.settings, "serial_step", "Serial increment")
            self.serial_pad = _integer(self.settings, "serial_pad", "Serial padding")
            if not 0 <= self.serial_pad <= 32:
                raise ValueError("Serial padding must be between 0 and 32.")
        if "hostname" in self.tokens:
            self.hostname_prefix = self.settings["hostname_prefix"]
            for serial in (self.serial_start, self.serial_start + (self.count - 1) * self.serial_step):
                name = self.hostname_prefix + str(serial).zfill(self.serial_pad)
                if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", name):
                    raise ValueError("Hostnames must be 1–63 letters, digits or hyphens and start and end with a letter or digit.")
                if serial < 0:
                    raise ValueError("Hostname serials must be zero or greater.")
        if "mac" in self.tokens:
            oui = self.settings["mac_oui"].strip()
            suffix = self.settings["mac_start"].strip()
            if not re.fullmatch(r"[0-9a-fA-F]{6}|[0-9a-fA-F]{2}([:-])[0-9a-fA-F]{2}\1[0-9a-fA-F]{2}", oui):
                raise ValueError("Enter a 6-digit hexadecimal OUI, for example 02:00:00.")
            if not re.fullmatch(r"[0-9a-fA-F]{1,6}", suffix):
                raise ValueError("Enter a hexadecimal MAC suffix from 0 through FFFFFF.")
            self.mac_oui = oui.replace(":", "").replace("-", "").upper()
            self.mac_start = int(suffix, 16)
            self.mac_step = _integer(self.settings, "mac_step", "MAC increment")
            self.mac_format = self.settings["mac_format"]
            if self.mac_format not in MAC_FORMATS:
                raise ValueError("Choose colon, hyphen or dot MAC formatting.")
            if not 0 <= self.mac_start + (self.count - 1) * self.mac_step <= 0xffffff:
                raise ValueError("The last MAC suffix would fall outside the OUI.")
        self.port_fields = {token: int(match[1] or 0) for token in self.tokens
                            if (match := PORT_FIELD.fullmatch(token))}
        if self.port_fields:
            self.port_start = _integer(self.settings, "port_start", "Starting port")
            self.port_step = _integer(self.settings, "port_step", "Port increment per label")
            end = self.port_start + (self.count - 1) * self.port_step
            if min(self.port_start, end) < 1 or max(self.port_start, end) + max(self.port_fields.values()) > 9999:
                raise ValueError("Port numbers must stay between 1 and 9999 across the batch.")
        if self.tokens & {"ip", "subnet", "prefix", "cidr"}:
            try:
                self.address = ipaddress.ip_address(self.settings["ip_start"].strip())
                mask = self.settings["ip_mask"].strip().lstrip("/")
                self.network = ipaddress.ip_network(f"{self.address}/{mask}", strict=False)
            except ValueError as exc:
                raise ValueError("Enter a valid starting IP and subnet mask or CIDR prefix.") from exc
            self.ip_step = _integer(self.settings, "ip_step", "IP increment")
            last = int(self.address) + (self.count - 1) * self.ip_step
            if not int(self.network.network_address) <= last <= int(self.network.broadcast_address):
                raise ValueError(f"The last IP would fall outside {self.network}.")

    def _date_values(self):
        format_code = DATE_FORMATS.get(self.settings["date_format"])
        if not format_code:
            raise ValueError("Choose a date format in Batch setup.")
        values = {"date": self.today.strftime(format_code)}
        for token in self.tokens:
            match = DATE_OFFSET.fullmatch(token)
            if token == "expiry" or match:
                offset = _integer(self.settings, "expiry_days", "Expiry offset") if token == "expiry" else int(match[1])
                try:
                    values[token] = (self.today + timedelta(days=offset)).strftime(format_code)
                except OverflowError as exc:
                    raise ValueError("The date offset falls outside the supported calendar.") from exc
        return values

    def context(self, index):
        if not 0 <= index < self.count:
            raise IndexError("Label is outside the batch.")
        fields = (dict(zip(self.data["headers"], self.data["rows"][index]))
                  if self.data["rows"] else {})
        values = {"index": str(index + 1), **self.date_values}
        if self.tokens & {"serial", "hostname"}:
            serial = str(self.serial_start + index * self.serial_step).zfill(self.serial_pad)
            values["serial"] = serial
            if "hostname" in self.tokens:
                values["hostname"] = self.hostname_prefix + serial
        if "mac" in self.tokens:
            address = self.mac_oui + f"{self.mac_start + index * self.mac_step:06X}"
            separator, group = {"Colon": (":", 2), "Hyphen": ("-", 2), "Dot": (".", 4)}[self.mac_format]
            values["mac"] = separator.join(address[i:i + group] for i in range(0, 12, group))
        if self.port_fields:
            port = self.port_start + index * self.port_step
            values.update((token, str(port + offset)) for token, offset in self.port_fields.items())
        if self.tokens & {"ip", "subnet", "prefix", "cidr"}:
            address = self.address + index * self.ip_step
            prefix = str(self.network.prefixlen)
            values.update(ip=str(address), subnet=str(self.network.netmask),
                          prefix=prefix, cidr=f"{address}/{prefix}")
        return values, fields

    @staticmethod
    def expand(value, context):
        values, fields = context

        def replace(match):
            key = match[1].strip()
            if key.lower().startswith("field:"):
                key = key[6:].strip()
            elif key.lower() in values:
                return values[key.lower()]
            if key not in fields:
                raise ValueError(f"Unknown field {{{{{match[1]}}}}}.")
            return fields[key]

        return TOKEN.sub(replace, value)

    def summary(self, index):
        context = self.context(index)
        values = [self.expand(item["value"], context).replace("\n", " / ")
                  for item in self.doc["elements"] if item.get("value")]
        return " · ".join(filter(None, values)) or "Image / shape label"


@dataclass
class Selection:
    """Sorted, merged inclusive intervals using one-based label numbers."""

    ranges: list[tuple[int, int]]

    @property
    def count(self):
        return sum(last - first + 1 for first, last in self.ranges)

    def __contains__(self, number):
        return any(first <= number <= last for first, last in self.ranges)

    def __iter__(self):
        for first, last in self.ranges:
            yield from range(first, last + 1)

    def add(self, first, last):
        merged = []
        for start, end in sorted([*self.ranges, (first, last)]):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        self.ranges = merged

    def toggle(self, number):
        if number not in self:
            self.add(number, number)
            return
        kept = []
        for first, last in self.ranges:
            if not first <= number <= last:
                kept.append((first, last))
            else:
                if first < number:
                    kept.append((first, number - 1))
                if number < last:
                    kept.append((number + 1, last))
        self.ranges = kept

    def add_expression(self, expression, count):
        additions = []
        for part in expression.split(","):
            match = re.fullmatch(r"\s*(\d+)\s*(?:[-–]\s*(\d+)\s*)?", part)
            if not match:
                raise ValueError("Enter label numbers or ranges, for example 1, 4–8, 12.")
            first = int(match[1])
            last = int(match[2] or first)
            if not 1 <= first <= last <= count:
                raise ValueError(f"Enter an ascending range between 1 and {count}.")
            additions.append((first, last))
        for first, last in additions:
            self.add(first, last)
