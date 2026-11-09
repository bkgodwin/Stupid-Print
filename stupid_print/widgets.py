"""Desktop theme and a paged list for arbitrarily large batches."""

import tkinter as tk
from tkinter import ttk
from tkinter.font import nametofont


DARK = dict(background="#11141c", panel="#191e2a", field="#141924", raised="#252d3f",
            ink="#ecf0fa", muted="#aab6ce", line="#384459", accent="#7967fb", hover="#353f58",
            selected="#413875", selection_outline="#a896ff", stage="#101522",
            shadow="#080b12", good="#62d8a9", error="#ff9dab", guide="#efbb68", header="#1b2031")
LIGHT = dict(background="#edf0f7", panel="#ffffff", field="#f8f9fd", raised="#eef0f7",
             ink="#17233c", muted="#56647e", line="#ccd4e4", accent="#4e3bd6", hover="#e1e6f6",
             selected="#e6e2ff", selection_outline="#5945d9", stage="#dfe5f2",
             shadow="#bbc6dc", good="#16734e", error="#a23546", guide="#8a581c", header="#17233c")


def configure_style(root, dark):
    colors = DARK if dark else LIGHT
    c = colors
    root.configure(background=c["background"])
    for key, color in (("background", c["field"]), ("foreground", c["ink"]),
                       ("selectBackground", c["selected"]), ("selectForeground", c["ink"])):
        root.option_add(f"*TCombobox*Listbox.{key}", color)
    family = nametofont("TkDefaultFont", root=root).actual("family")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=c["panel"], foreground=c["ink"], font=(family, 10),
                    bordercolor=c["line"], lightcolor=c["line"], darkcolor=c["line"],
                    troughcolor=c["field"], arrowcolor=c["ink"], selectbackground=c["selected"],
                    selectforeground=c["ink"], focuscolor=c["selection_outline"])
    style.configure("TFrame", background=c["panel"])
    style.configure("App.TFrame", background=c["background"])
    style.configure("TLabel", padding=0)
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Error.TLabel", foreground=c["error"])
    style.configure("App.TLabel", foreground=c["muted"], background=c["background"])
    style.configure("Title.TLabel", font=(family, 21, "bold"))
    style.configure("Section.TLabel", font=(family, 12, "bold"))
    style.configure("Header.TFrame", background=c["header"])
    style.configure("Header.TLabel", background=c["header"], foreground="#ffffff", font=(family, 20, "bold"))
    style.configure("HeaderSub.TLabel", background=c["header"], foreground="#bdc9e4", font=(family, 8))
    style.configure("TButton", background=c["raised"], padding=(8, 5), borderwidth=0)
    style.configure("TMenubutton", background=c["raised"], padding=(8, 5))
    for name in ("TButton", "TMenubutton", "TScrollbar"):
        style.map(name, background=[("pressed", c["selected"]), ("active", c["hover"])],
                  foreground=[("disabled", c["muted"])])
    style.configure("Accent.TButton", background=c["accent"], foreground="white", padding=(12, 7))
    style.map("Accent.TButton", background=[("disabled", c["raised"]), ("active", "#5845d6")],
              foreground=[("disabled", c["muted"])])
    style.configure("TEntry", fieldbackground=c["field"], insertcolor=c["ink"], padding=(6, 4))
    style.configure("TCombobox", fieldbackground=c["field"], background=c["raised"],
                    insertcolor=c["ink"], padding=(5, 4), arrowsize=14)
    style.map("TCombobox", fieldbackground=[("readonly", c["field"])],
              selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["ink"])])
    style.configure("TCheckbutton", indicatorbackground=c["field"], indicatorforeground=c["ink"])
    style.map("TCheckbutton", indicatorbackground=[("selected", c["selected"])],
              background=[("active", c["panel"])])
    style.configure("TNotebook", background=c["panel"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(9, 7), background=c["raised"])
    style.map("TNotebook.Tab", background=[("selected", c["selected"]), ("active", c["hover"])],
              foreground=[("selected", c["ink"])])
    style.configure("Treeview", fieldbackground=c["field"], background=c["field"], rowheight=25, borderwidth=0)
    style.configure("Treeview.Heading", background=c["raised"], padding=(5, 5))
    style.map("Treeview.Heading", background=[("active", c["hover"])])
    style.map("Treeview", background=[("selected", c["selected"])], foreground=[("selected", c["ink"])])
    style.configure("TScrollbar", background=c["raised"])
    style.configure("TProgressbar", background=c["accent"], troughcolor=c["field"])
    return colors


def button(parent, label, command, primary=False, **options):
    return ttk.Button(parent, text=label, command=command, style="Accent.TButton" if primary else "TButton",
                      **options)


def field(parent, label, variable, options=None, editable=False, width=12):
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 5))
    ttk.Label(row, text=label, style="Muted.TLabel").pack(anchor="w", pady=(0, 2))
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
        self.previous = button(controls, "‹", lambda: self.change_page(-1), width=3)
        self.previous.pack(side="left")
        self.next = button(controls, "›", lambda: self.change_page(1), width=3)
        self.next.pack(side="left", padx=(3, 8))
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
        self.can_toggle = lambda: True

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

    def change_page(self, direction):
        number = self.start + direction * self.page_size
        self.show(number, focus=number)

    def show(self, start=None, focus=None):
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        if self.batch is None:
            self.caption.set("No batch")
            self.previous.state(["disabled"])
            self.next.state(["disabled"])
            return
        last_page = ((self.batch.count - 1) // self.page_size) * self.page_size + 1
        self.start = max(1, min(last_page, self.start if start is None else start))
        end = min(self.batch.count, self.start + self.page_size - 1)
        self.previous.state(["!disabled" if self.start > 1 else "disabled"])
        self.next.state(["!disabled" if end < self.batch.count else "disabled"])
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
        if not self.can_toggle():
            return
        number = int(row)
        self.selection.toggle(number)
        self.tree.set(row, "picked", "✓" if number in self.selection else "○")
        self.on_toggle()
