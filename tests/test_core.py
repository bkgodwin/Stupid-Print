import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageFont
from openpyxl import Workbook

from stupid_print import placement
from stupid_print.artwork import graphic_layer
from stupid_print.fonts import font_picker_sections
from stupid_print.model import (Batch, Library, Selection, element, excel_sheets, import_data,
                                new_document, read_document)
from stupid_print.printer import (D30, P21, PRINT_COMPLETE, P21_ROLL, P21_STATUS, LabelRoll,
                                  PrinterPort, PrinterStatus, _label_roll, _nelko_config,
                                  available_ports, connect_printer, nelko_packet, suggested_port)
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
    def test_tag_emoji_prints_ink_without_an_installed_emoji_font(self):
        doc = new_document()
        doc["elements"][0]["value"] = "\U0001F3F7\ufe0f"
        with patch("stupid_print.render.font_catalog", side_effect=AssertionError("system emoji fallback used")):
            batch = Batch(doc)
            preview = render_label(doc, batch, 0, smooth=True)
            native = render_label(doc, batch, 0)
        self.assertGreater(sum(preview.histogram()[1:255]), 0)
        self.assertGreater(native.histogram()[0], 40)

    def test_shaded_graphic_round_trips_as_a_catalog_key(self):
        doc = new_document()
        doc["elements"] = [element("graphic", asset="package", w=8, h=8)]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            library = Library(directory)
            library.save(doc)
            doc = read_document(library.list()[0])
        self.assertEqual(doc["elements"][0]["asset"], "package")
        self.assertNotIn("image", doc["elements"][0])
        dithered = graphic_layer("package", (64, 64))
        solid = graphic_layer("package", (64, 64), dither=False)
        self.assertGreater(dithered.histogram()[0], solid.histogram()[0])
        self.assertGreater(render_label(doc, Batch(doc), 0).histogram()[0], 0)

    def test_raster_dimensions_rotation_and_ink(self):
        image = Image.new("1", (176, HEAD_DOTS), 1)
        image.putpixel((0, HEAD_DOTS - 1), 0)
        packet = raster_packet(image)
        self.assertEqual(struct.unpack("<HH", packet[10:14]), (12, 176))
        self.assertEqual(packet[14], 0x80)
        self.assertEqual(len(packet), 14 + 12 * 176)
        self.assertEqual(sum(packet[15:]), 0)
        self.assertEqual(struct.unpack("<HH", raster_packet(image, True)[10:14]), (12, 232))

    def test_smooth_preview_preserves_gray_edges_and_native_output(self):
        doc = new_document()
        doc["elements"][0].update(value="Aa 203", italic=True, size=9)
        batch = Batch(doc)
        native = render_label(doc, batch, 0)
        smooth = render_label(doc, batch, 0, smooth=True)
        self.assertEqual(native.mode, "1")
        self.assertEqual(smooth.size, (native.width * 3, native.height * 3))
        self.assertGreater(sum(smooth.histogram()[1:255]), 0)
        self.assertEqual(render_label(doc, batch, 0).tobytes(), native.tobytes())

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

    def test_upc_a_accepts_scanner_and_human_readable_forms(self):
        doc = new_document()
        code = element("barcode", value="03600029145", x=5, w=28.25, symbology="UPC-A")
        doc["elements"] = [code]
        expected = render_label(doc, Batch(doc), 0).tobytes()
        for value in ("036000291452", "0 36000 29145 2", "0-036000291452"):
            with self.subTest(value=value):
                code["value"] = value
                self.assertEqual(render_label(doc, Batch(doc), 0).tobytes(), expected)
        code["value"] = "0036000291453"
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

    def test_barcode_keeps_white_modules_and_quiet_zones_over_a_lower_layer(self):
        doc = new_document()
        code = element("barcode", x=2, y=3, w=34, h=6, value="007")
        doc["elements"] = [element("line", x=0, y=4, w=40, h=1), code]
        composite = render_label(doc, Batch(doc), 0)
        doc["elements"] = [code]
        alone = render_label(doc, Batch(doc), 0)
        scan_region = (16, 24, 288, 72)
        self.assertEqual(composite.crop(scan_region).tobytes(), alone.crop(scan_region).tobytes())
        self.assertEqual(composite.getpixel((0, 35)), 0)

    def test_barcode_refuses_artwork_over_the_scan_area_and_clipped_stock(self):
        doc = new_document()
        doc["height"] = 14
        code = element("barcode", x=2, y=3, w=34, h=6, value="007")
        mark = element("graphic", asset="rectangle", x=2, y=4, w=6, h=4)
        doc["elements"] = [code, mark]
        with self.assertRaisesRegex(ValueError, "Artwork covers"):
            render_label(doc, Batch(doc), 0)
        doc["elements"].reverse()
        self.assertGreater(render_label(doc, Batch(doc), 0).histogram()[0], 0)
        code["y"] = 0
        with self.assertRaisesRegex(ValueError, "inside the printable area"):
            render_label(doc, Batch(doc), 0)


