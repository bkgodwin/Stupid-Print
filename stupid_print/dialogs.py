"""Batch setup, print selection, and a cancellable print worker."""

import queue
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk

from .artwork import GRAPHICS, graphic_layer
from .fonts import font_picker_sections, select_font
from .model import BATCH_DEFAULTS, DATE_FORMATS, MAC_FORMATS, Batch, Selection
from .printer import connect_printer
from .proof import write_proof
from .render import DPI, render_label
from .widgets import BatchList, button, field, tree_with_scroll


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
    def __init__(self, parent, title, options, label="Choose an option"):
        self.options = options
        self.label = label
        super().__init__(parent, title)

    def body(self, parent):
        super().body(parent)
        self.variable = tk.StringVar(value=self.options[0])
        return field(parent, self.label, self.variable, self.options, width=35)

    def apply(self):
        self.result = self.variable.get()


class GraphicPicker(SettingsDialog):
    def __init__(self, parent, initial=None):
        self.initial = initial
        super().__init__(parent, "Built-in graphics")

    def body(self, parent):
        super().body(parent)
        categories = tuple(dict.fromkeys(graphic.category for graphic in GRAPHICS.values()))
        self.category = tk.StringVar(value=GRAPHICS[self.initial].category if self.initial else categories[0])
        category = field(parent, "Category", self.category, categories)
        category.bind("<<ComboboxSelected>>", lambda _: self.populate())
        row = ttk.Frame(parent)
        row.pack(fill="both", expand=True)
        frame, self.tree = tree_with_scroll(row, ("name",), height=9, selectmode="browse")
        self.tree.configure(show="")
        self.tree.column("name", width=202)
        frame.pack(side="left", fill="both", expand=True)
        preview = ttk.Frame(row, padding=(12, 5))
        preview.pack(side="left")
        ttk.Label(preview, text="Print preview", style="Muted.TLabel").pack(pady=(0, 6))
        self.sample = ttk.Label(preview)
        self.sample.pack()
        self.graphic_note = tk.StringVar()
        ttk.Label(parent, textvariable=self.graphic_note, wraplength=340, style="Muted.TLabel").pack(anchor="w")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.draw_sample())
        self.tree.bind("<Double-Button-1>", self.ok)
        self.populate(self.initial)
        return self.tree

    def populate(self, preferred=None):
        self.tree.delete(*self.tree.get_children())
        choices = [(key, value.name) for key, value in GRAPHICS.items() if value.category == self.category.get()]
        for key, name in sorted(choices, key=lambda item: item[1].casefold()):
            self.tree.insert("", "end", iid=key, values=(name,))
        key = preferred if preferred and self.tree.exists(preferred) else self.tree.get_children()[0]
        self.tree.selection_set(key)
        self.tree.focus(key)
        self.tree.see(key)
        self.draw_sample()

    def draw_sample(self):
        selection = self.tree.selection()
        if selection:
            image = graphic_layer(selection[0], (64, 64)).resize((128, 128), Image.Resampling.NEAREST)
            self.photo = ImageTk.PhotoImage(image, master=self)
            self.sample.configure(image=self.photo)
            self.graphic_note.set("Monochrome reference artwork. Regulated chemical labels may require a red frame."
                                  if self.category.get() == "GHS reference" else "")

    def validate(self):
        return bool(self.tree.selection())

    def apply(self):
        self.result = self.tree.selection()[0]


