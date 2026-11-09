"""Desktop theme and a paged list for arbitrarily large batches."""

import tkinter as tk
from tkinter import ttk
from tkinter.font import nametofont


BACKGROUND = "#edf0f7"
PANEL = "#ffffff"
INK = "#17233c"
MUTED = "#56647e"
ACCENT = "#4e3bd6"
ACCENT_HOVER = "#4030b8"
PREVIEW = "#dfe5f2"
ERROR = "#a23546"
GOOD = "#16734e"


def configure_style(root):
    root.configure(background=BACKGROUND)
    family = nametofont("TkDefaultFont", root=root).actual("family")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANEL, foreground=INK, font=(family, 10))
    style.configure("TFrame", background=PANEL)
    style.configure("App.TFrame", background=BACKGROUND)
    style.configure("TLabel", padding=0)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("App.TLabel", foreground=MUTED, background=BACKGROUND)
    style.configure("Title.TLabel", font=(family, 21, "bold"))
    style.configure("Section.TLabel", font=(family, 12, "bold"))
    style.configure("Header.TFrame", background=INK)
    style.configure("Header.TLabel", background=INK, foreground="#ffffff", font=(family, 20, "bold"))
    style.configure("HeaderSub.TLabel", background=INK, foreground="#bdc9e4", font=(family, 8))
    style.configure("TButton", background="#eef0f7", foreground=INK, padding=(9, 6), borderwidth=0)
    style.map("TButton", background=[("pressed", "#dce1f3"), ("active", "#e1e6f6")],
              foreground=[("disabled", "#8590a7")])
    style.configure("Accent.TButton", background=ACCENT, foreground="white", padding=(12, 7))
    style.map("Accent.TButton", background=[("disabled", "#d9d8ef"), ("active", ACCENT_HOVER)],
              foreground=[("disabled", "#626580")])
    style.configure("TEntry", fieldbackground="#f8f9fd", padding=(6, 5))
    style.configure("TCombobox", fieldbackground="#f8f9fd", padding=(5, 4), arrowsize=14)
    style.map("TCombobox", fieldbackground=[("readonly", "#f8f9fd")],
              selectbackground=[("readonly", "#f8f9fd")], selectforeground=[("readonly", INK)])
    style.configure("TNotebook", background=PANEL, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(12, 7), background="#eef0f7")
    style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
    style.configure("Treeview", fieldbackground=PANEL, rowheight=28, borderwidth=0)
    style.configure("Treeview.Heading", background="#eef0f7", padding=(5, 5))
    style.map("Treeview", background=[("selected", "#e6e2ff")], foreground=[("selected", INK)])
    style.configure("TProgressbar", background=ACCENT, troughcolor="#e8e6f7")


def button(parent, label, command, primary=False, **options):
    return ttk.Button(parent, text=label, command=command, style="Accent.TButton" if primary else "TButton",
                      **options)


def field(parent, label, variable, options=None, editable=False, width=12):
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 7))
    ttk.Label(row, text=label, style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
    if options is None:
        control = ttk.Entry(row, textvariable=variable, width=width)
    else:
        control = ttk.Combobox(row, textvariable=variable, values=options, width=width,
                               state="normal" if editable else "readonly")
    control.pack(fill="x")
    return control


def tree_with_scroll(parent, columns, **kwargs):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show="headings", **kwargs)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    return frame, tree


class ScrollPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=PANEL, width=270)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, padding=(6, 4, 9, 4))
        window = self.canvas.create_window((0, 0), anchor="nw", window=self.content)
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        top = self.winfo_toplevel()
        for key in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            top.bind(key, self._wheel, add="+")

    def _wheel(self, event):
        target = self.winfo_containing(event.x_root, event.y_root)
        if target is None or not str(target).startswith(str(self.content)):
            return
        if isinstance(target, (tk.Text, ttk.Combobox)):
            return
        step = -1 if (getattr(event, "num", 0) == 4 or event.delta > 0) else 1
        self.canvas.yview_scroll(step * 3, "units")


class BatchList(ttk.Frame):
    page_size = 150

    def __init__(self, parent, preview, selection=None):
        super().__init__(parent)
        self.preview = preview
        self.selection = selection
        self.batch = None
        self.start = 1
        self.number = tk.StringVar(value="1")
        self.caption = tk.StringVar(value="No batch")
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 6))
        button(controls, "‹", lambda: self.show(self.start - self.page_size), width=3).pack(side="left")
        button(controls, "›", lambda: self.show(self.start + self.page_size), width=3).pack(side="left", padx=(3, 8))
        ttk.Label(controls, textvariable=self.caption, style="Muted.TLabel").pack(side="left")
        button(controls, "Go", self.jump, width=4).pack(side="right")
        go = ttk.Entry(controls, textvariable=self.number, width=7)
        go.pack(side="right", padx=(6, 4))
        go.bind("<Return>", lambda _: self.jump())
        columns = ("picked", "number", "summary") if selection is not None else ("number", "summary")
        frame, self.tree = tree_with_scroll(self, columns, selectmode="browse", height=5)
        frame.pack(fill="both", expand=True)
        if selection is not None:
            self.tree.heading("picked", text="Print")
            self.tree.column("picked", width=48, minwidth=44, stretch=False, anchor="center")
            self.tree.bind("<ButtonRelease-1>", self._click)
            self.tree.bind("<space>", self._space)
        self.tree.heading("number", text="#")
        self.tree.column("number", width=68, minwidth=47, stretch=False, anchor="center")
        self.tree.heading("summary", text="Label contents", anchor="w")
        self.tree.column("summary", width=200)
        self.tree.bind("<<TreeviewSelect>>", self._preview)
        self.on_toggle = lambda: None

    def set_batch(self, batch, number=1):
        self.batch = batch
        page = ((number - 1) // self.page_size) * self.page_size + 1
        self.show(page, focus=number)

    def jump(self):
        try:
            number = int(self.number.get())
            if self.batch and 1 <= number <= self.batch.count:
                self.set_batch(self.batch, number)
                self.preview(number)
        except ValueError:
            pass

    def show(self, start=None, focus=None):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        if self.batch is None:
            self.caption.set("No batch")
            return
        last_page = ((self.batch.count - 1) // self.page_size) * self.page_size + 1
        self.start = max(1, min(last_page, self.start if start is None else start))
        end = min(self.batch.count, self.start + self.page_size - 1)
        self.caption.set(f"{self.start:,}–{end:,} of {self.batch.count:,}")
        for number in range(self.start, end + 1):
            try:
                summary = self.batch.summary(number - 1)
            except (ValueError, TypeError, KeyError) as exc:
                summary = str(exc)
            values = (number, summary)
            if self.selection is not None:
                values = ("✓" if number in self.selection else "○", *values)
            self.tree.insert("", "end", iid=str(number), values=values)
        if focus is not None and self.tree.exists(str(focus)):
            self.tree.selection_set(str(focus))
            self.tree.see(str(focus))
            self.number.set(str(focus))

    def _preview(self, _):
        chosen = self.tree.selection()
        if chosen:
            self.number.set(chosen[0])
            self.preview(int(chosen[0]))

    def _click(self, event):
        if self.tree.identify_column(event.x) == "#1":
            row = self.tree.identify_row(event.y)
            if row:
                self._toggle(row)

    def _space(self, _):
        chosen = self.tree.selection()
        if chosen:
            self._toggle(chosen[0])
        return "break"

    def _toggle(self, row):
        number = int(row)
        self.selection.toggle(number)
        self.tree.set(row, "picked", "✓" if number in self.selection else "○")
        self.on_toggle()
