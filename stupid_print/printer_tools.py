"""Dialogs for printer profiles, roll estimates, and the local job log."""

import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .dialogs import SettingsDialog
from .widgets import button, field, tree_with_scroll


MODELS = {"Auto detect": "", "Phomemo D30": "D30", "Phomemo D30N": "D30", "Nelko P21": "P21"}
NEW_PROFILE = "New profile…"


class ProfilesDialog(SettingsDialog):
    def __init__(self, app, port, width):
        self.app = app
        self.profiles = app.settings.get("profiles", {})
        self.defaults = {"port": port, "model": "Auto detect", "width": width}
        self.active = app.settings.get("active_profile", NEW_PROFILE)
        super().__init__(app.root, "Printer profiles")

    def body(self, parent):
        super().body(parent)
        self.choice = tk.StringVar(value=self.active if self.active in self.profiles else NEW_PROFILE)
        self.name = tk.StringVar()
        self.device = tk.StringVar()
        self.model = tk.StringVar()
        self.width = tk.StringVar()
        self.error = tk.StringVar()
        options = (NEW_PROFILE, *sorted(self.profiles, key=str.casefold))
        control = field(parent, "Choose a profile", self.choice, options, width=34)
        control.bind("<<ComboboxSelected>>", lambda _: self.load())
        name = field(parent, "Profile name", self.name)
        field(parent, "Bluetooth printer or serial port", self.device,
              tuple(port.display for port in self.app.ports.values()), editable=True)
        field(parent, "Printer model", self.model, tuple(MODELS))
        field(parent, "Tape width (mm)", self.width)
        button(parent, "Use detected tape width", self.detect_width).pack(anchor="w")
        ttk.Label(parent, text="Save & use applies the port, model and width to the current design. "
                  "Detected width is available when the printer reports readable roll dimensions.",
                  wraplength=330, style="Muted.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(parent, textvariable=self.error, wraplength=330, style="Error.TLabel").pack(anchor="w")
        self.load()
        return name

    def buttonbox(self):
        row = ttk.Frame(self, padding=(12, 4, 12, 10))
        row.pack(fill="x")
        button(row, "Save & use", self.ok, primary=True).pack(side="right")
        button(row, "Cancel", self.cancel).pack(side="right", padx=5)
        self.delete_button = button(row, "Delete profile", self.delete)
        self.delete_button.pack(side="left")
        button(row, "Clear active", self.clear_active).pack(side="left", padx=5)
        self.update_delete()
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def load(self):
        key = self.choice.get()
        profile = self.profiles.get(key, self.defaults)
        self.name.set("" if key == NEW_PROFILE else key)
        port = self.app.resolve_port(profile["port"])
        self.device.set(port.display if port else "")
        self.model.set(profile["model"])
        self.width.set(f"{profile['width']:g}")
        self.error.set("")
        if hasattr(self, "delete_button"):
            self.update_delete()

    def update_delete(self):
        self.delete_button.state(["!disabled"] if self.choice.get() in self.profiles else ["disabled"])

    def detect_width(self):
        roll = self.app.loaded_roll
        port = self.app.resolve_port(self.device.get())
        if self.app.printer_busy or not roll or not port or port.device != self.app.checked_device:
            self.error.set("Check status on this printer first. Tape width is available from a readable P21 roll tag.")
            return
        self.width.set(f"{roll.width:g}")
        self.error.set("")

    def validate(self):
        name = self.name.get().strip()
        port = self.app.resolve_port(self.device.get())
        previous = self.choice.get()
        if not 1 <= len(name) <= 60 or name == NEW_PROFILE or not port:
            self.error.set("Enter a profile name (up to 60 characters) and choose a printer or port.")
            return False
        if any(key.casefold() == name.casefold() and key != previous for key in self.profiles):
            self.error.set("A profile with this name already exists.")
            return False
        try:
            width = float(self.width.get())
            if not 5 <= width <= 15:
                raise ValueError
        except ValueError:
            self.error.set("Enter a tape width from 5 through 15 mm.")
            return False
        self.result = (previous, name, {"port": port.device, "model": self.model.get(), "width": width})
        return True

    def delete(self):
        self.result = (self.choice.get(), None, None)
        self.cancel()

    def clear_active(self):
        self.result = (None, None, None)
        self.cancel()


class StockDialog(SettingsDialog):
    def __init__(self, parent, port, size, stock):
        self.port = port
        self.size = size
        self.stock = stock
        super().__init__(parent, "Label stock")

    def body(self, parent):
        super().body(parent)
        remaining, threshold = self.stock if self.stock else ("", 10)
        self.remaining = tk.StringVar(value=str(remaining))
        self.threshold = tk.StringVar(value=str(threshold))
        self.error = tk.StringVar()
        ttk.Label(parent, text=self.port, style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text=self.size, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        entry = field(parent, "Estimated labels remaining", self.remaining)
        field(parent, "Low stock warning at or below", self.threshold)
        ttk.Label(parent, text="Set the count when loading a roll or correcting the estimate. "
                  "Leave the count blank to stop tracking this size and media type.",
                  wraplength=310, style="Muted.TLabel").pack(anchor="w", pady=6)
        ttk.Label(parent, textvariable=self.error, wraplength=310, style="Error.TLabel").pack(anchor="w")
        return entry

    def validate(self):
        text = self.remaining.get().strip()
        try:
            remaining = int(text) if text else None
            threshold = int(self.threshold.get()) if text else 0
            if remaining is not None and not (0 <= remaining <= 1_000_000 and 0 <= threshold <= 1_000_000):
                raise ValueError
        except ValueError:
            self.error.set("Enter whole numbers between 0 and 1,000,000.")
            return False
        self.result = (remaining, threshold)
        return True


class JobHistoryDialog(tk.Toplevel):
    def __init__(self, app, jobs, can_reprint):
        super().__init__(app.root)
        self.app = app
        self.jobs = {job["id"]: job for job in jobs}
        self.title("Print history")
        self.transient(app.root)
        self.minsize(680, 350)
        self.configure(background=app.colors["panel"])
        panel = ttk.Frame(self, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Print history", style="Title.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Latest 250 jobs. CSV export includes the full log.", style="Muted.TLabel").pack(
            anchor="w", pady=(0, 8))
        columns = ("timestamp", "title", "port", "count", "outcome")
        frame, self.tree = tree_with_scroll(panel, columns, height=9, selectmode="browse")
        frame.pack(fill="both", expand=True)
        for key, label, width in zip(columns, ("Time", "Design", "Port", "Done / total", "Status"),
                                     (145, 200, 95, 90, 100)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=65, stretch=key == "title")
        for job in jobs:
            timestamp = job["timestamp"][:19].replace("T", " ")
            count = f"{job['completed']:,} / {job['requested']:,}"
            self.tree.insert("", "end", iid=job["id"],
                             values=(timestamp, job["title"], job["port"], count, job["outcome"]))
        self.detail = tk.StringVar(value="No print jobs yet." if not jobs else "")
        self.job_id = tk.StringVar()
        ttk.Label(panel, textvariable=self.detail, wraplength=610, style="Muted.TLabel").pack(
            fill="x", pady=(8, 3))
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Job ID", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        ttk.Entry(row, textvariable=self.job_id, state="readonly", width=35).pack(side="left")
        actions = ttk.Frame(panel)
        actions.pack(fill="x")
        button(actions, "Close", self.destroy).pack(side="right")
        reprint = button(actions, "Reprint last batch…", self.reprint, primary=True)
        reprint.pack(side="right", padx=6)
        reprint.state(["!disabled"] if can_reprint else ["disabled"])
        export = button(actions, "Export CSV…", self.export)
        export.pack(side="left")
        export.state(["!disabled"] if jobs else ["disabled"])
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_detail())
        if jobs:
            self.tree.selection_set(jobs[0]["id"])
            self.show_detail()
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.tree.focus_set()

    def show_detail(self):
        selection = self.tree.selection()
        if selection:
            job = self.jobs[selection[0]]
            self.job_id.set(job["id"])
            self.detail.set(" · ".join(filter(None, (job["model"], job["detail"] or job["outcome"]))))

    def reprint(self):
        self.destroy()
        self.app.reprint_last()

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="print-history.csv",
                                            filetypes=[("CSV log", "*.csv")])
        if path:
            try:
                self.app.jobs.export_csv(path)
                self.app.footer.set("Print history exported.")
            except (OSError, sqlite3.Error) as exc:
                messagebox.showerror("Export print history", str(exc), parent=self)
