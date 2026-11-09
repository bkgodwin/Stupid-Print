"""Persistent print history, last-batch replay and manual roll counts."""

import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from .model import dimensions


JOB_FIELDS = ("id", "timestamp", "title", "port", "model", "requested", "completed", "outcome", "detail")


class JobStore:
    def __init__(self, directory):
        self.path = directory / "print-jobs.sqlite3"

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, timestamp TEXT, title TEXT, port TEXT, model TEXT DEFAULT '',
                    requested INTEGER, completed INTEGER DEFAULT 0, outcome TEXT, detail TEXT DEFAULT '',
                    snapshot TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS stock (
                    port TEXT, length REAL, width REAL, media TEXT, remaining INTEGER, threshold INTEGER,
                    PRIMARY KEY (port, length, width, media))""")
                yield db
        finally:
            db.close()

    def start(self, batch, port, selection, copies):
        job = uuid4().hex
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.connect() as db:
            db.execute("""INSERT INTO jobs (id, timestamp, title, port, requested, outcome)
                          VALUES (?, ?, ?, ?, ?, 'Unfinished')""",
                       (job, timestamp, batch.doc["title"], port, selection.count * copies))
        return job

    def remember(self, job, batch, selection, copies, model):
        snapshot = json.dumps({"document": batch.doc, "date": batch.today.isoformat(),
                               "ranges": selection.ranges, "copies": copies}, separators=(",", ":"))
        with self.connect() as db:
            db.execute("UPDATE jobs SET snapshot = NULL WHERE snapshot IS NOT NULL")
            db.execute("UPDATE jobs SET snapshot = ?, model = ? WHERE id = ?", (snapshot, model, job))

    def record_label(self, job, port, doc):
        with self.connect() as db:
            db.execute("UPDATE jobs SET completed = completed + 1 WHERE id = ?", (job,))
            db.execute("""UPDATE stock SET remaining = max(0, remaining - 1)
                          WHERE port = ? AND length = ? AND width = ? AND media = ?""",
                       self.stock_key(port, doc))

    def finish(self, job, outcome, detail):
        with self.connect() as db:
            db.execute("UPDATE jobs SET outcome = ?, detail = ? WHERE id = ?", (outcome, detail, job))

    def recent(self, limit=250):
        with self.connect() as db:
            return db.execute("""SELECT id, timestamp, title, port, model, requested, completed, outcome, detail
                                 FROM jobs ORDER BY rowid DESC LIMIT ?""", (limit,)).fetchall()

    def last_batch(self):
        with self.connect() as db:
            row = db.execute("SELECT port, snapshot FROM jobs WHERE snapshot IS NOT NULL LIMIT 1").fetchone()
        return (row["port"], json.loads(row["snapshot"])) if row else None

    def has_reprint(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM jobs WHERE snapshot IS NOT NULL LIMIT 1").fetchone() is not None

    def export_csv(self, path):
        with self.connect() as db, open(path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(JOB_FIELDS)
            for row in db.execute(f"SELECT {', '.join(JOB_FIELDS)} FROM jobs ORDER BY rowid DESC"):
                # Prevent spreadsheet apps from treating user-supplied strings as formulas.
                writer.writerow("'" + value if isinstance(value, str) and value.startswith(
                    ("=", "+", "-", "@", "\t", "\r", "\n")) else value for value in row)

    @staticmethod
    def stock_key(port, doc):
        return port, *dimensions(doc), doc["media"]

    def stock(self, port, doc):
        with self.connect() as db:
            return db.execute("""SELECT remaining, threshold FROM stock
                                 WHERE port = ? AND length = ? AND width = ? AND media = ?""",
                              self.stock_key(port, doc)).fetchone()

    def set_stock(self, port, doc, remaining, threshold):
        with self.connect() as db:
            key = self.stock_key(port, doc)
            if remaining is None:
                db.execute("DELETE FROM stock WHERE port = ? AND length = ? AND width = ? AND media = ?", key)
            else:
                db.execute("""INSERT INTO stock VALUES (?, ?, ?, ?, ?, ?)
                              ON CONFLICT (port, length, width, media)
                              DO UPDATE SET remaining = excluded.remaining, threshold = excluded.threshold""",
                           (*key, remaining, threshold))
