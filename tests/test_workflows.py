"""Regression coverage for professional label workflows."""

import csv
import queue
import re
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import zxingcpp
from PIL import Image, ImageChops, ImageOps

from stupid_print.artwork import GHS_ARTWORK, graphic_layer
from stupid_print.dialogs import PrintDialog
from stupid_print.jobs import JobStore
from stupid_print.model import Batch, Selection, element, new_document, read_document, write_json
from stupid_print.printer import LabelRoll, PrinterPort
from stupid_print.proof import write_proof
from stupid_print.render import render_label
from stupid_print.templates import bundled_templates


class ProfessionalBatchTests(unittest.TestCase):
    def test_network_and_date_fields(self):
        doc = new_document()
        doc["elements"][0]["value"] = "{{hostname}} {{mac}} {{date}} {{date+2d}} {{date-1d}} {{expiry}}"
        doc["batch"].update(count="3", serial_start="8", serial_pad="3", hostname_prefix="lab-",
                            mac_oui="AA-BB-CC", mac_start="0000FE", mac_step="2",
                            date_format="DD/MM/YYYY", expiry_days="1")
        for style, address in (("Colon", "AA:BB:CC:00:01:00"), ("Hyphen", "AA-BB-CC-00-01-00"),
                               ("Dot", "AABB.CC00.0100")):
            doc["batch"]["mac_format"] = style
            batch = Batch(doc, today=date(2028, 2, 28))
            self.assertEqual(batch.summary(1), f"lab-009 {address} 28/02/2028 01/03/2028 27/02/2028 29/02/2028")
        doc["batch"]["mac_start"] = "FFFFFE"
        with self.assertRaisesRegex(ValueError, "outside the OUI"):
            Batch(doc)
        doc["batch"].update(mac_start="1", hostname_prefix="invalid ")
        with self.assertRaisesRegex(ValueError, "Hostnames must"):
            Batch(doc)

    def test_legacy_document_gets_new_defaults(self):
        doc = new_document()
        doc["elements"][0].pop("rotation")
        doc["batch"] = {key: value for key, value in doc["batch"].items()
                        if key == "count" or key.startswith(("ip_", "serial_"))}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.stupidprint"
            write_json(path, doc)
            loaded = read_document(path)
        self.assertEqual(loaded["elements"][0]["rotation"], "0°")
        self.assertEqual(loaded["batch"]["date_format"], "YYYY-MM-DD")
        self.assertEqual(Batch(loaded).summary(0), "Your label")

    def test_bundled_designs_render_and_panel_sections_cover_every_port(self):
        docs = bundled_templates()
        self.assertEqual(len(docs), 12)
        for key, doc in docs.items():
            with self.subTest(template=key):
                batch = Batch(doc)
                for index in range(batch.count):
                    self.assertIsNotNone(ImageOps.invert(render_label(doc, batch, index).convert("L")).getbbox())
                if key.startswith("panel"):
                    ports = " · ".join(batch.summary(index) for index in range(batch.count)).split(" · ")
                    self.assertEqual(ports, [str(number) for number in range(1, int(key[5:]) + 1)])


class MatrixTests(unittest.TestCase):
    def test_codes_decode_and_qr_correction_round_trips(self):
        doc = new_document()
        for name, level in [("QR Code", level) for level in "LMQH"] + [("Data Matrix", "M")]:
            with self.subTest(name=name, level=level):
                doc["elements"] = [element("matrix", symbology=name, correction=level, value="ID-{{serial}}",
                                           x=15, y=.5, w=11, h=11)]
                image = render_label(doc, Batch(doc), 0).convert("L")
                codes = zxingcpp.read_barcodes(image)
                self.assertEqual([code.text for code in codes], ["ID-1"])
                if name == "QR Code":
                    self.assertEqual(codes[0].ec_level, level)

    def test_white_quiet_zone_and_validation(self):
        doc = new_document()
        code = element("matrix", x=15, y=.5, w=11, h=11)
        line = element("line", x=15, y=.5, w=11, h=1)
        doc["elements"] = [line, code]
        image = render_label(doc, Batch(doc), 0).convert("L")
        self.assertEqual(image.crop((120, 4, 208, 12)).getextrema(), (255, 255))
        doc["elements"].reverse()
        with self.assertRaisesRegex(ValueError, "Artwork covers"):
            render_label(doc, Batch(doc), 0)
        doc["elements"] = [code]
        code["h"] = 7
        with self.assertRaisesRegex(ValueError, "2-dot modules"):
            render_label(doc, Batch(doc), 0)

    def test_text_rotation_uses_native_dimensions(self):
        doc = new_document()
        item = element("text", x=0, y=0, w=10, h=6, value="LAN-02")
        doc["elements"] = [item]
        upright = render_label(doc, Batch(doc), 0).crop((0, 0, 80, 48))
        item["rotation"] = "180°"
        rotated = render_label(doc, Batch(doc), 0).crop((0, 0, 80, 48))
        self.assertIsNone(ImageChops.difference(upright.transpose(Image.Transpose.ROTATE_180), rotated).getbbox())

    def test_official_graphics_render_monochrome(self):
        for key in GHS_ARTWORK:
            with self.subTest(graphic=key):
                colors = graphic_layer(key, (64, 64)).getcolors()
                self.assertEqual({color for _, color in colors}, {0, 255})


