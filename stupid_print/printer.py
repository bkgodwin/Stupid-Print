"""Bluetooth Classic discovery and print protocols for the D30 and P21."""

import glob
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass

import serial
from PIL import Image
from serial.tools import list_ports

from .model import dimensions
from .render import DPI, HEAD_DOTS, dots, head_raster, raster_packet


PRINT_COMPLETE = bytes.fromhex("1a0f0c")
PRINT_ERROR = bytes.fromhex("1a0bb8")
INITIAL_QUERIES = ("1f1138", "1f11121f1113", "1f1111", "1f1119", "1f1107")
P21_STATUS = b"\x1b!?\r\n"
P21_ROLL = b"\x1b!o\r\n"
P21_ISSUES = {
    1: "Close the printer lid", 2: "Printer is feeding", 3: "Paper error", 4: "Paper not detected",
    0x10: "Printer is paused", 0x20: "Printer is busy", 0x24: "Paper ran out",
    0x30: "Battery is low", 0x80: "Print head is too hot", 0x90: "Printer has no power",
}


@dataclass(frozen=True)
class PrinterPort:
    device: str
    name: str = ""

    @property
    def display(self):
        return f"{self.name}  ·  {self.device}" if self.name else self.device

    @property
    def hint(self):
        if re.search(r"(?<![A-Z0-9])D30[A-Z]?(?![A-Z0-9])", self.name, re.IGNORECASE):
            return "D30"
        if re.search(r"(?<![A-Z0-9])P21(?![A-Z0-9])", self.name, re.IGNORECASE):
            return "P21"
        return ""


def _windows_bluetooth_name(address):
    import winreg

    location = rf"SYSTEM\CurrentControlSet\Enum\BTHENUM\Dev_{address}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, location) as device:
            for index in range(winreg.QueryInfoKey(device)[0]):
                with winreg.OpenKey(device, winreg.EnumKey(device, index)) as instance:
                    try:
                        return winreg.QueryValueEx(instance, "FriendlyName")[0]
                    except FileNotFoundError:
                        continue
    except OSError:
        pass
    return ""


def available_ports():
    result = {}
    for info in sorted(list_ports.comports(), key=lambda item: item.device):
        hardware = (info.hwid or "").upper()
        description = info.description or ""
        bluetooth = "BTHENUM" in hardware or "bluetooth" in description.lower()
        if not bluetooth and not info.device.startswith("/dev/rfcomm"):
            continue
        name = ""
        if os.name == "nt":
            remote = re.search(r"&([0-9A-F]{12})_[0-9A-F]+$", hardware)
            if remote:
                if remote[1] == "000000000000":
                    continue  # Windows' incoming SPP endpoint cannot reach the printer.
                name = _windows_bluetooth_name(remote[1])
        advertised = PrinterPort(info.device, description)
        result[info.device] = PrinterPort(info.device, name) if name else (
            advertised if advertised.hint else PrinterPort(info.device)
        )
    if os.name != "nt":
        for path in glob.glob("/dev/rfcomm*"):
            result.setdefault(path, PrinterPort(path))
    return result


def suggested_port(ports):
    recognized = [port for port in ports.values() if port.hint]
    if len(recognized) == 1:
        return recognized[0]
    return next(iter(ports.values())) if len(ports) == 1 else None


def _value(response, field):
    marker = bytes((0x1A, field))
    position = response.rfind(marker, 0, len(response) - 1)
    return response[position + 2] if 0 <= position < len(response) - 2 else None


