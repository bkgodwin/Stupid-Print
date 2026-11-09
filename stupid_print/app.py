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
from . import placement
from .printer import D30, available_ports, suggested_port
from .render import BARCODES, DPI, EMOJIS, embed_image, font_catalog, render_label
from .widgets import BatchList, button, configure_style, field, tree_with_scroll


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
        self.selected = []
        self.photo = None
        self.bounds = None
        self.drag = None
        self.editor_text = None
        self.printer_busy = False
        self.printer_tone = "muted"
        self.status_events = queue.SimpleQueue()
        self.port = tk.StringVar(value=self.settings.get("port", ""))
        self.printer_title = tk.StringVar(value="Printer status")
        self.printer_detail = tk.StringVar(value="Choose a Bluetooth serial port.")
        self.heading = tk.StringVar()
        self.subtitle = tk.StringVar()
        self.preview_note = tk.StringVar()
        self.footer = tk.StringVar(value="Ready to design")
        self.data_note = tk.StringVar()
        self.theme_label = tk.StringVar()
        self.batch_visible = tk.BooleanVar(value=True)
        self.grid_visible = tk.BooleanVar(value=bool(self.settings.get("grid", False)))
        self.snap_grid = tk.BooleanVar(value=bool(self.settings.get("snap", False)))
        self.align_reference = tk.StringVar(value="Selection")
        self.library_paths = {}
        self.library_names = {}
        self.dark = self.settings.get("theme") != "light"
        self.colors = configure_style(root, self.dark)
        root.title("Stupid Print — Label Studio")
        root.geometry("1300x850")
        root.minsize(1060, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-s>", lambda _: self.save())
        root.bind("<Control-n>", lambda _: self.new_project())
        root.bind("<Control-p>", lambda _: self.open_print())
        self.build()
        self.apply_theme()
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
        brand = self.brand = tk.Canvas(header, width=43, height=43, highlightthickness=0)
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
        ttk.Button(header, textvariable=self.theme_label, command=self.toggle_theme).pack(side="right", padx=8)

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
        project = ttk.Menubutton(parent, text="Project files")
        self.project_menu = tk.Menu(project, tearoff=False)
        for label, command in (("Open .stupidprint file…", self.open_file),
                               ("Save as template…", self.save_template),
                               ("Export project file…", self.export_project),
                               ("Export current label PNG…", self.export_image)):
            self.project_menu.add_command(label=label, command=command)
        project.configure(menu=self.project_menu)
        project.pack(fill="x", pady=(0, 3))

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
        self.canvas = tk.Canvas(parent, highlightthickness=0, height=188, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.draw_stage())
        self.canvas.bind("<ButtonPress-1>", self.canvas_press)
        self.canvas.bind("<B1-Motion>", self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_release)
        self.canvas.bind("<KeyPress>", self.canvas_key)
        self.canvas.bind("<Control-a>", lambda _: self.select_all())
        self.canvas.bind("<Control-d>", lambda _: self.duplicate_item() or "break")
        ttk.Label(parent, textvariable=self.preview_note, style="Muted.TLabel", wraplength=530).pack(
            anchor="w", pady=(5, 8))
        ttk.Separator(parent).pack(fill="x", pady=(0, 8))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 5))
        ttk.Label(row, text="Batch preview", style="Section.TLabel").pack(side="left")
        button(row, "Batch setup…", self.setup_batch).pack(side="right")
        button(row, "Import data…", self.import_source).pack(side="right", padx=6)
        self.batch_toggle = button(row, "Hide", self.toggle_batch, width=5)
        self.batch_toggle.pack(side="left", padx=8)
        self.batch_body = ttk.Frame(parent)
        self.batch_body.pack(fill="x")
        ttk.Label(self.batch_body, textvariable=self.data_note, wraplength=435, style="Muted.TLabel").pack(
            anchor="w", pady=(0, 5))
        self.batch_list = BatchList(self.batch_body, self.select_batch)
        self.batch_list.pack(fill="x")

    def build_inspector(self, parent):
        ttk.Label(parent, text="Layers", style="Section.TLabel", padding=(5, 2, 0, 7)).pack(anchor="w")
        frame, self.layer_tree = tree_with_scroll(parent, ("layer",), height=4, selectmode="extended")
        self.layer_tree.configure(show="")
        self.layer_tree.column("layer", width=270)
        self.layer_tree.bind("<<TreeviewSelect>>", self.select_from_tree)
        self.layer_tree.bind("<Delete>", lambda _: self.remove_item() or "break")
        frame.pack(fill="x")
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(6, 8))
        for label, action, width in (("Duplicate", self.duplicate_item, 8), ("Remove", self.remove_item, 7),
                                     ("Raise", lambda: self.reorder(1), 5),
                                     ("Lower", lambda: self.reorder(-1), 5)):
            button(actions, label, action, width=width).pack(side="left", padx=(0, 4))
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill="both", expand=True)
        self.item_panel = ttk.Frame(self.tabs, padding=9)
        self.style_panel = ttk.Frame(self.tabs, padding=9)
        self.place_panel = ttk.Frame(self.tabs, padding=9)
        self.page_panel = ttk.Frame(self.tabs, padding=9)
        for panel, title in ((self.item_panel, "Content"), (self.style_panel, "Style"),
                             (self.place_panel, "Place"), (self.page_panel, "Label")):
            self.tabs.add(panel, text=title)

    def toggle_theme(self):
        self.dark = not self.dark
        self.settings["theme"] = "dark" if self.dark else "light"
        self.persist_settings()
        self.apply_theme()

    def apply_theme(self):
        self.colors = c = configure_style(self.root, self.dark)
        self.theme_label.set("Light mode" if self.dark else "Dark mode")
        self.brand.configure(background=c["header"])
        self.canvas.configure(background=c["stage"])
        self.project_menu.configure(background=c["panel"], foreground=c["ink"],
                                    activebackground=c["selected"], activeforeground=c["ink"])
        self.printer_badge.configure(foreground=c[self.printer_tone])
        if self.editor_text is not None:
            self.style_text(self.editor_text)
        self.draw_stage()

    def style_text(self, text):
        c = self.colors
        text.configure(background=c["field"], foreground=c["ink"], insertbackground=c["ink"],
                       selectbackground=c["selected"], selectforeground=c["ink"],
                       highlightbackground=c["line"], highlightcolor=c["selection_outline"])

    def toggle_batch(self):
        visible = not self.batch_visible.get()
        self.batch_visible.set(visible)
        if visible:
            self.batch_body.pack(fill="x")
        else:
            self.batch_body.pack_forget()
        self.batch_toggle.configure(text="Hide" if visible else "Show")

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
        self.printer_tone = "muted"
        self.printer_badge.configure(foreground=self.colors[self.printer_tone])
        self.printer_title.set("Checking printer…")
        self.printer_detail.set(port)
        self.settings["port"] = port
        self.persist_settings()

        def check():
            try:
                with D30(port) as printer:
                    status = printer.status()
                self.status_events.put((not status.issue, status.description))
            except (OSError, ValueError):
                self.status_events.put((False, f"Could not reach {port}. Check printer power, "
                                               "Bluetooth pairing, and serial-port access."))

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
        self.printer_tone = "good" if ready else "error"
        self.printer_badge.configure(foreground=self.colors[self.printer_tone])
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
                image.save(path, dpi=(DPI, DPI))
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
        self.selected = [item["id"] for item in self.doc["elements"][:1]]
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
        canvas.create_rectangle(x + 5, y + 6, x + w + 5, y + h + 6, fill=self.colors["shadow"], outline="")
        canvas.create_rectangle(x, y, x + w, y + h, fill="white", outline="")
        try:
            batch = self.batch or Batch(self.doc)
            image = render_label(self.doc, batch, self.preview_number - 1)
            self.photo = ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.NEAREST), master=self.root)
            canvas.create_image(x, y, image=self.photo, anchor="nw")
            self.preview_note.set(f"Label {self.preview_number:,} of {batch.count:,}  ·  {DPI} dpi  ·  "
                                  "Shift-click to select more")
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            self.preview_note.set(str(exc))
        if self.grid_visible.get():
            for column in range(1, int(width)):
                px = x + column * factor
                canvas.create_line(px, y, px, y + h, fill="#c6cfe3", stipple="gray25")
            for row in range(1, int(height)):
                py = y + row * factor
                canvas.create_line(x, py, x + w, py, fill="#c6cfe3", stipple="gray25")
        _, top, _, bottom = placement.printable_area(self.doc)
        if top:
            for edge in (y + top * factor, y + bottom * factor):
                canvas.create_line(x, edge, x + w, edge, fill=self.colors["guide"], dash=(4, 3))
        items = self.items()
        outline = self.colors["selection_outline"]
        for item in items:
            left, top = x + item["x"] * factor, y + item["y"] * factor
            right, bottom = left + item["w"] * factor, top + item["h"] * factor
            canvas.create_rectangle(left, top, right, bottom, outline=outline, width=2, dash=(4, 3))
            if len(items) == 1:
                canvas.create_rectangle(right - 4, bottom - 4, right + 4, bottom + 4,
                                        fill=outline, outline="white")

    def canvas_press(self, event):
        if not self.bounds:
            return
        self.canvas.focus_set()
        origin_x, origin_y, scale = self.bounds
        px, py = (event.x - origin_x) / scale, (event.y - origin_y) / scale
        item = self.item()
        extended = bool(event.state & (0x0001 | 0x0004))
        if item and not extended and abs(px - item["x"] - item["w"]) <= 8 / scale and (
            abs(py - item["y"] - item["h"]) <= 8 / scale
        ):
            self.drag = ("resize", event.x, event.y, [(item, "w", item["w"], "h", item["h"])])
            return
        for candidate in reversed(self.doc["elements"]):
            if candidate["x"] <= px <= candidate["x"] + candidate["w"] and (
                candidate["y"] <= py <= candidate["y"] + candidate["h"]
            ):
                uid = candidate["id"]
                if extended:
                    self.select([key for key in self.selected if key != uid] if uid in self.selected else
                                [*self.selected, uid])
                elif uid not in self.selected:
                    self.select([uid])
                if uid in self.selected:
                    self.drag = ("move", event.x, event.y, [(layer, "x", layer["x"], "y", layer["y"])
                                                           for layer in self.items()])
                return
        if not extended:
            self.select([])

    def canvas_drag(self, event):
        if not self.drag or not self.bounds:
            return
        mode, x, y, originals = self.drag
        scale = self.bounds[2]
        page = dimensions(self.doc)
        dx, dy = (event.x - x) / scale, (event.y - y) / scale
        for item, first, a, second, b in originals:
            item[first], item[second] = a, b
        if mode == "move":
            items = [record[0] for record in originals]
            placement.move(items, placement.bounds(items), dx, dy, page, self.snap_grid.get())
        else:
            w, h = item["w"] + dx, item["h"] + dy
            if self.snap_grid.get():
                w, h = round(item["x"] + w) - item["x"], round(item["y"] + h) - item["y"]
            item["w"] = round(max(0.2, min(page[0] - item["x"], w)), 3)
            item["h"] = round(max(0.2, min(page[1] - item["y"], h)), 3)
        self.draw_stage()

    def canvas_release(self, _):
        if self.drag:
            originals = self.drag[3]
            self.drag = None
            if any(item[first] != a or item[second] != b for item, first, a, second, b in originals):
                self.placement_changed()

    def canvas_key(self, event):
        directions = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
        if event.keysym == "Delete":
            self.remove_item()
            return "break"
        items = self.items()
        if event.keysym in directions and items:
            step = 1 if event.state & 0x0001 else placement.DOT
            dx, dy = directions[event.keysym]
            placement.move(items, placement.bounds(items), dx * step, dy * step, dimensions(self.doc))
            self.placement_changed()
            return "break"

    def items(self):
        selected = set(self.selected)
        return [item for item in self.doc["elements"] if item["id"] in selected]

    def item(self):
        items = self.items()
        return items[0] if len(items) == 1 else None

    def select(self, ids, sync_layers=True):
        if set(ids) != set(self.selected):
            self.selected = ids
            self.rebuild_elements(sync_layers=sync_layers)
            self.draw_stage()

    def select_all(self):
        self.select([item["id"] for item in self.doc["elements"]])
        return "break"

    def select_from_tree(self, _):
        self.select(list(self.layer_tree.selection()), sync_layers=False)

    def add_item(self, kind, **values):
        w, _ = dimensions(self.doc)
        _, top, _, bottom = placement.printable_area(self.doc)
        height = min(bottom - top - 1, {"text": 4, "line": .25}.get(kind, 8))
        width = min(w - 2, 10) if kind == "image" else w - 2
        previous = self.item()
        below = previous["y"] + previous["h"] + .5 if previous else top + 1
        y = below if below + height <= bottom else top + .5
        item = element(kind, x=1, y=y, w=width, h=height, **values)
        self.doc["elements"].append(item)
        self.selected = [item["id"]]
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
        copies = [{**source, "id": uuid4().hex} for source in self.items()]
        if copies:
            placement.move(copies, placement.bounds(copies), 1, 1, dimensions(self.doc))
            self.doc["elements"].extend(copies)
            self.selected = [item["id"] for item in copies]
            self.rebuild_elements()
            self.changed()

    def remove_item(self):
        if self.selected:
            selected = set(self.selected)
            self.doc["elements"] = [item for item in self.doc["elements"] if item["id"] not in selected]
            self.selected = []
            self.rebuild_elements()
            self.changed()

    def reorder(self, direction):
        elements = self.doc["elements"]
        selected = set(self.selected)
        indices = range(len(elements) - 2, -1, -1) if direction == 1 else range(1, len(elements))
        changed = False
        for index in indices:
            target = index + direction
            if elements[index]["id"] in selected and elements[target]["id"] not in selected:
                elements[index], elements[target] = elements[target], elements[index]
                changed = True
        if changed:
            self.rebuild_elements()
            self.changed()

    @staticmethod
    def layer_title(item):
        name = item.get("value") or item.get("filename") or ""
        summary = " ".join(name.split())
        if len(summary) > 30:
            summary = summary[:29] + "…"
        return f"{item['kind'].title()}   {summary}".strip()

    def rebuild_elements(self, sync_layers=True):
        if sync_layers:
            self.layer_tree.delete(*self.layer_tree.get_children())
            for layer in reversed(self.doc["elements"]):
                self.layer_tree.insert("", "end", iid=layer["id"], values=(self.layer_title(layer),))
            self.layer_tree.selection_set(self.selected)
            if self.selected:
                self.layer_tree.see(self.selected[-1])
        self.editor_text = None
        for parent in (self.item_panel, self.style_panel):
            for child in parent.winfo_children():
                child.destroy()
        self.rebuild_placement()
        parent = self.item_panel
        item = self.item()
        if item is None:
            hint = ("Use Place to align or space the selection." if self.selected else
                    "Select an element on the label, or add one from the toolbar.")
            for panel in (parent, self.style_panel):
                ttk.Label(panel, text=hint, wraplength=245, style="Muted.TLabel").pack(anchor="w")
            return
        if item["kind"] in ("text", "barcode"):
            self.content_controls(parent, item)
        elif item["kind"] == "image":
            ttk.Label(parent, text=item["filename"], wraplength=235).pack(anchor="w")
            button(parent, "Replace image…", lambda: self.add_image(True)).pack(anchor="w", pady=6)
        else:
            ttk.Label(parent, text="Use Place to position and size this rule.",
                      wraplength=245, style="Muted.TLabel").pack(anchor="w")
        parent = self.style_panel
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
            self.check_item(parent, item, "dither", "Dither image")
            ttk.Label(parent, text="Dither photos for tonal detail. Turn it off for solid logos.",
                      wraplength=235, style="Muted.TLabel").pack(anchor="w", pady=5)

    def rebuild_placement(self):
        parent = self.place_panel
        for child in parent.winfo_children():
            child.destroy()
        options = ttk.Frame(parent)
        options.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(options, text="1 mm grid", variable=self.grid_visible,
                        command=self.placement_settings).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(options, text="Snap", variable=self.snap_grid,
                        command=self.placement_settings).pack(side="left")
        count = len(self.selected)
        item = self.item()
        self.geometry_fields = {}
        if item:
            for group in ((("x", "Left · mm"), ("y", "Top · mm")),
                          (("w", "Length · mm"), ("h", "Height · mm"))):
                row = ttk.Frame(parent)
                row.pack(fill="x")
                for key, title in group:
                    column = ttk.Frame(row)
                    column.pack(side="left", fill="x", expand=True, padx=(0, 5))
                    variable = self.geometry_fields[key] = tk.StringVar(value=f"{item[key]:g}")
                    control = field(column, title, variable, width=7)
                    control.bind("<Return>", lambda _, k=key: self.commit_geometry(item, k))
                    control.bind("<FocusOut>", lambda _, k=key: self.commit_geometry(item, k))
        if not count:
            ttk.Label(parent, text="Select elements to place or align.", style="Muted.TLabel").pack(anchor="w")
            return
        ttk.Separator(parent).pack(fill="x", pady=(4, 8))
        if count > 1:
            field(parent, "Align to", self.align_reference, ("Selection", "Printable area"))
        else:
            ttk.Label(parent, text="Align to printable area", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        for axis, labels in enumerate((("Left", "Center", "Right"), ("Top", "Middle", "Bottom"))):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=(0, 4))
            for anchor, name in zip((0, .5, 1), labels):
                button(row, name, lambda a=axis, p=anchor: self.align_selection(a, p),
                       width=7).pack(side="left", fill="x", expand=True, padx=(0, 4))
        if count > 1:
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=(4, 0))
            for axis, name in enumerate(("Space across", "Space down")):
                control = button(row, name, lambda a=axis: self.distribute_selection(a))
                control.pack(side="left", fill="x", expand=True, padx=(0, 4))
                if count < 3:
                    control.state(["disabled"])
        ttk.Label(parent, text="On the canvas, arrows move one dot. Shift + arrow moves 1 mm.",
                  wraplength=245, style="Muted.TLabel").pack(anchor="w", pady=(9, 0))

    def commit_geometry(self, item, key):
        if self.item() is not item or key not in self.geometry_fields:
            return
        previous = tuple(item[k] for k in self.geometry_fields)
        try:
            value = float(self.geometry_fields[key].get())
        except ValueError:
            value = item[key]
        if (0 if key in ("x", "y") else .2) <= value <= 200:
            item[key] = round(value, 3)
            placement.fit_box(item, dimensions(self.doc))
        if previous != tuple(item[k] for k in self.geometry_fields):
            self.placement_changed()
        else:
            self.update_geometry_fields()

    def update_geometry_fields(self):
        item = self.item()
        if item:
            for key, variable in self.geometry_fields.items():
                variable.set(f"{item[key]:g}")

    def placement_changed(self):
        self.update_geometry_fields()
        self.changed()
        self.draw_stage()

    def align_selection(self, axis, anchor):
        items = self.items()
        if items:
            placement.align(items, self.doc, axis, anchor, self.align_reference.get() == "Printable area")
            self.placement_changed()

    def distribute_selection(self, axis):
        try:
            placement.distribute(self.items(), axis)
        except ValueError as exc:
            self.footer.set(str(exc))
            return
        self.placement_changed()

    def placement_settings(self):
        self.settings.update(grid=self.grid_visible.get(), snap=self.snap_grid.get())
        self.persist_settings()
        self.draw_stage()

    def content_controls(self, parent, item):
        ttk.Label(parent, text="Label text" if item["kind"] == "text" else "Barcode value",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        text = self.editor_text = tk.Text(parent, height=5 if item["kind"] == "text" else 2, width=24,
                                          wrap="word", relief="flat", borderwidth=0, highlightthickness=1,
                                          padx=6, pady=5, undo=True)
        self.style_text(text)
        text.pack(fill="x", pady=(0, 7))
        text.insert("1.0", item["value"])
        text.edit_modified(False)

        def update(_):
            if text.edit_modified():
                text.edit_modified(False)
                item["value"] = text.get("1.0", "end-1c")
                self.layer_tree.set(item["id"], "layer", self.layer_title(item))
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
        parent = self.page_panel
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
        size_row = ttk.Frame(parent)
        size_row.pack(fill="x")
        length_column, width_column = ttk.Frame(size_row), ttk.Frame(size_row)
        for column in (length_column, width_column):
            column.pack(side="left", fill="x", expand=True, padx=(0, 5))
        width_control = field(length_column, "Length · mm", w_value, width=7)
        height_control = field(width_column, "Width · mm", h_value, width=7)

        def resize(*_):
            try:
                next_width, next_height = dimensions({"width": w_value.get(), "height": h_value.get()})
            except ValueError:
                return
            if (next_width, next_height) == dimensions(self.doc):
                return
            self.doc.update(width=next_width, height=next_height)
            for item in self.doc["elements"]:
                placement.fit_box(item, (next_width, next_height))
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