class PlacementTests(unittest.TestCase):
    def test_single_alignment_respects_wide_stock_printable_area(self):
        doc = new_document()
        doc["height"] = 15
        item = element("text", w=10, h=3)
        placement.align([item], doc, 1, 0)
        self.assertEqual(item["y"], 1.5)
        placement.align([item], doc, 1, 1)
        self.assertEqual(item["y"], 10.5)

    def test_group_aligns_as_block_or_aligns_members(self):
        doc = new_document()
        items = [element("text", x=3, y=2, w=10), element("image", x=15, y=1, w=4)]
        placement.align(items, doc, 0, .5, to_label=True)
        self.assertEqual([item["x"] for item in items], [12, 24])
        placement.align(items, doc, 0, 1)
        self.assertEqual([item["x"] for item in items], [18, 24])

    def test_distribution_uses_equal_gaps_and_keeps_outer_edges(self):
        items = [element("text", x=1, w=4), element("text", x=6, w=3), element("text", x=17, w=5)]
        placement.distribute(items, 0)
        self.assertEqual([item["x"] for item in items], [1, 9.5, 17])
        with self.assertRaisesRegex(ValueError, "at least three"):
            placement.distribute(items[:2], 0)

    def test_snap_and_clamping_preserve_group_spacing(self):
        items = [element("text", x=2.2, y=2.4, w=5, h=2),
                 element("image", x=8.2, y=5.4, w=8, h=4)]
        placement.move(items, placement.bounds(items), 2.4, 12, (40, 12), snap=True)
        self.assertEqual([(item["x"], item["y"]) for item in items], [(5, 5), (11, 8)])


class FontTests(unittest.TestCase):
    def test_picker_places_recommended_first_and_excludes_unusable_faces(self):
        font = ImageFont.load_default(size=24)
        good = SimpleNamespace(load=lambda _: font)
        tofu = SimpleNamespace(load=lambda _: SimpleNamespace(getmask=lambda _: font.getmask("?")))
        variants = lambda face: {(False, False): face}
        catalog = {"Other valid": variants(good), "Arial": variants(good),
                   "Broken glyphs": variants(tofu), "AMGDT": variants(good)}
        with patch("stupid_print.fonts.font_catalog", return_value=catalog):
            recommended, system = font_picker_sections.__wrapped__()
        self.assertEqual(recommended, ("Default", "Arial"))
        self.assertEqual(system, ("Other valid",))


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

    def test_windows_names_outgoing_bluetooth_ports(self):
        def port(device, suffix):
            return SimpleNamespace(device=device, description="Bluetooth serial", hwid="BTHENUM\\SPP&" + suffix)

        comports = [port("COM3", "D2380A501A47_C00000000"), port("COM4", "000000000000_00000000")]
        with (patch("stupid_print.printer.os.name", "nt"),
              patch("stupid_print.printer.list_ports.comports", return_value=comports),
              patch("stupid_print.printer._windows_bluetooth_name", return_value="D30N")):
            detected = available_ports()
        self.assertEqual(list(detected), ["COM3"])
        self.assertEqual(suggested_port(detected).display, "D30N  ·  COM3")

    def test_generic_port_detects_phomemo_from_binary_reply(self):
        reply = bytes.fromhex("1a 3b 04 01 00 02 00 1a 06 89 1a 07 00 00 09")
        with (patch("stupid_print.printer.serial.Serial") as serial,
              patch("stupid_print.printer.time.sleep"),
              patch.object(D30, "_read", return_value=reply)):
            serial.return_value.write.side_effect = len
            with connect_printer(PrinterPort("/dev/rfcomm0")) as (printer, status):
                self.assertIsInstance(printer, D30)
                self.assertTrue(status.recognized)