@dataclass(frozen=True)
class PrinterStatus:
    response: bytes
    roll = None

    @property
    def recognized(self):
        return (_value(self.response, 0x06) in (0x88, 0x89)
                and (b"\x1a\x07" in self.response or b"\x1a\x3b" in self.response))

    @property
    def issue(self):
        if not self.response:
            return "Printer did not answer"
        if _value(self.response, 0x03) == 0xA9:
            return "Print head is too hot"
        if _value(self.response, 0x06) == 0x88:
            return "Paper not detected"
        return ""

    @property
    def description(self):
        if self.issue:
            return self.issue
        details = []
        if _value(self.response, 0x06) == 0x89:
            details.append("Paper detected")
        media = {0x0A: "Gap labels", 0x0B: "Continuous tape", 0x26: "Black mark"}.get(
            _value(self.response, 0x0C)
        )
        if media:
            details.append(media)
        version_start = self.response.find(b"\x1a\x07")
        if 0 <= version_start <= len(self.response) - 5:
            version = self.response[version_start + 2:version_start + 5]
            details.append("Firmware " + ".".join(map(str, version)))
        return " · ".join(details) or "Printer responded"


class SerialPrinter:
    baudrate = 9600

    def __init__(self, port):
        self.port = port
        self.serial = None

    def __enter__(self):
        self.serial = serial.Serial(self.port, baudrate=self.baudrate, timeout=0.15, write_timeout=3,
                                    exclusive=True if os.name != "nt" else None)
        return self

    def __exit__(self, *_):
        self.serial.close()

    def _write(self, data):
        if self.serial.write(data) != len(data):
            raise OSError("Incomplete Bluetooth serial write.")

    def _read(self, seconds, stop=(), size=None):
        end = time.monotonic() + seconds
        response = bytearray()
        while time.monotonic() < end:
            available = self.serial.in_waiting or 1
            response.extend(self.serial.read(available if size is None else min(available, size - len(response))))
            if len(response) == size or any(marker in response for marker in stop):
                break
        return bytes(response)

    def validate_stock(self, doc, status):
        roll = status.roll
        if roll and (dimensions(doc) != (roll.length, roll.width) or doc["media"] != roll.media):
            raise ValueError(f"The {self.model} reports {roll.description}. Match the design to the loaded roll.")


class D30(SerialPrinter):
    model = "Phomemo D30"
    confirms_print = True

    def identify(self):
        status = self.status()
        return status if status.recognized else None

    def status(self):
        for command in INITIAL_QUERIES:
            self._write(bytes.fromhex(command))
            time.sleep(0.06)
        return PrinterStatus(self._read(0.85))

    def print_label(self, packet, continuous=False):
        self._write(bytes.fromhex("1f110b1f110202" if continuous else "1f110a1f110202"))
        time.sleep(0.05)
        self._write(packet[:14])
        for offset in range(14, len(packet), 192):
            self._write(packet[offset:offset + 192])
            time.sleep(0.03)
        response = self._read(12, stop=(PRINT_COMPLETE, PRINT_ERROR))
        if PRINT_COMPLETE not in response:
            if PRINT_ERROR in response:
                raise OSError("The printer reported a print error. Check the lid and paper.")
            raise TimeoutError("The printer did not confirm completion. Check the output before retrying.")

    def print_image(self, image, doc, status):
        continuous = doc["media"] == "Continuous tape"
        self.print_label(raster_packet(image, continuous), continuous)


@dataclass(frozen=True)
class LabelRoll:
    length: int
    width: int
    media: str
    gap: int

    @property
    def description(self):
        return f"{self.length} × {self.width} mm · {self.media}"


@dataclass(frozen=True)
class NelkoStatus:
    description: str
    issue: str
    roll: LabelRoll | None


def _label_crc(data):
    crc = 0xffff
    for value in data:
        crc ^= value
        for _ in range(8):
            low_bit = crc & 1
            crc >>= 1
            if low_bit:
                crc ^= 0xa001
    return crc.to_bytes(2, "big")


def _valid_label_block(data):
    return len(data) == 16 and data[1] == 12 and _label_crc(data[:14]) == data[-2:]


def _label_roll(data):
    if not _valid_label_block(data) or not any(data[2:14]):
        return None
    length, width = data[11], data[13]
    if not 10 <= length <= 200 or not 5 <= width <= 15:
        return None
    version = data[3] >> 4
    media_code = data[7] & 15 if version >= 2 else data[7]
    media = {0: "Continuous tape", 1: "Gap labels", 2: "Black mark"}.get(media_code, "Unknown stock")
    gap = (data[8] if version >= 2 and 0 < data[8] <= 20 else 5) if media_code == 1 else 0
    return LabelRoll(length, width, media, gap)


