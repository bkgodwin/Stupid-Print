"""Tk desktop editor for Stupid Print."""

import copy
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from uuid import uuid4

from PIL import Image, ImageTk

from .dialogs import BatchSetup, ChoiceDialog, PrintDialog
from .model import (EXTENSION, PRESETS, Batch, Library, dimensions, element, excel_sheets,
                    import_data, new_document, read_document, write_json)
from .printer import D30, available_ports, suggested_port
from .render import BARCODES, EMOJIS, embed_image, font_catalog, render_label
from .widgets import (ACCENT, ERROR, GOOD, INK, MUTED, PREVIEW, BatchList, ScrollPanel,
                      button, configure_style, field, tree_with_scroll)


class App:
    def __init__(self, root, library=None):
        self.root = root
        self.library = library or Library()
        self.settings = self.library.settings()
        self.doc = new_document()
        self.dirty = False
        self.save_timer = None
        self.render_timer = None
        self.batch = None
        self.preview_number = 1
        self.selected = self.doc["elements"][0]["id"]
        self.photo = None
        self.bounds = None
        self.drag = None
        self.printer_busy = False
        self.status_events = queue.SimpleQueue()
        self.port = tk.StringVar(value=self.settings.get("port", ""))
        self.printer_title = tk.StringVar(value="Printer status")
        self.printer_detail = tk.StringVar(value="Choose a Bluetooth serial port.")
        self.heading = tk.StringVar()
        self.subtitle = tk.StringVar()
        self.preview_note = tk.StringVar()
        self.footer = tk.StringVar(value="Ready to design")
        self.data_note = tk.StringVar()
        self.library_paths = {}
        self.library_names = {}
        configure_style(root)
        root.title("Stupid Print — Label Studio")
        root.geometry("1300x850")
        root.minsize(1060, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-s>", lambda _: self.save())
        root.bind("<Control-n>", lambda _: self.new_project())
        root.bind("<Control-p>", lambda _: self.open_print())
        self.build()
        self.update_library()
        previous = next((path for path in self.library_paths.values()
                         if path.stem == self.settings.get("last")), None)
        if previous:
            self.load_project(previous)
        else:
            self.load_editor()
        self.find_ports()
        if self.port.get():
            self.root.after(450, self.check_printer)

    def build(self):
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(19, 12))
        header.pack(fill="x")
        brand = tk.Canvas(header, width=43, height=43, highlightthickness=0, background=INK)
        brand.pack(side="left", padx=(0, 11))
        brand.create_rectangle(1, 1, 42, 42, fill="#7665fb", outline="")
        brand.create_polygon(10, 12, 26, 12, 34, 21, 26, 31, 10, 31, fill="white")
        brand.create_oval(25, 19, 29, 23, fill="#7665fb", outline="")
        brand.create_line(14, 19, 21, 19, fill="#7665fb", width=2)
        brand.create_line(14, 24, 21, 24, fill="#7665fb", width=2)
        wordmark = ttk.Frame(header, style="Header.TFrame")
        wordmark.pack(side="left")
        ttk.Label(wordmark, text="Stupid Print", style="Header.TLabel").pack(anchor="w")
        ttk.Label(wordmark, text="D E S K T O P   L A B E L   S T U D I O", style="HeaderSub.TLabel").pack(anchor="w")
        button(header, "Print batch…", self.open_print, primary=True).pack(side="right")
        button(header, "Save", self.save).pack(side="right", padx=8)
        button(header, "New label", self.new_project).pack(side="right")

        main = ttk.Frame(self.root, style="App.TFrame", padding=(13, 13, 13, 0))
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(main, padding=12, width=231)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.build_library(sidebar)
        center = ttk.Frame(main, padding=12)
        center.grid(row=0, column=1, sticky="nsew")
        self.build_stage(center)
        right = ttk.Frame(main, padding=8, width=285)
        right.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        self.build_inspector(right)
        ttk.Label(self.root, textvariable=self.footer, style="App.TLabel", padding=(15, 6)).pack(fill="x")

    def build_library(self, parent):
        ttk.Label(parent, text="Library", style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Saved projects and templates", style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        frame, self.library_tree = tree_with_scroll(parent, ("name", "kind"), height=9, selectmode="browse")
        frame.pack(fill="both", expand=True)
        self.library_tree.heading("name", text="Name")
        self.library_tree.column("name", width=145, minwidth=100)
        self.library_tree.heading("kind", text="Type")
        self.library_tree.column("kind", width=70, minwidth=60, stretch=False)
        self.library_tree.bind("<Double-Button-1>", lambda _: self.open_saved())
        self.library_tree.bind("<Return>", lambda _: self.open_saved())
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=6)
        button(actions, "Open", self.open_saved).pack(side="left")
        button(actions, "Use as copy", lambda: self.open_saved(True)).pack(side="left", padx=5)
        button(parent, "Open .stupidprint file…", self.open_file).pack(fill="x", pady=(1, 2))
        button(parent, "Save as template…", self.save_template).pack(fill="x", pady=2)
        button(parent, "Export project file…", self.export_project).pack(fill="x", pady=2)

        ttk.Separator(parent).pack(fill="x", pady=12)
        self.printer_badge = ttk.Label(parent, textvariable=self.printer_title, style="Section.TLabel")
        self.printer_badge.pack(anchor="w")
        ttk.Label(parent, textvariable=self.printer_detail, wraplength=210,
                  style="Muted.TLabel").pack(fill="x", pady=(3, 8))
        self.port_field = field(parent, "Bluetooth serial port", self.port, (), editable=True)
        self.port_field.bind("<<ComboboxSelected>>", lambda _: self.check_printer())
        self.port_field.bind("<Return>", lambda _: self.check_printer())
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        button(actions, "Check status", self.check_printer).pack(side="left")
        button(actions, "Find ports", self.find_ports).pack(side="left", padx=5)

    def build_stage(self, parent):
        ttk.Label(parent, textvariable=self.heading, style="Title.TLabel").pack(anchor="w")
        ttk.Label(parent, textvariable=self.subtitle, style="Muted.TLabel").pack(anchor="w", pady=(1, 9))
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 8))
        for name, action in (("+ Text", lambda: self.add_item("text")),
                             ("+ Barcode", lambda: self.add_item("barcode")),
                             ("+ Image", self.add_image), ("+ Rule", lambda: self.add_item("line"))):
            button(toolbar, name, action).pack(side="left", padx=(0, 4))
        button(toolbar, "Export PNG", self.export_image).pack(side="right")
        self.canvas = tk.Canvas(parent, background=PREVIEW, highlightthickness=0, height=246)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.draw_stage())
        self.canvas.bind("<ButtonPress-1>", self.canvas_press)
        self.canvas.bind("<B1-Motion>", self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_release)
        ttk.Label(parent, textvariable=self.preview_note, style="Muted.TLabel", wraplength=530).pack(
            anchor="w", pady=(5, 8))
        ttk.Separator(parent).pack(fill="x", pady=(0, 8))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 5))
        ttk.Label(row, text="Batch preview", style="Section.TLabel").pack(side="left")
        button(row, "Batch setup…", self.setup_batch).pack(side="right")
        button(row, "Import CSV / Excel…", self.import_source).pack(side="right", padx=6)
        ttk.Label(parent, textvariable=self.data_note, style="Muted.TLabel").pack(anchor="w", pady=(0, 5))
        self.batch_list = BatchList(parent, self.select_batch)
        self.batch_list.pack(fill="x")

    def build_inspector(self, parent):
        ttk.Label(parent, text="Inspector", style="Section.TLabel", padding=(5, 2, 0, 8)).pack(anchor="w")
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill="both", expand=True)
        self.item_panel = ScrollPanel(self.tabs)
        self.page_panel = ScrollPanel(self.tabs)
        self.tabs.add(self.item_panel, text="Elements")
        self.tabs.add(self.page_panel, text="Label")

    def update_library(self):
        selected = self.library_tree.selection()
        self.library_tree.delete(*self.library_tree.get_children())
        self.library_paths.clear()
        names = {}
        for path in self.library.list():
            key = path.parent.name + "/" + path.stem
            try:
                modified = path.stat().st_mtime_ns
                if self.library_names.get(path, (None, None))[0] == modified:
                    name = self.library_names[path][1]
                else:
                    name = read_document(path)["title"]
                names[path] = (modified, name)
            except (OSError, ValueError, TypeError, KeyError):
                name = "Unreadable document"
            self.library_paths[key] = path
            self.library_tree.insert("", "end", iid=key, values=(name, path.parent.name.title()))
        self.library_names = names
        key = self.doc["kind"] + "/" + self.doc["id"]
        if key in self.library_paths:
            self.library_tree.selection_set(key)
        elif selected and selected[0] in self.library_paths:
            self.library_tree.selection_set(selected[0])

    def find_ports(self):
        try:
            ports = available_ports()
        except OSError as exc:
            self.printer_detail.set(str(exc))
            return
        self.port_field.configure(values=tuple(ports))
        if not self.port.get():
            self.port.set(suggested_port(ports))
        if not self.port.get():
            self.printer_title.set("Printer offline")
            self.printer_detail.set("Pair the D30 and select its outgoing Bluetooth serial port.")

    def check_printer(self):
        if self.printer_busy:
            return
        port = self.port.get().strip()
        if not port:
            self.printer_title.set("Printer offline")
            self.printer_detail.set("Choose or enter a Bluetooth serial port.")
            return
        self.printer_busy = True
        self.printer_badge.configure(foreground=MUTED)
        self.printer_title.set("Checking printer…")
        self.printer_detail.set(port)
        self.settings["port"] = port
        self.persist_settings()

        def check():
            try:
                with D30(port) as printer:
                    status = printer.status()
                self.status_events.put((not status.issue, status.description))
            except (OSError, ValueError) as exc:
                self.status_events.put((False, str(exc)))

        threading.Thread(target=check, daemon=True).start()
        self.root.after(100, self.poll_status)

    def poll_status(self):
        try:
            ready, details = self.status_events.get_nowait()
        except queue.Empty:
            self.root.after(100, self.poll_status)
            return
        self.printer_busy = False
        self.printer_title.set("Printer ready" if ready else "Printer attention")
        self.printer_badge.configure(foreground=GOOD if ready else ERROR)
        self.printer_detail.set(details)

    def persist_settings(self):
        try:
            self.library.save_settings(self.settings)
        except OSError as exc:
            self.footer.set(f"Settings could not be saved. {exc}")

    def changed(self):
        self.dirty = True
        if self.save_timer is not None:
            self.root.after_cancel(self.save_timer)
        self.save_timer = self.root.after(650, self.autosave)
        if self.render_timer is not None:
            self.root.after_cancel(self.render_timer)
        self.render_timer = self.root.after(130, self.refresh)

    def autosave(self):
        self.save_timer = None
        self.save(silent=True)

    def save(self, silent=False):
        if self.save_timer is not None:
            self.root.after_cancel(self.save_timer)
            self.save_timer = None
        try:
            self.library.save(self.doc)
            self.dirty = False
            if self.settings.get("last") != self.doc["id"]:
                self.settings["last"] = self.doc["id"]
                self.persist_settings()
            self.update_library()
            self.footer.set(f"{'Autosaved' if silent else 'Saved'} · {self.doc['title']}")
            return True
        except (OSError, ValueError) as exc:
            self.footer.set(f"Could not save · {exc}")
            if not silent:
                messagebox.showerror("Save project", str(exc), parent=self.root)
            return False

    def load_project(self, path, as_copy=False):
        if self.dirty and not self.save():
            return
        try:
            doc = read_document(path)
            if as_copy:
                doc.update(id=uuid4().hex, kind="project", title=doc["title"] + " copy")
            else:
                doc.update(id=path.stem, kind=path.parent.name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Open project", str(exc), parent=self.root)
            return
        self.doc = doc
        self.dirty = as_copy
        self.load_editor()
        if as_copy:
            self.save()
        else:
            self.settings["last"] = self.doc["id"]
            self.persist_settings()

    def new_project(self):
        if self.dirty and not self.save():
            return
        self.doc = new_document()
        self.dirty = False
        self.load_editor()
        self.footer.set("New label · Changes autosave to your library")

    def open_saved(self, as_copy=False):
        selection = self.library_tree.selection()
        if selection:
            self.load_project(self.library_paths[selection[0]], as_copy)

    def open_file(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Stupid Print", "*" + EXTENSION)])
        if path:
            self.load_project(Path(path), as_copy=True)

    def save_template(self):
        title = simpledialog.askstring("Save template", "Template name", initialvalue=self.doc["title"],
                                       parent=self.root)
        if not title or not title.strip():
            return
        doc = {**self.doc, "kind": "template", "id": uuid4().hex, "title": title.strip()}
        try:
            self.library.save(doc)
            self.update_library()
            self.footer.set(f"Template saved · {title.strip()}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save template", str(exc), parent=self.root)

    def export_project(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=EXTENSION,
                                            filetypes=[("Stupid Print", "*" + EXTENSION)])
        if path:
            try:
                write_json(path, self.doc)
                self.footer.set(f"Exported · {Path(path).name}")
            except OSError as exc:
                messagebox.showerror("Export project", str(exc), parent=self.root)

    def export_image(self):
        try:
            batch = Batch(self.doc)
            image = render_label(self.doc, batch, self.preview_number - 1)
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            messagebox.showerror("Export preview", str(exc), parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".png",
                                            filetypes=[("PNG image", "*.png")])
        if path:
            try:
                image.save(path, dpi=(203, 203))
                self.footer.set(f"Exported · {Path(path).name}")
            except OSError as exc:
                messagebox.showerror("Export preview", str(exc), parent=self.root)

    def setup_batch(self):
        result = BatchSetup(self.root, self.doc).result
        if result is not None:
            self.doc["batch"] = result
            self.preview_number = 1
            self.changed()

    def import_source(self):
        path = filedialog.askopenfilename(parent=self.root,
                                          filetypes=[("CSV, TSV or Excel", "*.csv *.tsv *.xlsx *.xlsm")])
        if not path:
            return
        try:
            sheet = None
            if Path(path).suffix.lower() in (".xlsx", ".xlsm"):
                sheets = excel_sheets(path)
                if len(sheets) > 1:
                    sheet = ChoiceDialog(self.root, "Choose worksheet", sheets).result
                    if sheet is None:
                        return
            self.doc["data"] = import_data(path, sheet)
            self.doc["batch"]["count"] = "0"
            self.preview_number = 1
            self.rebuild_elements()
            self.rebuild_page()
            self.changed()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Import data", str(exc), parent=self.root)

    def clear_source(self):
        self.doc["data"] = {"name": "", "headers": [], "rows": []}
        if self.doc["batch"]["count"] == "0":
            self.doc["batch"]["count"] = "1"
        self.rebuild_elements()
        self.rebuild_page()
        self.changed()

    def select_batch(self, number):
        self.preview_number = number
        self.draw_stage()

    def refresh(self):
        self.render_timer = None
        self.heading.set(self.doc["title"])
        self.subtitle.set(f"{self.doc['width']:g} × {self.doc['height']:g} mm   ·   {self.doc['media']}")
        data = self.doc["data"]
        self.data_note.set(f"{data['name']} · {len(data['rows']):,} rows" if data["rows"] else
                           "Use batch setup for serial numbers, IP addresses, or repeated labels.")
        try:
            self.batch = Batch(self.doc)
            self.preview_number = min(self.preview_number, self.batch.count)
        except ValueError:
            self.batch = None
        if self.batch is None:
            self.batch_list.batch = None
            self.batch_list.show()
        else:
            self.batch_list.set_batch(self.batch, self.preview_number)
        self.draw_stage()

    def load_editor(self):
        self.preview_number = 1
        self.selected = next((item["id"] for item in self.doc["elements"]), None)
        self.rebuild_elements()
        self.rebuild_page()
        self.refresh()

    def draw_stage(self):
        canvas = self.canvas
        width, height = dimensions(self.doc)
        stage_width, stage_height = canvas.winfo_width(), canvas.winfo_height()
        if stage_width < 40 or stage_height < 40:
            return
        factor = min((stage_width - 48) / width, (stage_height - 55) / height, 44)
        if factor <= 0:
            return
        w, h = round(width * factor), round(height * factor)
        x, y = (stage_width - w) // 2, (stage_height - h) // 2
        self.bounds = (x, y, factor)
        canvas.delete("all")
        for dot_y in range(12, stage_height, 19):
            for dot_x in range(12, stage_width, 19):
                canvas.create_rectangle(dot_x, dot_y, dot_x + 1, dot_y + 1, fill="#c9d3e8", outline="")
        canvas.create_rectangle(x + 4, y + 5, x + w + 4, y + h + 5, fill="#c0cbe2", outline="")
        canvas.create_rectangle(x, y, x + w, y + h, fill="white", outline="")
        try:
            batch = self.batch or Batch(self.doc)
            image = render_label(self.doc, batch, self.preview_number - 1)
            self.photo = ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.NEAREST), master=self.root)
            canvas.create_image(x, y, image=self.photo, anchor="nw")
            self.preview_note.set(f"Label {self.preview_number:,} of {batch.count:,} · Drag to move, corner to resize")
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            self.preview_note.set(str(exc))
        if height > 12:
            outside = (height - 12) * factor / 2
            for edge in (y + outside, y + h - outside):
                canvas.create_line(x, edge, x + w, edge, fill="#a97932", dash=(3, 3))
        item = self.item()
        if item:
            left, top = x + item["x"] * factor, y + item["y"] * factor
            right, bottom = left + item["w"] * factor, top + item["h"] * factor
            canvas.create_rectangle(left, top, right, bottom, outline=ACCENT, width=1, dash=(4, 3))
            canvas.create_rectangle(right - 4, bottom - 4, right + 4, bottom + 4, fill=ACCENT, outline="white")

    def canvas_press(self, event):
        if not self.bounds:
            return
        origin_x, origin_y, scale = self.bounds
        px, py = (event.x - origin_x) / scale, (event.y - origin_y) / scale
        item = self.item()
        if item and abs(px - item["x"] - item["w"]) <= 8 / scale and abs(py - item["y"] - item["h"]) <= 8 / scale:
            self.drag = ("resize", event.x, event.y, item["w"], item["h"])
            return
        for candidate in reversed(self.doc["elements"]):
            if candidate["x"] <= px <= candidate["x"] + candidate["w"] and (
                candidate["y"] <= py <= candidate["y"] + candidate["h"]
            ):
                self.selected = candidate["id"]
                self.drag = ("move", event.x, event.y, candidate["x"], candidate["y"])
                self.rebuild_elements()
                self.tabs.select(self.item_panel)
                self.draw_stage()
                return

    def canvas_drag(self, event):
        if not self.drag or not self.bounds:
            return
        mode, x, y, a, b = self.drag
        scale = self.bounds[2]
        item = self.item()
        width, height = dimensions(self.doc)
        new_x, new_y = a + (event.x - x) / scale, b + (event.y - y) / scale
        if mode == "move":
            item["x"] = round(max(0, min(width - item["w"], new_x)), 2)
            item["y"] = round(max(0, min(height - item["h"], new_y)), 2)
        else:
            item["w"] = round(max(0.2, min(width - item["x"], new_x)), 2)
            item["h"] = round(max(0.2, min(height - item["y"], new_y)), 2)
        self.draw_stage()

    def canvas_release(self, event):
        if self.drag:
            _, x, y, _, _ = self.drag
            self.drag = None
            if (x, y) != (event.x, event.y):
                self.rebuild_elements()
                self.changed()

    def item(self):
        return next((item for item in self.doc["elements"] if item["id"] == self.selected), None)

    def add_item(self, kind, **values):
        w, h = dimensions(self.doc)
        item = element(kind, w=w - 4, h=min(h - 2, 1 if kind == "line" else 8),
                       y=min(2, (h - 1) / 2), **values)
        self.doc["elements"].append(item)
        self.selected = item["id"]
        self.tabs.select(self.item_panel)
        self.rebuild_elements()
        self.changed()

    def add_image(self, replace=False):
        path = filedialog.askopenfilename(parent=self.root,
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff")])
        if not path:
            return
        try:
            values = {"image": embed_image(path), "filename": Path(path).name}
            if replace and self.item():
                self.item().update(values)
                self.rebuild_elements()
                self.changed()
            else:
                self.add_item("image", **values)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            messagebox.showerror("Import image", str(exc), parent=self.root)

    def duplicate_item(self):
        source = self.item()
        if source:
            item = {**source, "id": uuid4().hex}
            self.doc["elements"].append(item)
            self.selected = item["id"]
            self.rebuild_elements()
            self.changed()

    def remove_item(self):
        item = self.item()
        if item:
            self.doc["elements"].remove(item)
            self.selected = next((item["id"] for item in reversed(self.doc["elements"])), None)
            self.rebuild_elements()
            self.changed()

    def rebuild_elements(self):
        parent = self.item_panel.content
        for child in parent.winfo_children():
            child.destroy()
        elements = self.doc["elements"]
        item = self.item()
        if not elements:
            ttk.Label(parent, text="Add a text, barcode, image or rule.", wraplength=235).pack(anchor="w")
            return
        layers = {f"{index}  {layer['kind'].title()}": layer["id"]
                  for index, layer in enumerate(elements, 1)}
        layer = tk.StringVar(value=next((key for key, uid in layers.items() if uid == self.selected), ""))
        control = field(parent, "Element", layer, tuple(layers))
        control.bind("<<ComboboxSelected>>", lambda _: self.select_layer(layers[layer.get()]))
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(0, 7))
        button(actions, "Duplicate", self.duplicate_item).pack(side="left")
        button(actions, "Remove", self.remove_item).pack(side="left", padx=4)
        if item is None:
            return
        if item["kind"] in ("text", "barcode"):
            self.content_controls(parent, item)
        if item["kind"] == "text":
            families = ("Default", *sorted(font_catalog(), key=str.casefold))
            self.item_field(parent, item, "font", "Font family", families)
            self.item_field(parent, item, "size", "Text size (pt)", numeric=(3, 96))
            row = ttk.Frame(parent)
            row.pack(fill="x")
            for key, label in (("bold", "Bold"), ("italic", "Italic"), ("underline", "Underline")):
                self.check_item(row, item, key, label, side="left")
            self.item_field(parent, item, "align", "Horizontal alignment", ("Left", "Center", "Right"))
            self.item_field(parent, item, "valign", "Vertical alignment", ("Top", "Middle", "Bottom"))
            self.check_item(parent, item, "fit", "Shrink to fit")
        elif item["kind"] == "barcode":
            self.item_field(parent, item, "symbology", "Barcode type", tuple(BARCODES))
            self.check_item(parent, item, "caption", "Show barcode value")
            self.check_item(parent, item, "compact", "Allow compact bars (1 dot)")
            ttk.Label(parent, text="Use wider bars for easier scanning.", style="Muted.TLabel").pack(anchor="w")
        elif item["kind"] == "image":
            ttk.Label(parent, text=item["filename"], wraplength=220).pack(anchor="w")
            button(parent, "Replace image…", lambda: self.add_image(True)).pack(anchor="w", pady=6)
            self.check_item(parent, item, "dither", "Dither image")
        ttk.Separator(parent).pack(fill="x", pady=8)
        ttk.Label(parent, text="Position and size · mm", style="Muted.TLabel").pack(anchor="w")
        width, height = dimensions(self.doc)
        for keys in ((("x", "Left", 0, width), ("y", "Top", 0, height)),
                     (("w", "Length", 0.2, width), ("h", "Height", 0.2, height))):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=(4, 0))
            for key, label, low, high in keys:
                group = ttk.Frame(row)
                group.pack(side="left", fill="x", expand=True, padx=(0, 4))
                self.item_field(group, item, key, label, numeric=(low, high), width=6)

    def select_layer(self, uid):
        self.selected = uid
        self.rebuild_elements()
        self.draw_stage()

    def content_controls(self, parent, item):
        ttk.Label(parent, text="Label text" if item["kind"] == "text" else "Barcode value",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        text = tk.Text(parent, height=3 if item["kind"] == "text" else 2, width=24,
                       wrap="word", background="#f8f9fd", foreground=INK, insertbackground=INK,
                       relief="solid", borderwidth=1, padx=5, pady=4, undo=True)
        text.pack(fill="x", pady=(0, 7))
        text.insert("1.0", item["value"])
        text.edit_modified(False)

        def update(_):
            if text.edit_modified():
                text.edit_modified(False)
                item["value"] = text.get("1.0", "end-1c")
                self.changed()

        text.bind("<<Modified>>", update)
        tokens = ["serial", "ip", "subnet", "prefix", "cidr", "index", "date"]
        tokens.extend(f"field:{name}" for name in self.doc["data"]["headers"])
        token = tk.StringVar(value="Insert a field…")
        choices = ttk.Combobox(parent, textvariable=token, state="readonly", values=tokens, width=16)
        choices.pack(fill="x", pady=(0, 6))

        def insert_token(_):
            text.insert("insert", "{{" + token.get() + "}}")
            token.set("Insert a field…")
            text.focus_set()

        choices.bind("<<ComboboxSelected>>", insert_token)
        if item["kind"] == "text":
            emoji = tk.StringVar(value="Insert an emoji…")
            picker = ttk.Combobox(parent, textvariable=emoji, state="readonly", values=EMOJIS, width=16)
            picker.pack(fill="x", pady=(0, 6))

            def insert_emoji(_):
                text.insert("insert", emoji.get())
                emoji.set("Insert an emoji…")
                text.focus_set()

            picker.bind("<<ComboboxSelected>>", insert_emoji)

    def item_field(self, parent, item, key, label, options=None, numeric=None, width=12):
        variable = tk.StringVar(value=item[key])
        control = field(parent, label, variable, options, width=width)

        def change(*_):
            value = variable.get()
            if numeric:
                try:
                    value = float(value)
                except ValueError:
                    return
                if not numeric[0] <= value <= numeric[1]:
                    return
            if value != item[key]:
                item[key] = value
                self.changed()

        variable.trace_add("write", change)
        if numeric:
            control.bind("<FocusOut>", lambda _: variable.set(str(item[key])))

    def check_item(self, parent, item, key, label, side="top"):
        variable = tk.BooleanVar(value=item[key])

        def change():
            item[key] = variable.get()
            self.changed()

        ttk.Checkbutton(parent, text=label, variable=variable, command=change).pack(side=side, anchor="w", pady=3)

    def rebuild_page(self):
        parent = self.page_panel.content
        for child in parent.winfo_children():
            child.destroy()
        title = tk.StringVar(value=self.doc["title"])
        control = field(parent, "Project name", title)

        def rename(*_):
            if title.get().strip():
                self.doc["title"] = title.get().strip()
                self.changed()

        title.trace_add("write", rename)
        control.bind("<FocusOut>", lambda _: title.set(self.doc["title"]))
        width, height = dimensions(self.doc)
        preset = tk.StringVar(value=next((name for name, pair in PRESETS.items()
                                        if pair == (width, height)), "Custom"))
        w_value, h_value = tk.StringVar(value=f"{width:g}"), tk.StringVar(value=f"{height:g}")
        control = field(parent, "Roll preset", preset, ("Custom", *PRESETS))
        width_control = field(parent, "Label length (mm)", w_value)
        height_control = field(parent, "Label width (mm)", h_value)

        def resize(*_):
            try:
                next_width, next_height = dimensions({"width": w_value.get(), "height": h_value.get()})
            except ValueError:
                return
            if (next_width, next_height) == dimensions(self.doc):
                return
            self.doc.update(width=next_width, height=next_height)
            for item in self.doc["elements"]:
                item["w"] = min(item["w"], next_width)
                item["h"] = min(item["h"], next_height)
                item["x"] = max(0, min(item["x"], next_width - item["w"]))
                item["y"] = max(0, min(item["y"], next_height - item["h"]))
            preset.set(next((name for name, pair in PRESETS.items()
                             if pair == (next_width, next_height)), "Custom"))
            self.rebuild_elements()
            self.changed()

        def select_preset(_):
            chosen = PRESETS.get(preset.get())
            if chosen:
                w_value.set(str(chosen[0]))
                h_value.set(str(chosen[1]))
                resize()

        control.bind("<<ComboboxSelected>>", select_preset)
        for control, variable, key in ((width_control, w_value, "width"), (height_control, h_value, "height")):
            control.bind("<Return>", resize)
            control.bind("<FocusOut>", lambda _, v=variable, k=key: (resize(), v.set(f"{self.doc[k]:g}")))
        self.item_field(parent, self.doc, "media", "Media type", ("Gap labels", "Continuous tape"))
        self.item_field(parent, self.doc, "border", "Border style", ("None", "Rectangle", "Rounded", "Double"))
        self.item_field(parent, self.doc, "border_width", "Border weight (dots)", numeric=(1, 8))
        ttk.Label(parent, text="The D30 prints across the center 12 mm. On wider stock, "
                  "dashed guides show the printable strip.", wraplength=236,
                  style="Muted.TLabel").pack(anchor="w", pady=5)
        if self.doc["data"]["rows"]:
            button(parent, "Clear imported data", self.clear_source).pack(anchor="w", pady=7)

    def open_print(self):
        if not self.port.get().strip():
            messagebox.showinfo("Print labels", "Select the printer’s Bluetooth serial port first.", parent=self.root)
            return
        try:
            batch = Batch(copy.deepcopy(self.doc))
        except ValueError as exc:
            messagebox.showerror("Print labels", str(exc), parent=self.root)
            return
        if self.dirty and not self.save():
            return
        self.settings["port"] = self.port.get().strip()
        self.persist_settings()
        PrintDialog(self, batch, min(self.preview_number, batch.count))

    def close(self):
        if self.printer_busy and any(isinstance(window, PrintDialog) for window in self.root.winfo_children()):
            return
        if self.dirty and not self.save():
            return
        self.root.destroy()
