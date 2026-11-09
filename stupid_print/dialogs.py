"""Batch setup, print selection, and a cancellable print worker."""

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .model import Batch, Selection
from .printer import D30
from .render import raster_packet, render_label
from .widgets import BatchList, button, field


class SettingsDialog(simpledialog.Dialog):
    def buttonbox(self):
        panel = ttk.Frame(self, padding=(12, 4, 12, 10))
        panel.pack(fill="x")
        button(panel, "OK", self.ok, primary=True).pack(side="right")
        button(panel, "Cancel", self.cancel).pack(side="right", padx=(0, 6))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def body(self, parent):
        background = ttk.Style(self).lookup("TFrame", "background")
        self.configure(background=background)
        parent.configure(background=background, padx=12, pady=6)


class ChoiceDialog(SettingsDialog):
    def __init__(self, parent, title, options):
        self.options = options
        super().__init__(parent, title)

    def body(self, parent):
        super().body(parent)
        self.variable = tk.StringVar(value=self.options[0])
        return field(parent, "Worksheet", self.variable, self.options, width=35)

    def apply(self):
        self.result = self.variable.get()


class BatchSetup(SettingsDialog):
    def __init__(self, parent, doc):
        self.doc = doc
        super().__init__(parent, "Batch setup")

    def body(self, parent):
        super().body(parent)
        self.variables = {key: tk.StringVar(value=value) for key, value in self.doc["batch"].items()}
        first = field(parent, "Labels to generate (0 = all imported rows)", self.variables["count"])
        columns = ttk.Frame(parent)
        columns.pack(fill="x")
        for side, title, fields in (
            ("left", "Serial numbering", (("serial_start", "Starting value"),
                                          ("serial_step", "Increment"), ("serial_pad", "Minimum digits"))),
            ("right", "IP addressing", (("ip_start", "Starting IP address"),
                                        ("ip_mask", "Subnet mask or CIDR prefix"), ("ip_step", "Increment"))),
        ):
            group = ttk.LabelFrame(columns, text=title, padding=9)
            group.pack(side=side, fill="x", expand=True, padx=4, pady=6)
            for key, label in fields:
                field(group, label, self.variables[key])
        ttk.Label(parent, text="Insert fields into text or barcodes from the inspector.\n"
                  "{{serial}} · {{ip}} · {{subnet}} · {{cidr}} · {{index}}",
                  style="Muted.TLabel").pack(anchor="w", pady=8)
        self.error = tk.StringVar()
        ttk.Label(parent, textvariable=self.error, style="Error.TLabel", wraplength=440).pack(fill="x")
        return first

    def validate(self):
        settings = {key: value.get().strip() for key, value in self.variables.items()}
        try:
            Batch({**self.doc, "batch": settings})
        except ValueError as exc:
            self.error.set(str(exc))
            return False
        self.result = settings
        return True


