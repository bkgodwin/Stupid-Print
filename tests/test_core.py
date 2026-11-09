import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from openpyxl import Workbook

from stupid_print.model import (Batch, Library, Selection, element, excel_sheets, import_data,
                                new_document, read_document)
from stupid_print.printer import D30, PRINT_COMPLETE, PrinterStatus
from stupid_print.render import HEAD_DOTS, embed_image, raster_packet, render_label


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.doc = new_document()

    def test_large_batch_is_indexed_and_zero_padded(self):
        self.doc["elements"][0]["value"] = "Asset {{serial}} / {{index}}"
        self.doc["batch"].update(count="1000000", serial_start="-4", serial_step="2", serial_pad="6")
        batch = Batch(self.doc)
        self.assertEqual(batch.summary(0), "Asset -00004 / 1")
        self.assertEqual(batch.summary(999999), "Asset 1999994 / 1000000")

    def test_ip_sequence_and_subnet_limit(self):
        self.doc["elements"][0]["value"] = "{{cidr}} {{subnet}}"
        self.doc["batch"].update(count="4", ip_start="10.11.12.1", ip_mask="255.255.255.248", ip_step="2")
        self.assertEqual(Batch(self.doc).summary(3), "10.11.12.7/29 255.255.255.248")
        self.doc["batch"]["count"] = "5"
        with self.assertRaisesRegex(ValueError, "outside"):
            Batch(self.doc)
        self.doc["batch"].update(count="2", ip_start="2001:db8::2", ip_mask="/126", ip_step="-1")
        self.assertTrue(Batch(self.doc).summary(1).startswith("2001:db8::1/126"))

    def test_csv_round_trip_and_reserved_fields(self):
        self.doc["elements"][0]["value"] = "{{field:serial}} / {{serial}} / {{Site}}"
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "input.csv"
            path.write_text('serial,Site\n0001,"North, Lab"\n0042,South\n', encoding="utf-8-sig")
            self.doc["data"] = import_data(path)
            self.doc["batch"]["count"] = "0"
            library = Library(Path(directory) / "library")
            library.save(self.doc)
            self.assertEqual(len(library.list()), 1)
            batch = Batch(read_document(library.list()[0]))
            self.assertEqual(batch.count, 2)
            self.assertEqual(batch.summary(0), "0001 / 1 / North, Lab")
            self.assertEqual(batch.summary(1), "0042 / 2 / South")

    def test_ranges_merge_without_expanding_and_invalid_input_is_atomic(self):
        selection = Selection([])
        selection.add_expression("1, 4–8, 3-5, 12", 15)
        self.assertEqual(selection.ranges, [(1, 1), (3, 8), (12, 12)])
        selection.toggle(5)
        self.assertEqual(list(selection), [1, 3, 4, 6, 7, 8, 12])
        with self.assertRaises(ValueError):
            selection.add_expression("2, 16", 15)
        self.assertNotIn(2, selection)

    def test_excel_worksheet_and_number_padding(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "fixture.xlsx"
            book = Workbook()
            book.active.title = "Notes"
            sheet = book.create_sheet("Assets")
            sheet.append(("Asset ID", "Location"))
            sheet.append((7, "Lab A"))
            sheet["A2"].number_format = "0000"
            sheet.append(("0008", "Lab B"))
            book.save(path)
            book.close()
            self.assertEqual(excel_sheets(path), ["Notes", "Assets"])
            data = import_data(path, "Assets")
        self.assertEqual(data["headers"], ["Asset ID", "Location"])
        self.assertEqual(data["rows"], [["0007", "Lab A"], ["0008", "Lab B"]])


class RenderTests(unittest.TestCase):
    def test_raster_dimensions_rotation_and_ink(self):
        image = Image.new("1", (176, HEAD_DOTS), 1)
        image.putpixel((0, HEAD_DOTS - 1), 0)
        packet = raster_packet(image)
        self.assertEqual(struct.unpack("<HH", packet[10:14]), (12, 176))
        self.assertEqual(packet[14], 0x80)
        self.assertEqual(len(packet), 14 + 12 * 176)
        self.assertEqual(sum(packet[15:]), 0)
        self.assertEqual(struct.unpack("<HH", raster_packet(image, True)[10:14]), (12, 232))

    def test_text_image_barcode_and_border_render_in_same_design(self):
        doc = new_document()
        doc.update(height=15, border="Rounded")
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "icon.png"
            Image.new("RGBA", (20, 20), "#000000").save(path)
            doc["elements"] = [
                element("text", value="Lab ✓ {{index}}", size=9, bold=True, italic=True, underline=True,
                        x=2, y=2, w=30, h=4),
                element("barcode", value="12345", x=2, y=6, w=29, h=6, compact=True),
                element("image", image=embed_image(path), x=32, y=2, w=5, h=5),
            ]
            image = render_label(doc, Batch(doc), 0)
        self.assertEqual(image.size, (320, 120))
        self.assertGreater(image.histogram()[0], 300)
        self.assertEqual(image.crop((0, 0, 320, 12)).histogram()[0], 0)
        self.assertEqual(image.crop((0, 108, 320, 120)).histogram()[0], 0)

    def test_invalid_barcode_is_rejected_before_printing(self):
        doc = new_document()
        doc["elements"] = [element("barcode", value="5901234123450", symbology="EAN-13")]
        with self.assertRaisesRegex(ValueError, "check digit"):
            render_label(doc, Batch(doc), 0)

    def test_narrow_barcode_requires_explicit_compact_mode(self):
        doc = new_document()
        item = element("barcode", value="007", w=20)
        doc["elements"] = [item]
        with self.assertRaisesRegex(ValueError, "2-dot modules"):
            render_label(doc, Batch(doc), 0)
        item["compact"] = True
        self.assertGreater(render_label(doc, Batch(doc), 0).histogram()[0], 0)


class PrinterTests(unittest.TestCase):
    def test_status_distinguishes_ready_and_paper_out(self):
        self.assertEqual(PrinterStatus(bytes.fromhex("1a06881a0500")).issue, "Paper not detected")
        ready = PrinterStatus(bytes.fromhex("1a06901a06891a0c0a1a07000009"))
        self.assertFalse(ready.issue)
        self.assertIn("Gap labels", ready.description)
        self.assertIn("Firmware 0.0.9", ready.description)

    def test_serial_packet_waits_for_fragmented_confirmation(self):
        class Wire:
            in_waiting = 1

            def __init__(self):
                self.writes = []
                self.reply = iter(PRINT_COMPLETE)

            def write(self, data):
                self.writes.append(data)
                return len(data)

            def read(self, _):
                return bytes((next(self.reply),))

        printer = D30("test")
        printer.serial = Wire()
        packet = raster_packet(Image.new("1", (176, HEAD_DOTS), 1))
        with patch("stupid_print.printer.time.sleep"):
            printer.print_label(packet)
        self.assertEqual(printer.serial.writes[0], bytes.fromhex("1f110a1f110202"))
        self.assertEqual(b"".join(printer.serial.writes[1:]), packet)


if __name__ == "__main__":
    unittest.main()
