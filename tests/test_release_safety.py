import base64
import io
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, UnidentifiedImageError
from openpyxl import Workbook

from stupid_print.dialogs import prepared_labels
from stupid_print.jobs import JobStore
from stupid_print.model import Batch, Library, Selection, import_data, new_document, read_document, write_json
from stupid_print.render import _read_image, embed_image, render_label


class ImportSafetyTests(unittest.TestCase):
    def test_xlsx_rejects_entities_and_checks_expanded_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.xlsx"
            book = Workbook()
            book.active.append(["Name"])
            book.active.append(["Label"])
            stream = io.BytesIO()
            book.save(stream)
            with ZipFile(stream) as original, ZipFile(path, "w", ZIP_DEFLATED) as crafted:
                for name in original.namelist():
                    contents = original.read(name)
                    if name == "xl/workbook.xml":
                        contents = (b'<!DOCTYPE workbook [<!ENTITY injected "Unsafe">]>' +
                                    contents.replace(b'name="Sheet"', b'name="&injected;"'))
                    crafted.writestr(name, contents)
            with self.assertRaisesRegex(ValueError, "unsupported content"):
                import_data(path)
            with patch("stupid_print.model.MAX_WORKBOOK_BYTES", 8):
                with self.assertRaisesRegex(ValueError, "too large after decompression"):
                    import_data(path)

    def test_image_inputs_reject_postscript_and_oversized_embeds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logo.png"
            path.write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 20 20\nshowpage\n")
            with self.assertRaises(UnidentifiedImageError):
                embed_image(path)
        buffer = io.BytesIO()
        Image.new("1", (1601, 20)).save(buffer, format="PNG")
        with self.assertRaisesRegex(ValueError, "supported size"):
            _read_image(base64.b64encode(buffer.getvalue()).decode("ascii"))

    def test_invalid_geometry_and_settings_are_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.stupidprint"
            doc = new_document()
            doc["elements"][0]["w"] = 10**900
            write_json(path, doc)
            with self.assertRaisesRegex(ValueError, "invalid settings"):
                read_document(path)
            library = Library(directory)
            library.save_settings({"port": [], "profiles": {"invalid": {"port": "COM4", "width": "bad"}}})
            self.assertEqual(library.settings(), {"profiles": {}})


class ReleasePrintTests(unittest.TestCase):
    def test_preparation_renders_static_job_once_and_preserves_variable_dots(self):
        doc = new_document()
        doc["width"] = 40.3
        doc["batch"]["count"] = "3"
        selection = Selection([(1, 3)])
        stop = threading.Event()
        with patch("stupid_print.dialogs.render_label", wraps=render_label) as render:
            with prepared_labels(Batch(doc), selection, stop, lambda _: None) as labels:
                self.assertEqual([number for number, _ in labels], [1, 2, 3])
            self.assertEqual(render.call_count, 1)
        doc["elements"][0]["value"] = "Label {{serial}}"
        batch = Batch(doc)
        with prepared_labels(batch, selection, stop, lambda _: None) as labels:
            for number, image in labels:
                self.assertEqual(image.tobytes(), render_label(doc, batch, number - 1).tobytes())

    def test_csv_escapes_whitespace_prefixed_formulas_and_protects_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            store = JobStore(path)
            store.start(Batch(new_document("  =1+1")), "COM3", Selection([(1, 1)]), 1)
            with self.assertRaisesRegex(OSError, "outside the print history database"):
                store.export_csv(store.path)
            csv_path = path / "history.csv"
            store.export_csv(csv_path)
            self.assertIn("'  =1+1", csv_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(len(store.recent()), 1)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