class PrintDialog(tk.Toplevel):
    def __init__(self, app, batch, current):
        super().__init__(app.root)
        self.app = app
        self.batch = batch
        self.selection = Selection([(current, current)])
        self.status = tk.StringVar(value="Choose labels in the list, or add a range.")
        self.total = tk.StringVar()
        self.copies = tk.StringVar(value="1")
        self.expression = tk.StringVar()
        self.stop = None
        self.events = queue.SimpleQueue()
        self.photo = None
        self.title("Stupid Print  /  Print labels")
        self.transient(app.root)
        width, height = 700, 620
        x = app.root.winfo_rootx() + (app.root.winfo_width() - width) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - height) // 2
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        self.minsize(570, 530)
        self.configure(background=app.colors["panel"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _: self.close())
        body = ttk.Frame(self, padding=17)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Print labels", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"{batch.doc['title']} · {app.port.get()}",
                  style="Muted.TLabel").pack(anchor="w", pady=(1, 11))
        self.preview = ttk.Label(body, anchor="center", padding=(7, 8))
        self.preview.pack(fill="x")
        self.list = BatchList(body, self.show_preview, self.selection)
        self.list.on_toggle = self.update_count
        self.list.pack(fill="both", expand=True, pady=(4, 10))
        controls = ttk.Frame(body)
        controls.pack(fill="x")
        button(controls, "Select all", lambda: self.pick_all(True)).pack(side="left")
        button(controls, "Clear", lambda: self.pick_all(False)).pack(side="left", padx=(5, 10))
        self.range_entry = ttk.Entry(controls, textvariable=self.expression, width=13)
        self.range_entry.pack(side="left", padx=(0, 5))
        self.range_entry.bind("<Return>", lambda _: self.add_range())
        button(controls, "Add range", self.add_range).pack(side="left")
        ttk.Entry(controls, textvariable=self.copies, width=5).pack(side="right")
        ttk.Label(controls, text="Copies each").pack(side="right", padx=6)
        ttk.Label(body, text="Range example  1, 4–8, 12", style="Muted.TLabel").pack(anchor="w", pady=(5, 4))
        self.progress = ttk.Progressbar(body, maximum=1)
        self.progress.pack(fill="x", pady=3)
        ttk.Label(body, textvariable=self.status, wraplength=620).pack(anchor="w", pady=(5, 8))
        footer = ttk.Frame(body)
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.total, style="Section.TLabel").pack(side="left")
        self.print_button = button(footer, "Print selected", self.start, primary=True)
        self.print_button.pack(side="right")
        self.close_button = button(footer, "Close", self.close)
        self.close_button.pack(side="right", padx=7)
        self.update_count()
        self.list.set_batch(batch, current)
        self.show_preview(current)
        self.grab_set()
        self.focus_set()

    def show_preview(self, number):
        try:
            image = render_label(self.batch.doc, self.batch, number - 1)
            factor = min(360 / image.width, 90 / image.height)
            image = image.resize((max(1, round(image.width * factor)),
                                  max(1, round(image.height * factor))), Image.Resampling.NEAREST)
            self.photo = ImageTk.PhotoImage(image, master=self)
            self.preview.configure(image=self.photo, text="")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.preview.configure(image="", text=str(exc))

    def update_count(self):
        count = self.selection.count
        self.total.set(f"{count:,} selected")
        if self.stop is None:
            self.print_button.configure(state="normal" if count else "disabled")

    def pick_all(self, select):
        if self.stop is not None:
            return
        self.selection.ranges = [(1, self.batch.count)] if select else []
        self.list.show()
        self.update_count()

    def add_range(self):
        if self.stop is not None:
            return
        try:
            self.selection.add_expression(self.expression.get(), self.batch.count)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.list.show()
        self.update_count()
        self.status.set("Range added to the selection.")

    def start(self):
        try:
            copies = int(self.copies.get())
            if copies < 1:
                raise ValueError
        except ValueError:
            self.status.set("Enter a positive whole number for copies.")
            return
        if self.app.printer_busy:
            self.status.set("The printer is checking status. Try again in a moment.")
            return
        self.stop = threading.Event()
        self.app.printer_busy = True
        self.status.set("Checking selected labels…")
        self.print_button.configure(state="disabled")
        self.close_button.configure(text="Stop after current label")
        self.progress.configure(value=0)
        selection = Selection(self.selection.ranges.copy())
        thread = threading.Thread(target=self._print, args=(self.app.port.get().strip(), selection, copies),
                                  daemon=True)
        thread.start()
        self.after(100, self._poll)

    def _print(self, port, selection, copies):
        done = 0
        total = selection.count * copies
        number = 0
        try:
            # Validate before the first physical write, including every variable barcode.
            latest = 0.0
            for index, number in enumerate(selection, 1):
                if self.stop.is_set():
                    break
                render_label(self.batch.doc, self.batch, number - 1)
                now = time.monotonic()
                if now - latest > 0.2:
                    self.events.put(("status", f"Checking label {number:,} · {index:,}/{selection.count:,}"))
                    latest = now
            if self.stop.is_set():
                self.events.put(("end", "Stopped before printing."))
                return
            continuous = self.batch.doc["media"] == "Continuous tape"
            with D30(port) as printer:
                status = printer.status()
                if status.issue:
                    raise OSError(status.issue)
                for number in selection:
                    if self.stop.is_set():
                        break
                    packet = raster_packet(render_label(self.batch.doc, self.batch, number - 1), continuous)
                    for _ in range(copies):
                        if self.stop.is_set():
                            break
                        self.events.put(("status", f"Printing label {number:,} · {done + 1:,}/{total:,}"))
                        printer.print_label(packet, continuous)
                        done += 1
                        self.events.put(("progress", done / total))
            result = f"Printed {done:,} of {total:,} labels." if done == total else (
                f"Stopped after {done:,} of {total:,} labels."
            )
            self.events.put(("end", result))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            label = f"Label {number:,}: " if number else ""
            self.events.put(("end", f"{label}{exc} ({done:,} confirmed.)"))

    def _poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                self.after(100, self._poll)
                return
            if kind == "progress":
                self.progress.configure(value=value)
            elif kind == "status":
                self.status.set(value)
            else:
                self.status.set(value)
                self.app.footer.set(value)
                self.stop = None
                self.app.printer_busy = False
                self.close_button.configure(text="Close")
                self.update_count()
                return

    def close(self):
        if self.stop is not None:
            self.stop.set()
            self.status.set("Stopping after the current label…")
        else:
            self.destroy()