def _nelko_config(data):
    start = data.find(b"CONFIG ")
    if start < 0:
        return None
    payload = data[start + len(b"CONFIG "):]
    for size in (20, 10):
        if payload[size:size + 2] == b"\r\n":
            dpi = int.from_bytes(payload[:2], "big")
            if 100 <= dpi <= 600:
                return dpi, ".".join(map(str, payload[5:8]))
    return None


def nelko_packet(image, doc, gap):
    """Encode the P21's TSPL bitmap (0 is ink, landscape rotates counterclockwise)."""
    length, width = dimensions(doc)
    raster = head_raster(image, Image.Transpose.ROTATE_90).convert("1", dither=Image.Dither.NONE)
    if raster.height != dots(length):
        raise ValueError("The bitmap does not match the label length.")
    setup = [f"SIZE {width:g} mm,{length:g} mm", f"GAP {gap:g} mm,0 mm",
             "DIRECTION 1,1", "DENSITY 15", "CLS"]
    prefix = "\r\n" + "\r\n".join(setup) + f"\r\nBITMAP 0,0,{HEAD_DOTS // 8},{raster.height},1,"
    return prefix.encode("ascii") + raster.tobytes() + b"\r\nPRINT 1\r\n"


class P21(SerialPrinter):
    model = "Nelko P21"
    baudrate = 115200
    confirms_print = False

    def _query(self, command, size=None):
        self.serial.reset_input_buffer()
        self._write(command)
        return self._read(0.85, size=size)

    def identify(self):
        time.sleep(0.4)
        config = _nelko_config(self._query(b"\r\nCONFIG?\r\n"))
        if config is None:
            return None
        dpi, firmware = config
        reply = self._query(P21_STATUS, size=1)
        roll = _label_roll(self._query(P21_ROLL, size=16))
        issue = self._issue(reply)
        if dpi != DPI:
            issue = f"This printer reports {dpi} DPI. The P21 driver expects {DPI} DPI."
        stock = roll.description if roll else "Roll size not reported"
        return NelkoStatus(f"{stock} · Firmware {firmware}", issue, roll)

    @staticmethod
    def _issue(reply):
        if not reply:
            return "Printer did not answer the status query"
        return "" if reply[0] == 0 else P21_ISSUES.get(reply[0], f"Printer status 0x{reply[0]:02X}")

    def print_image(self, image, doc, status):
        length, _ = dimensions(doc)
        gap = status.roll.gap if status.roll else (5 if doc["media"] == "Gap labels" else 0)
        self._write(nelko_packet(image, doc, gap))
        # P21 print commands do not acknowledge completion. Pace by the label
        # length and then check that the printer is ready before the next job.
        may_be_done = time.monotonic() + (length + gap) / 15
        response = self._read(max(0.5, may_be_done - time.monotonic()), size=16)
        if _valid_label_block(response) and response[0] not in (0, 2, 0x20):
            raise OSError(self._issue(response[:1]))
        time.sleep(max(0, may_be_done - time.monotonic()))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            reply = self._query(P21_STATUS, size=1)
            if reply == b"\x00":
                return
            if reply and reply[0] not in (2, 0x20):
                raise OSError(self._issue(reply))
            time.sleep(0.25)
        raise TimeoutError("The label was sent, but the P21 did not report ready. Check the output before retrying.")


@contextmanager
def connect_printer(port):
    drivers = {"D30": (D30,), "P21": (P21,)}.get(port.hint, (D30, P21))
    for driver in drivers:
        with driver(port.device) as printer:
            status = printer.identify()
            if status is not None:
                yield printer, status
                return
    raise OSError("No supported printer answered. Check the outgoing Bluetooth serial port.")
