"""Graphical office suite for Operator virtual-storage documents."""

import json
import shutil
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from core.office_suite import SpreadsheetDatabase


WRITER_TYPES = (".opdoc", ".md", ".txt")
SHEET_TYPE = ".opsheet"
SLIDE_TYPE = ".opsdeck"
DOCUMENT_TYPES = WRITER_TYPES + (SHEET_TYPE, SLIDE_TYPE)


def _column_name(index):
    label = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


class OfficeApplication:
    def __init__(self, root, home_path, mode="home", initial_path=None):
        self.root = root
        self.home_path = Path(home_path).resolve()
        self.documents_path = self.home_path / "Documents"
        self.documents_path.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.initial_path = Path(initial_path).resolve() if initial_path else None
        self.root.title("Operator Office")
        self.root.geometry("900x600")
        self.root.minsize(720, 460)
        self._build_home()
        self.refresh_files()
        if self.mode != "home":
            self.root.after_idle(self._open_initial_tool)

    def _build_home(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = ttk.Frame(self.root, padding=(18, 14))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Operator Office", font=("Segoe UI", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Create and edit documents, database spreadsheets, and presentations.",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(self.root, padding=(18, 0, 18, 16))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        actions = ttk.Frame(body)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for text, callback in (
            ("New document", self.new_writer),
            ("New spreadsheet", self.new_sheet),
            ("New presentation", self.new_slides),
            ("Open file...", self.open_file),
            ("Delete selected", self.delete_selected),
            ("Refresh", self.refresh_files),
        ):
            ttk.Button(actions, text=text, command=callback).pack(
                side="left", padx=(0, 8)
            )

        self.file_list = tk.Listbox(body, activestyle="dotbox", font=("Segoe UI", 10))
        self.file_list.grid(row=1, column=0, sticky="nsew")
        self.file_list.bind("<Double-Button-1>", self.open_selected)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.file_list.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=scrollbar.set)
        self.status = tk.StringVar(value=f"Files in {self.documents_path}")
        ttk.Label(body, textvariable=self.status, anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

    def _open_initial_tool(self):
        if self.initial_path:
            self.open_path(self.initial_path)
            return
        {
            "writer": self.new_writer,
            "sheet": self.new_sheet,
            "slides": self.new_slides,
        }[self.mode]()

    def _inside_home(self, path):
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self.home_path)
        except ValueError as exc:
            raise ValueError("Office files must remain inside the active user's home folder") from exc
        return resolved

    def refresh_files(self):
        if not hasattr(self, "file_list"):
            return
        self.file_list.delete(0, tk.END)
        paths = sorted(
            (
                path
                for path in self.documents_path.rglob("*")
                if path.is_file() and path.suffix.casefold() in DOCUMENT_TYPES
            ),
            key=lambda path: path.name.casefold(),
        )
        for path in paths:
            self.file_list.insert(tk.END, str(path.relative_to(self.documents_path)))
        self.status.set(f"{len(paths)} document(s) in {self.documents_path}")

    def _new_path(self, title, extension, filetypes, allowed_extensions=None):
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title=title,
            initialdir=self.documents_path,
            defaultextension=extension,
            filetypes=filetypes,
        )
        if not selected:
            return None
        try:
            path = self._inside_home(selected)
        except ValueError as exc:
            messagebox.showerror("Invalid location", str(exc), parent=self.root)
            return None
        if path.suffix.casefold() not in (allowed_extensions or (extension,)):
            messagebox.showerror(
                "Invalid file type",
                f"Choose a file ending in {', '.join(allowed_extensions or (extension,))}.",
                parent=self.root,
            )
            return None
        if path.exists():
            messagebox.showerror(
                "File already exists",
                "Choose a new file name; existing files are not overwritten.",
                parent=self.root,
            )
            return None
        return path

    def new_writer(self):
        path = self._new_path(
            "Create document",
            ".opdoc",
            [("Operator documents", "*.opdoc"), ("Text and Markdown", "*.txt *.md")],
            allowed_extensions=WRITER_TYPES,
        )
        if path:
            try:
                path.touch(exist_ok=False)
                WriterWindow(self, path, "")
            except OSError as exc:
                messagebox.showerror("Could not create document", str(exc), parent=self.root)
            self.refresh_files()

    def new_sheet(self):
        path = self._new_path(
            "Create spreadsheet database",
            SHEET_TYPE,
            [("Operator database spreadsheet", "*.opsheet")],
        )
        if path:
            SheetWindow(self, path, create=True)
            self.refresh_files()

    def new_slides(self):
        path = self._new_path(
            "Create presentation",
            SLIDE_TYPE,
            [("Operator slide deck", "*.opsdeck")],
        )
        if path:
            try:
                deck = {"title": path.stem, "slides": []}
                path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8")
                SlidesWindow(self, path, deck)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Could not create presentation", str(exc), parent=self.root)
            self.refresh_files()

    def open_file(self):
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Open office file",
            initialdir=self.documents_path,
            filetypes=[
                ("Operator office files", "*.opdoc *.md *.txt *.opsheet *.opsdeck"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.open_path(selected)

    def open_selected(self, _event=None):
        selection = self.file_list.curselection()
        if selection:
            self.open_path(self.documents_path / self.file_list.get(selection[0]))

    def delete_selected(self):
        selection = self.file_list.curselection()
        if not selection:
            messagebox.showinfo("Delete office file", "Select a file first.", parent=self.root)
            return
        try:
            path = self._inside_home(
                self.documents_path / self.file_list.get(selection[0])
            )
            if messagebox.askyesno(
                "Delete office file",
                f"Delete {path.name}? This cannot be undone.",
                parent=self.root,
            ):
                path.unlink()
                self.refresh_files()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not delete file", str(exc), parent=self.root)

    def open_path(self, path):
        try:
            path = self._inside_home(path)
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {path.name}")
            suffix = path.suffix.casefold()
            if suffix in WRITER_TYPES:
                WriterWindow(self, path, path.read_text(encoding="utf-8"))
            elif suffix == SHEET_TYPE:
                SheetWindow(self, path)
            elif suffix == SLIDE_TYPE:
                SlidesWindow(self, path)
            else:
                raise ValueError(f"Unsupported office file type: {suffix or '(none)'}")
        except (OSError, UnicodeError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
            messagebox.showerror("Could not open file", str(exc), parent=self.root)


class WriterWindow(tk.Toplevel):
    def __init__(self, application, path, content):
        super().__init__(application.root)
        self.application = application
        self.path = path
        self.dirty = False
        self.title(path.name)
        self.geometry("800x560")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Save", command=self.save).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Save as...", command=self.save_as).pack(side="left", padx=3)
        self.editor = tk.Text(self, wrap="word", undo=True, font=("Consolas", 11))
        self.editor.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.editor.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.editor.configure(yscrollcommand=scroll.set)
        self.editor.insert("1.0", content)
        self.editor.edit_modified(False)
        self.editor.bind("<<Modified>>", self._modified)

    def _modified(self, _event=None):
        if self.editor.edit_modified():
            self.dirty = True
            self.title(f"* {self.path.name}")
            self.editor.edit_modified(False)

    def save(self):
        try:
            self.path = self.application._inside_home(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
            self.dirty = False
            self.title(self.path.name)
            self.application.refresh_files()
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save document", str(exc), parent=self)
            return False

    def save_as(self):
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Save document as",
            initialdir=self.path.parent,
            initialfile=self.path.name,
            defaultextension=".opdoc",
            filetypes=[("Operator document", "*.opdoc"), ("Markdown", "*.md"), ("Text", "*.txt")],
        )
        if not selected:
            return
        try:
            target = self.application._inside_home(selected)
            if target.suffix.casefold() not in WRITER_TYPES:
                raise ValueError("Documents must use .opdoc, .md, or .txt")
            if target.exists() and target != self.path:
                raise FileExistsError(f"{target.name} already exists")
            previous = self.path
            self.path = target
            if not self.save():
                self.path = previous
                self.title(f"* {previous.name}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save document", str(exc), parent=self)

    def close(self):
        if self.dirty and not messagebox.askyesno(
            "Unsaved document",
            "Discard unsaved changes?",
            parent=self,
        ):
            return
        self.destroy()


class SheetWindow(tk.Toplevel):
    def __init__(self, application, path, create=False):
        super().__init__(application.root)
        self.application = application
        self.path = path
        self.database = SpreadsheetDatabase(path)
        if create:
            self.database.create(title=path.stem)
        self.data = self.database.load()
        self.title(f"{path.name} — Database Spreadsheet")
        self.geometry("1000x620")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Add row", command=self.add_row).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Add column", command=self.add_column).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Save as...", command=self.save_as).pack(side="left", padx=3)
        ttk.Label(toolbar, text="Double-click a cell to edit it").pack(side="left", padx=12)

        self.grid_view = ttk.Treeview(
            self,
            show="tree headings",
            selectmode="browse",
        )
        self.grid_view.grid(row=1, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.grid_view.yview)
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.grid_view.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.grid_view.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.grid_view.bind("<Double-Button-1>", self.edit_cell)
        self.status = tk.StringVar(value=f"SQLite spreadsheet database: {self.path}")
        ttk.Label(self, textvariable=self.status, anchor="w").grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=6
        )
        self.refresh_grid()

    def refresh_grid(self):
        self.grid_view.heading("#0", text="Row")
        self.grid_view.column("#0", width=55, minwidth=50, stretch=False)
        columns = [f"c{index}" for index in range(self.data["columns"])]
        self.grid_view.configure(columns=columns)
        for index, column in enumerate(columns):
            self.grid_view.heading(column, text=_column_name(index))
            self.grid_view.column(column, width=110, minwidth=72, stretch=False)
        self.grid_view.delete(*self.grid_view.get_children())
        for row_index in range(self.data["rows"]):
            row_id = f"r{row_index}"
            values = [
                self.data["cells"].get((row_index, column_index), "")
                for column_index in range(self.data["columns"])
            ]
            self.grid_view.insert(
                "",
                "end",
                iid=row_id,
                text=str(row_index + 1),
                values=values,
            )
        self.status.set(
            f"{self.data['rows']} rows × {self.data['columns']} columns | SQLite database: {self.path}"
        )

    def edit_cell(self, event):
        region = self.grid_view.identify("region", event.x, event.y)
        row_id = self.grid_view.identify_row(event.y)
        column_id = self.grid_view.identify_column(event.x)
        if region != "cell" or not row_id or not column_id:
            return
        row_index = int(row_id[1:])
        column_index = int(column_id[1:]) - 1
        existing = self.data["cells"].get((row_index, column_index), "")
        value = simpledialog.askstring(
            "Edit spreadsheet cell",
            f"{_column_name(column_index)}{row_index + 1}",
            initialvalue=existing,
            parent=self,
        )
        if value is None:
            return
        try:
            self.database.set_cell(row_index, column_index, value)
            if value:
                self.data["cells"][(row_index, column_index)] = value
            else:
                self.data["cells"].pop((row_index, column_index), None)
            self.refresh_grid()
        except (OSError, sqlite3.Error, ValueError) as exc:
            messagebox.showerror("Could not save cell", str(exc), parent=self)

    def add_row(self):
        self._resize(rows=self.data["rows"] + 1, columns=self.data["columns"])

    def add_column(self):
        self._resize(rows=self.data["rows"], columns=self.data["columns"] + 1)

    def _resize(self, rows, columns):
        try:
            self.database.resize(rows, columns)
            self.data = self.database.load()
            self.refresh_grid()
        except (OSError, sqlite3.Error, ValueError) as exc:
            messagebox.showerror("Could not resize spreadsheet", str(exc), parent=self)

    def save_as(self):
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Save spreadsheet database as",
            initialdir=self.path.parent,
            initialfile=self.path.name,
            defaultextension=SHEET_TYPE,
            filetypes=[("Operator database spreadsheet", "*.opsheet")],
        )
        if not selected:
            return
        try:
            target = self.application._inside_home(selected)
            if target.suffix.casefold() != SHEET_TYPE:
                raise ValueError(f"Database spreadsheets must use the {SHEET_TYPE} extension")
            if target.exists() and target != self.path:
                raise FileExistsError(f"{target.name} already exists")
            if target != self.path:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.path, target)
                self.path = target
                self.database = SpreadsheetDatabase(target)
                self.title(f"{target.name} — Database Spreadsheet")
                self.refresh_grid()
                self.application.refresh_files()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save spreadsheet", str(exc), parent=self)