class FontPicker(SettingsDialog):
    def __init__(self, parent, initial):
        self.chosen = initial
        self.sections = font_picker_sections()
        super().__init__(parent, "Choose a font")

    def body(self, parent):
        super().body(parent)
        self.filter = tk.StringVar()
        search = field(parent, "Search fonts", self.filter)
        self.trees = []
        for index, (title, height) in enumerate((("Recommended English fonts", 5), ("System fonts", 7))):
            if index:
                ttk.Separator(parent).pack(fill="x", pady=8)
            ttk.Label(parent, text=title, style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
            frame, tree = tree_with_scroll(parent, ("font",), height=height, selectmode="browse")
            tree.configure(show="")
            tree.column("font", width=360)
            frame.pack(fill="x")
            tree.bind("<<TreeviewSelect>>", lambda _, widget=tree: self.select_font(widget))
            tree.bind("<Double-Button-1>", self.ok)
            self.trees.append(tree)
        self.sample = ttk.Label(parent, padding=(0, 9, 0, 0))
        self.sample.pack()
        self.filter.trace_add("write", lambda *_: self.populate())
        self.populate()
        return search

    def populate(self):
        query = self.filter.get().strip().casefold()
        match = None
        first = None
        for tree, section in zip(self.trees, self.sections):
            tree.delete(*tree.get_children())
            for name in section:
                if query in name.casefold():
                    row = tree.insert("", "end", values=(name,))
                    if first is None:
                        first = (tree, row)
                    if name == self.chosen:
                        match = (tree, row)
        if match or first:
            tree, row = match or first
            tree.selection_set(row)
            tree.focus(row)
            tree.see(row)
            self.select_font(tree)
        else:
            self.sample.configure(image="", text="No usable fonts match your search.")

    def select_font(self, tree):
        selection = tree.selection()
        if not selection:
            return
        for other in self.trees:
            if other is not tree:
                other.selection_remove(other.selection())
        self.chosen = tree.set(selection[0], "font")
        font, _, _ = select_font(self.chosen, 24)
        image = Image.new("L", (360, 47), 255)
        ImageDraw.Draw(image).text((180, 23), "Asset ID 0123456789", font=font, fill=0, anchor="mm")
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.sample.configure(image=self.photo, text="")

    def validate(self):
        return any(tree.selection() for tree in self.trees)

    def apply(self):
        self.result = self.chosen


class BatchSetup(SettingsDialog):
    def __init__(self, parent, doc):
        self.doc = doc
        super().__init__(parent, "Batch setup")

    def body(self, parent):
        super().body(parent)
        values = {**BATCH_DEFAULTS, **self.doc["batch"]}
        self.variables = {key: tk.StringVar(value=value) for key, value in values.items()}
        first = field(parent, "Labels to generate (0 = all imported rows)", self.variables["count"])
        tabs = ttk.Notebook(parent)
        tabs.pack(fill="both", expand=True, pady=6)

        def tab(title):
            frame = ttk.Frame(tabs, padding=8)
            tabs.add(frame, text=title)
            return frame

        def group(parent, title, fields):
            frame = ttk.LabelFrame(parent, text=title, padding=8)
            frame.pack(side="left", fill="both", expand=True, padx=3)
            for key, label, *options in fields:
                field(frame, label, self.variables[key], *options)

        serial = tab("Serial & IP")
        group(serial, "Serial numbering", (("serial_start", "Starting value"), ("serial_step", "Increment"),
                                          ("serial_pad", "Minimum digits")))
        group(serial, "IP addressing", (("ip_start", "Starting IP address"), ("ip_mask", "Mask or CIDR prefix"),
                                       ("ip_step", "IP increment")))
        network = tab("MAC, host & ports")
        group(network, "MAC addresses", (("mac_oui", "OUI prefix"), ("mac_start", "Starting suffix (hex)"),
                                         ("mac_step", "MAC increment"), ("mac_format", "MAC format", MAC_FORMATS)))
        group(network, "Hostnames & ports", (("hostname_prefix", "Hostname prefix + serial"),
                                             ("port_start", "Starting port"), ("port_step", "Ports per label step")))
        dates = tab("Dates")
        field(dates, "Date format", self.variables["date_format"], tuple(DATE_FORMATS))
        field(dates, "Expiry offset from today (days)", self.variables["expiry_days"])
        ttk.Label(dates, text="Use {{expiry}} for the configured offset or enter an offset directly, "
                  "such as {{date+30d}} or {{date-7d}}.", wraplength=350, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Insert batch fields from an element’s Content tab.",
                  style="Muted.TLabel").pack(anchor="w", pady=6)
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


class ProofDialog(tk.Toplevel):
    def __init__(self, app, batch, path, paper):
        super().__init__(app.root)
        self.app = app
        self.stop = threading.Event()
        self.events = queue.SimpleQueue()
        self.title("Export batch PDF")
        self.transient(app.root)
        self.configure(background=app.colors["panel"])
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        self.status = tk.StringVar(value=f"Rendering {batch.count:,} labels…")
        ttk.Label(body, textvariable=self.status, wraplength=360).pack(fill="x", pady=(0, 8))
        self.progress = ttk.Progressbar(body, maximum=batch.count, length=340)
        self.progress.pack(fill="x", pady=(0, 8))
        self.cancel = button(body, "Cancel", self.request_stop)
        self.cancel.pack(anchor="e")
        self.protocol("WM_DELETE_WINDOW", self.request_stop)
        self.bind("<Escape>", lambda _: self.request_stop())
        self.grab_set()
        threading.Thread(target=self.export, args=(batch, path, paper), daemon=True).start()
        self.after(100, self.poll)

    def request_stop(self):
        self.stop.set()
        self.status.set("Cancelling export…")
        self.cancel.state(["disabled"])

    def export(self, batch, path, paper):
        try:
            def progress(count):
                if count % 25 == 0:
                    self.events.put(("progress", count))

            success = write_proof(path, batch, paper, cancelled=self.stop.is_set, progress=progress)
            self.events.put(("end", f"Exported · {path.name}" if success else "PDF export cancelled."))
        except (OSError, ValueError, TypeError) as exc:
            self.events.put(("error", str(exc)))

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "progress":
                self.progress.configure(value=value)
                continue
            self.destroy()
            if kind == "error":
                messagebox.showerror("Export batch PDF", value, parent=self.app.root)
            else:
                self.app.footer.set(value)
            return
        self.after(100, self.poll)


class PrintDialog(tk.Toplevel):
    def __init__(self, app, batch, current, port, *, ranges=None, copies=1):
        super().__init__(app.root)
        self.app = app
        self.batch = batch
        self.port = port
        self.selection = Selection(ranges if ranges is not None else [(current, current)])
        self.status = tk.StringVar(value="Review the previous batch before printing it again." if ranges is not None
                                   else "Choose labels in the list, or add a range.")
        roll = app.loaded_roll if app.checked_device == port.device else None
        if roll and not roll.matches(batch.doc):
            self.status.set(f"Last detected roll is {roll.description}. Use loaded roll in the editor to match it.")
        self.total = tk.StringVar()
        self.copies = tk.StringVar(value=str(copies))
        self.stock_note = tk.StringVar()
        self.stock = None
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
        printer = app.printer_model if app.checked_device == port.device else ""
        target = f"{printer} · {port.device}" if printer else port.display
        ttk.Label(body, text=f"{batch.doc['title']} · {target} · Print dots at {DPI} DPI",
                  style="Muted.TLabel").pack(anchor="w", pady=(1, 11))
        self.preview = ttk.Label(body, anchor="center", padding=(7, 8))
        self.preview.pack(fill="x")
        self.list = BatchList(body, self.show_preview, self.selection)
        self.list.on_toggle = self.update_count
        self.list.can_toggle = lambda: self.stop is None
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
        ttk.Label(body, textvariable=self.stock_note, wraplength=620, style="Muted.TLabel").pack(anchor="w")
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
        self.read_stock()
        self.copies.trace_add("write", lambda *_: self.update_count())
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
        if self.stock:
            remaining, threshold = self.stock
            try:
                requested = count * int(self.copies.get())
            except ValueError:
                requested = 0
            if requested > remaining:
                note = f"Stock estimate is below the job size ({remaining:,} labels left)."
            elif remaining <= threshold:
                note = f"Low stock · {remaining:,} labels left."
            else:
                note = f"Tracked stock · {remaining:,} labels left."
            self.stock_note.set(note)

    def read_stock(self):
        try:
            self.stock = self.app.jobs.stock(self.port.device, self.batch.doc)
            self.stock_note.set("")
        except (OSError, sqlite3.Error) as exc:
            self.stock_note.set(f"Could not read label stock. {exc}")

    def pick_all(self, select):
        if self.stop is not None:
            return
        self.selection.ranges = [(1, self.batch.count)] if select else []
        self.refresh_selection()
        self.update_count()

    def add_range(self):
        if self.stop is not None:
            return
        try:
            self.selection.add_expression(self.expression.get(), self.batch.count)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.refresh_selection()
        self.update_count()
        self.status.set("Range added to the selection.")

    def refresh_selection(self):
        focused = self.list.tree.selection()
        self.list.show(focus=int(focused[0]) if focused else None)

    def start(self):
        if self.stop is not None or not self.selection.count:
            return
        try:
            copies = int(self.copies.get())
            if copies < 1:
                raise ValueError
        except ValueError:
            self.status.set("Enter a positive whole number for copies.")
            return
        if self.selection.count * copies >= 2**63:
            self.status.set("The total label count is too large. Reduce the selection or copy count.")
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
        thread = threading.Thread(target=self._print, args=(self.port, selection, copies),
                                  daemon=True)
        thread.start()
        self.after(100, self._poll)

    def _print(self, port, selection, copies):
        done = 0
        total = selection.count * copies
        number = 0
        confirms_print = True
        job = None
        outcome = "Failed"
        result = "Printing stopped unexpectedly."
        try:
            job = self.app.jobs.start(self.batch, port.device, selection, copies)
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
                outcome, result = "Stopped", "Stopped before printing."
                return
            number = 0
            with connect_printer(port) as (printer, status):
                if status.issue:
                    raise OSError(status.issue)
                printer.validate_stock(self.batch.doc, status)
                confirms_print = printer.confirms_print
                for number in selection:
                    if self.stop.is_set():
                        break
                    image = render_label(self.batch.doc, self.batch, number - 1)
                    for _ in range(copies):
                        if self.stop.is_set():
                            break
                        if done == 0:
                            self.app.jobs.remember(job, self.batch, selection, copies, printer.model)
                        self.events.put(("status", f"Printing label {number:,} · {done + 1:,}/{total:,}"))
                        printer.print_image(image, self.batch.doc, status)
                        done += 1
                        self.app.jobs.record_label(job, port.device, self.batch.doc)
                        self.events.put(("progress", done / total))
            verb = "Printed" if confirms_print else "Sent"
            result = f"{verb} {done:,} of {total:,} labels."
            if done != total:
                outcome = "Stopped"
                result = "Stopped. " + result
            else:
                outcome = "Printed" if confirms_print else "Sent"
        except sqlite3.Error as exc:
            result = f"Print history could not be updated. {done:,} labels processed. {exc}"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            label = f"Label {number:,}: " if number else ""
            completed = "confirmed" if confirms_print else "sent with printer ready"
            result = f"{label}{exc} ({done:,} {completed}.)"
        finally:
            if job:
                try:
                    self.app.jobs.finish(job, outcome, result)
                except (OSError, sqlite3.Error) as exc:
                    result += f" Could not save the final job status. {exc}"
            self.events.put(("end", result))

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
                self.read_stock()
                self.update_count()
                return

    def close(self):
        if self.stop is not None:
            self.stop.set()
            self.status.set("Stopping after the current label…")
        else:
            self.destroy()