class JobAndProofTests(unittest.TestCase):
    def test_continuous_roll_validates_width_without_a_fixed_length(self):
        doc = bundled_templates()["panel48"]
        self.assertTrue(LabelRoll(40, 12, "Continuous tape", 0).matches(doc))
        self.assertFalse(LabelRoll(40, 14, "Continuous tape", 0).matches(doc))
        self.assertFalse(LabelRoll(162, 12, "Gap labels", 5).matches(doc))

    def test_partial_print_logs_and_decrements_only_processed_labels(self):
        doc = new_document("=Imported project")
        doc["elements"][0]["value"] = "{{date}}"
        batch = Batch(doc, today=date(2028, 2, 29))
        port = PrinterPort("COM5")
        selection = Selection([(1, 1)])
        calls = []

        def print_image(image, doc, status):
            calls.append(image.tobytes())
            if len(calls) == 2:
                raise TimeoutError("Check the output before retrying.")

        printer = SimpleNamespace(model="Phomemo D30", confirms_print=True, print_image=print_image,
                                  validate_stock=lambda *_: None)

        @contextmanager
        def connect(_):
            yield printer, SimpleNamespace(issue="")

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            store = JobStore(directory)
            store.set_stock(port.device, doc, 4, 2)
            harness = SimpleNamespace(batch=batch, stop=threading.Event(), events=queue.SimpleQueue(),
                                      app=SimpleNamespace(jobs=store))
            with patch("stupid_print.dialogs.connect_printer", connect):
                PrintDialog._print(harness, port, selection, 3)
            reopened = JobStore(directory)
            job, = reopened.recent()
            self.assertEqual((job["requested"], job["completed"], job["outcome"]), (3, 1, "Failed"))
            self.assertIn("Check the output", job["detail"])
            self.assertEqual(tuple(reopened.stock(port.device, doc)), (3, 2))
            replay_port, replay = reopened.last_batch()
            self.assertEqual((replay_port, replay["ranges"], replay["copies"]), ("COM5", [[1, 1]], 3))
            replay_batch = Batch(replay["document"], today=date.fromisoformat(replay["date"]))
            self.assertEqual(render_label(replay_batch.doc, replay_batch, 0).tobytes(), calls[0])

            doc["elements"][0]["value"] = "{{missing}}"
            harness.batch = Batch(doc)
            with patch("stupid_print.dialogs.connect_printer") as connect_mock:
                PrintDialog._print(harness, port, selection, 1)
                connect_mock.assert_not_called()
            self.assertEqual(reopened.last_batch()[1], replay)
            csv_path = directory / "history.csv"
            reopened.export_csv(csv_path)
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[1]["id"], job["id"])
            self.assertEqual(rows[1]["title"], "'=Imported project")

    def test_pdf_paginates_and_failed_or_cancelled_exports_keep_previous_file(self):
        doc = bundled_templates()["asset"]
        doc["batch"]["count"] = "60"
        batch = Batch(doc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proof.pdf"
            self.assertTrue(write_proof(path, batch, "US Letter"))
            original = path.read_bytes()
            self.assertEqual(len(re.findall(rb"/Type /Page\b", original)), 2)
            self.assertFalse(write_proof(path, batch, "US Letter", cancelled=lambda: True))
            doc["elements"][-1]["value"] = "{{unknown}}"
            with self.assertRaisesRegex(ValueError, "Label 1"):
                write_proof(path, Batch(doc), "US Letter")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])