class SlidesWindow(tk.Toplevel):
    def __init__(self, application, path, deck=None):
        super().__init__(application.root)
        self.application = application
        self.path = path
        self.deck = deck if deck is not None else self._read_deck(path)
        self.selected_slide = None
        self.dirty = deck is not None
        self.title(f"{path.name} — Presentation")
        self.geometry("900x600")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(toolbar, text="Add slide", command=self.add_slide).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Remove slide", command=self.remove_slide).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Save", command=self.save).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Save as...", command=self.save_as).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Present", command=self.present).pack(side="left", padx=3)

        self.slide_list = tk.Listbox(self, width=28, font=("Segoe UI", 10))
        self.slide_list.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.slide_list.bind("<<ListboxSelect>>", self.select_slide)
        editor = ttk.Frame(self, padding=8)
        editor.grid(row=1, column=1, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(3, weight=1)
        ttk.Label(editor, text="Presentation title").grid(row=0, column=0, sticky="w")
        self.title_entry = ttk.Entry(editor)
        self.title_entry.grid(row=1, column=0, sticky="ew", pady=(2, 10))
        self.title_entry.insert(0, self.deck["title"])
        self.title_entry.bind("<KeyRelease>", self.mark_dirty)
        ttk.Label(editor, text="Slide title").grid(row=2, column=0, sticky="w")
        self.slide_title = ttk.Entry(editor)
        self.slide_title.grid(row=3, column=0, sticky="new", pady=(2, 8))
        self.slide_title.bind("<KeyRelease>", self.mark_dirty)
        ttk.Label(editor, text="Slide content").grid(row=4, column=0, sticky="w")
        self.slide_body = tk.Text(editor, wrap="word", undo=True, font=("Segoe UI", 11))
        self.slide_body.grid(row=5, column=0, sticky="nsew", pady=(2, 0))
        editor.rowconfigure(5, weight=1)
        self.slide_body.bind("<<Modified>>", self._body_modified)
        self.status = tk.StringVar(value=str(self.path))
        ttk.Label(self, textvariable=self.status, anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=6
        )
        self.refresh_slides()

    @staticmethod
    def _read_deck(path):
        deck = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(deck, dict)
            or not isinstance(deck.get("title"), str)
            or not isinstance(deck.get("slides"), list)
            or any(
                not isinstance(slide, dict)
                or not isinstance(slide.get("title"), str)
                or not isinstance(slide.get("body"), str)
                for slide in deck["slides"]
            )
        ):
            raise ValueError(f"Invalid slide deck format: {path.name}")
        return deck

    def mark_dirty(self, _event=None):
        self.dirty = True

    def _body_modified(self, _event=None):
        if self.slide_body.edit_modified():
            self.mark_dirty()
            self.slide_body.edit_modified(False)

    def refresh_slides(self, select=None):
        self.slide_list.delete(0, tk.END)
        for index, slide in enumerate(self.deck["slides"], 1):
            self.slide_list.insert(tk.END, f"{index}. {slide['title']}")
        if select is not None and self.deck["slides"]:
            selected = min(select, len(self.deck["slides"]) - 1)
            self.slide_list.selection_set(selected)
            self.slide_list.activate(selected)
            self._load_slide(selected)

    def _commit_current(self):
        if self.selected_slide is None or self.selected_slide >= len(self.deck["slides"]):
            return
        self.deck["title"] = self.title_entry.get()
        self.deck["slides"][self.selected_slide] = {
            "title": self.slide_title.get(),
            "body": self.slide_body.get("1.0", "end-1c"),
        }
        self.slide_list.delete(self.selected_slide)
        self.slide_list.insert(
            self.selected_slide,
            f"{self.selected_slide + 1}. {self.deck['slides'][self.selected_slide]['title']}",
        )

    def _load_slide(self, index):
        self._commit_current()
        self.selected_slide = index
        slide = self.deck["slides"][index]
        self.slide_title.delete(0, tk.END)
        self.slide_title.insert(0, slide["title"])
        self.slide_body.delete("1.0", tk.END)
        self.slide_body.insert("1.0", slide["body"])
        self.slide_body.edit_modified(False)

    def select_slide(self, _event=None):
        selection = self.slide_list.curselection()
        if selection:
            self._load_slide(selection[0])

    def add_slide(self):
        self._commit_current()
        self.deck["slides"].append({"title": "New slide", "body": ""})
        self.dirty = True
        self.refresh_slides(len(self.deck["slides"]) - 1)

    def remove_slide(self):
        selection = self.slide_list.curselection()
        if not selection:
            return
        index = selection[0]
        self.deck["slides"].pop(index)
        self.selected_slide = None
        self.dirty = True
        self.refresh_slides(index - 1 if index else 0)
        if not self.deck["slides"]:
            self.slide_title.delete(0, tk.END)
            self.slide_body.delete("1.0", tk.END)

    def save(self):
        try:
            self._commit_current()
            self.deck["title"] = self.title_entry.get()
            self.path = self.application._inside_home(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.deck, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.dirty = False
            self.title(f"{self.path.name} — Presentation")
            self.application.refresh_files()
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save presentation", str(exc), parent=self)
            return False

    def save_as(self):
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Save presentation as",
            initialdir=self.path.parent,
            initialfile=self.path.name,
            defaultextension=SLIDE_TYPE,
            filetypes=[("Operator slide deck", "*.opsdeck")],
        )
        if not selected:
            return
        try:
            target = self.application._inside_home(selected)
            if target.suffix.casefold() != SLIDE_TYPE:
                raise ValueError(f"Presentations must use the {SLIDE_TYPE} extension")
            if target.exists() and target != self.path:
                raise FileExistsError(f"{target.name} already exists")
            previous = self.path
            self.path = target
            if not self.save():
                self.path = previous
                self.title(f"{previous.name} — Presentation")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save presentation", str(exc), parent=self)

    def present(self):
        self._commit_current()
        self.deck["title"] = self.title_entry.get()
        if not self.deck["slides"]:
            messagebox.showinfo("Presentation", "Add at least one slide to present.", parent=self)
            return
        PresentationWindow(self, self.deck)

    def close(self):
        if self.dirty:
            decision = messagebox.askyesnocancel(
                "Unsaved presentation",
                "Save changes before closing?",
                parent=self,
            )
            if decision is None:
                return
            if decision and not self.save():
                return
        self.destroy()


