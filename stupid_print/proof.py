"""Export a numbered PDF proof from the same rasters sent to the printer."""

import tempfile
from pathlib import Path

from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen.canvas import Canvas

from .model import dimensions
from .render import render_label


PAPER_SIZES = {"US Letter": letter, "A4": A4}
MAX_PROOF_LABELS = 5000


def write_proof(path, batch, paper, *, cancelled=lambda: False, progress=lambda count: None):
    """Write atomically and leave any existing file intact on failure or cancel."""
    if batch.count > MAX_PROOF_LABELS:
        raise ValueError(f"PDF proofs support up to {MAX_PROOF_LABELS:,} labels. Reduce the batch count and try again.")
    path = Path(path)
    page = PAPER_SIZES[paper]
    length, width = dimensions(batch.doc)
    w, h = length * mm, width * mm
    margin, column_gap, row_gap, header = 28, 10, 17, 44
    if w > page[0] - 2 * margin:
        page = landscape(page)
    columns = int((page[0] - 2 * margin + column_gap) // (w + column_gap))
    rows = int((page[1] - 2 * margin - header) // (h + row_gap))
    per_page = rows * columns
    pages = (batch.count + per_page - 1) // per_page
    title = " ".join(batch.doc["title"].split()) or "Untitled label"
    heading = simpleSplit(title, "Helvetica-Bold", 16, page[0] - 2 * margin)[0]
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".pdf", delete=False) as stream:
        temp = Path(stream.name)
    try:
        canvas = Canvas(str(temp), pagesize=page, pageCompression=1)
        canvas.setTitle(batch.doc["title"] + " - Batch proof")
        canvas.setAuthor("Stupid Print")
        artwork = None
        for index in range(batch.count):
            if cancelled():
                return False
            row, col = divmod(index % per_page, columns)
            if not row and not col:
                if index:
                    canvas.showPage()
                canvas.setFont("Helvetica-Bold", 16)
                canvas.drawString(margin, page[1] - margin - 7, heading)
                canvas.setFont("Helvetica", 9)
                canvas.drawString(margin, page[1] - margin - 23,
                                  f"Batch proof  |  {length:g} x {width:g} mm  |  {batch.count:,} labels  |  "
                                  "Print at actual size")
                canvas.drawRightString(page[0] - margin, margin - 8, f"Page {index // per_page + 1} of {pages}")
            x = margin + col * (w + column_gap)
            y = page[1] - margin - header - row * (h + row_gap) - h
            if artwork is None or batch.tokens:
                try:
                    artwork = ImageReader(render_label(batch.doc, batch, index).convert("L"))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    raise ValueError(f"Label {index + 1:,} — {exc}") from exc
            canvas.drawImage(artwork, x, y, w, h)
            canvas.setStrokeColorRGB(.72, .72, .72)
            canvas.setLineWidth(.35)
            canvas.rect(x - .5, y - .5, w + 1, h + 1)
            canvas.setFont("Helvetica", 8)
            canvas.drawString(x, y - 10, f"{index + 1:,}")
            progress(index + 1)
        canvas.save()
        if cancelled():
            return False
        temp.replace(path)
        return True
    finally:
        temp.unlink(missing_ok=True)