class NelkoTests(unittest.TestCase):
    tag = bytes.fromhex("000c011203000301121215280f0eed03")
    config = b"CONFIG " + bytes.fromhex("00cb0000030402040201") + b"\r\n"

    def test_capture_config_and_roll(self):
        self.assertEqual(_nelko_config(self.config), (203, "4.2.4"))
        self.assertEqual(_nelko_config(self.config[:-2] + b"\x00" * 10 + b"\r\n"), (203, "4.2.4"))
        self.assertEqual(_label_roll(self.tag), LabelRoll(40, 14, "Gap labels", 5))
        self.assertIsNone(_label_roll(self.tag[:-1] + b"\x00"))

    def test_40_by_14_packet_uses_96_dot_head_and_black_zero(self):
        doc = new_document()
        doc["height"] = 14
        image = Image.new("1", (320, 112), 1)
        image.putpixel((319, 8), 0)  # printable corner after counterclockwise rotation
        image.putpixel((0, 0), 0)  # outside the printable strip
        packet = nelko_packet(image, doc, 5)
        prefix, ink_and_print = packet.split(b"BITMAP 0,0,12,320,1,")
        self.assertIn(b"SIZE 14 mm,40 mm\r\nGAP 5 mm,0 mm\r\n", prefix)
        self.assertEqual(ink_and_print, b"\x7f" + b"\xff" * 3839 + b"\r\nPRINT 1\r\n")

    def test_detection_uses_only_queries_and_rejects_mismatched_stock(self):
        replies = [self.config, b"\x00", self.tag]
        with (patch("stupid_print.printer.serial.Serial") as serial,
              patch("stupid_print.printer.time.sleep"),
              patch.object(P21, "_read", side_effect=replies)):
            serial.return_value.write.side_effect = len
            with connect_printer(PrinterPort("COM5", "P21_1234")) as (printer, status):
                self.assertIsInstance(printer, P21)
                self.assertEqual(status.roll.length, 40)
                self.assertFalse(status.issue)
                with self.assertRaisesRegex(ValueError, "loaded roll"):
                    printer.validate_stock(new_document(), status)
                doc = new_document()
                doc["height"] = 14
                printer.validate_stock(doc, status)
            writes = [call.args[0] for call in serial.return_value.write.call_args_list]
            self.assertEqual(writes, [b"\r\nCONFIG?\r\n", P21_STATUS, P21_ROLL])

    def test_generic_port_can_fall_back_to_nelko_without_a_name(self):
        with (patch("stupid_print.printer.serial.Serial") as serial,
              patch("stupid_print.printer.time.sleep"),
              patch.object(D30, "_read", return_value=b""),
              patch.object(P21, "_read", side_effect=[self.config, b"\x00", self.tag])):
            serial.return_value.write.side_effect = len
            with connect_printer(PrinterPort("/dev/rfcomm1")) as (printer, status):
                self.assertIsInstance(printer, P21)
                self.assertEqual(status.roll, LabelRoll(40, 14, "Gap labels", 5))
            self.assertEqual([call.kwargs["baudrate"] for call in serial.call_args_list], [9600, 115200])

    def test_nelko_job_is_sent_once_and_waits_for_ready(self):
        doc = new_document()
        doc["height"] = 14
        printer = P21("COM5")
        status = SimpleNamespace(roll=_label_roll(self.tag))
        image = render_label(doc, Batch(doc), 0)
        with (patch.object(printer, "_write") as write,
              patch.object(printer, "_read", return_value=b""),
              patch.object(printer, "_query", side_effect=[b"\x20", b"\x00"]) as query,
              patch("stupid_print.printer.time.sleep")):
            printer.print_image(image, doc, status)
        self.assertEqual(write.call_count, 1)
        self.assertTrue(write.call_args.args[0].endswith(b"\r\nPRINT 1\r\n"))
        self.assertEqual(query.call_count, 2)


if __name__ == "__main__":
    unittest.main()