class PresentationWindow(tk.Toplevel):
    def __init__(self, parent, deck):
        super().__init__(parent)
        self.deck = deck
        self.index = 0
        self.title(deck["title"])
        self.geometry("900x560")
        self.configure(background="#111827")
        self.title_label = tk.Label(
            self,
            text="",
            font=("Segoe UI", 28, "bold"),
            foreground="white",
            background="#111827",
            wraplength=800,
        )
        self.title_label.pack(pady=(90, 24), padx=40)
        self.body_label = tk.Label(
            self,
            text="",
            font=("Segoe UI", 17),
            foreground="#d1d5db",
            background="#111827",
            wraplength=760,
            justify="left",
        )
        self.body_label.pack(fill="both", expand=True, padx=70, pady=20)
        controls = ttk.Frame(self, padding=12)
        controls.pack()
        ttk.Button(controls, text="Previous", command=self.previous).pack(side="left", padx=8)
        ttk.Button(controls, text="Next", command=self.next).pack(side="left", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.show_slide()

    def show_slide(self):
        slide = self.deck["slides"][self.index]
        self.title_label.configure(text=f"{self.deck['title']}\n\n{slide['title']}")
        self.body_label.configure(text=slide["body"])

    def previous(self):
        self.index = (self.index - 1) % len(self.deck["slides"])
        self.show_slide()

    def next(self):
        self.index = (self.index + 1) % len(self.deck["slides"])
        self.show_slide()


def launch_office(mode, home_path, initial_path=None):
    root = tk.Tk()
    OfficeApplication(root, home_path, mode=mode, initial_path=initial_path)
    root.mainloop()
