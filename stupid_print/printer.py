"""Bluetooth Classic serial transport for the Phomemo D30 family."""

import glob
import os
import re
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports


PRINT_COMPLETE = bytes.fromhex("1a0f0c")
PRINT_ERROR = bytes.fromhex("1a0bb8")
INITIAL_QUERIES = ("1f1138", "1f11121f1113", "1f1111", "1f1119", "1f1107")


def available_ports():
    result = {port.device: port.description for port in list_ports.comports()}
    if os.name != "nt":
        for path in glob.glob("/dev/rfcomm*"):
            result.setdefault(path, "Bluetooth serial")
    return result


def suggested_port(ports):
    bluetooth = [port for port, description in ports.items()
                 if "bluetooth" in description.lower() or port.startswith("/dev/rfcomm")]
    if not bluetooth:
        return ""
    return min(bluetooth, key=lambda port: (re.sub(r"\d+$", "", port),
                                           int(re.search(r"\d+$", port)[0])
                                           if re.search(r"\d+$", port) else 0))


def _value(response, field):
    marker = bytes((0x1A, field))
    position = response.rfind(marker, 0, len(response) - 1)
    return response[position + 2] if 0 <= position < len(response) - 2 else None


@dataclass(frozen=True)
class PrinterStatus:
    response: bytes

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


class D30:
    def __init__(self, port):
        self.port = port
        self.serial = None

    def __enter__(self):
        self.serial = serial.Serial(self.port, baudrate=9600, timeout=0.15, write_timeout=3,
                                    exclusive=True if os.name != "nt" else None)
        return self

    def __exit__(self, *_):
        self.serial.close()

    def _write(self, data):
        if self.serial.write(data) != len(data):
            raise OSError("Incomplete Bluetooth serial write.")

    def _read(self, seconds, stop=()):
        end = time.monotonic() + seconds
        response = bytearray()
        while time.monotonic() < end:
            response.extend(self.serial.read(self.serial.in_waiting or 1))
            if any(marker in response for marker in stop):
                break
        return bytes(response)

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
