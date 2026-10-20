#!/usr/bin/env python3
"""Terminal code editor with syntax highlighting and installable language completion."""

import json
import os
import sqlite3
import shutil
import sys
from pathlib import Path
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, BufferControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.margins import NumberedMargin
from prompt_toolkit.styles import Style
from prompt_toolkit.lexers import PygmentsLexer

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"
PACKAGE_REPO = ROOT_DIR / "packages" / "repo"

# Try Pygments lexers
try:
    from pygments.lexers import get_lexer_for_filename
except ImportError:
    get_lexer_for_filename = None


def load_language_extension(filepath: Optional[str], db_path: Path = DB_PATH) -> Optional[dict]:
    """Load matching completion data only from an installed active package."""
    if not filepath or not db_path.exists():
        return None

    suffix = Path(filepath).suffix.casefold()
    if not suffix:
        return None

    connection = sqlite3.connect(db_path)
    try:
        installed = connection.execute(
            "SELECT id FROM sys_packages WHERE status = 'active' AND id LIKE 'editor.lang.%'"
        ).fetchall()
    finally:
        connection.close()

    for (package_id,) in installed:
        package_parts = package_id.split(".")
        if len(package_parts) < 3 or not all(part.isalnum() for part in package_parts):
            continue
        manifest_path = PACKAGE_REPO / f"{package_id}.manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        extension = manifest.get("editor_extension")
        if not isinstance(extension, dict):
            continue
        file_extensions = extension.get("file_extensions", [])
        completions = extension.get("completions", [])
        if not isinstance(file_extensions, list) or not all(
            isinstance(item, str) and item.startswith(".") for item in file_extensions
        ):
            raise ValueError(f"Invalid file extensions in {manifest_path.name}")
        if suffix not in file_extensions:
            continue
        if not all(isinstance(word, str) and word for word in completions):
            raise ValueError(f"Invalid completion list in {manifest_path.name}")
        language = extension.get("language", package_id.removeprefix("editor.lang."))
        if not isinstance(language, str) or not language:
            raise ValueError(f"Invalid language name in {manifest_path.name}")
        return {
            "package_id": package_id,
            "language": language,
            "completions": sorted(set(completions)),
        }
    return None


class OperatorCodeEditor:
    def __init__(
        self,
        filepath: Optional[str] = None,
        working_dir: Optional[str] = None,
        extension_db_path: Path = DB_PATH,
    ):
        self.filepath = filepath
        self.working_dir = working_dir or (os.path.dirname(filepath) if filepath else os.getcwd())
        self.filename = os.path.basename(filepath) if filepath else "New Buffer"
        self.original_content = ""
        self.message = ""
        self.prompt_mode: Optional[str] = None  # 'writeout', 'exit_confirm', 'search', 'goto_line'
        self.prompt_text = ""
        self.show_help = False
        self.cut_buffer = ""
        self.extension_db_path = extension_db_path
        self.language_extension = load_language_extension(filepath, extension_db_path)
        self.language = self.language_extension["language"] if self.language_extension else "Plain Text"
        self.completion_words = self.language_extension["completions"] if self.language_extension else []

        # Load file content if existing
        if self.filepath and os.path.exists(self.filepath) and os.path.isfile(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
                    self.original_content = f.read()
                line_count = len(self.original_content.splitlines()) or 1
                self.message = f"[ Read {line_count} line{'s' if line_count != 1 else ''} ]"
            except Exception as e:
                self.message = f"[ Error reading file: {e} ]"
        elif self.filepath:
            self.message = "[ New File ]"
        else:
            self.message = "[ New Buffer ]"

        # Editor Buffer
        self.text_buffer = Buffer(
            document=Document(self.original_content, 0),
            completer=self._make_completer(),
            complete_while_typing=bool(self.completion_words),
            multiline=True,
            on_text_changed=self._on_text_changed,
        )

        # Prompt input buffer for Ctrl+O, Ctrl+W, etc.
        self.prompt_buffer = Buffer(multiline=False)

        # Lexer selection
        lexer = self._get_lexer()

        # Keybindings
        self.kb = self._create_keybindings()

        # Build layout
        self.layout = self._create_layout(lexer)

        # Custom Styling
        self.style = Style.from_dict({
            "titlebar": "bg:#1e1e1e #d4d4d4",
            "titlebar.modified": "bg:#1e1e1e #f1c40f bold",
            "titlebar.bracket": "bg:#1e1e1e #569cd6 bold",
            "statusbar": "bg:#007acc #ffffff bold",
            "statusbar.msg": "bg:#252526 #cccccc",
            "prompt.label": "bg:#007acc #ffffff bold",
            "prompt.input": "bg:#1e1e1e #d4d4d4",
            "keybar": "bg:#1e1e1e #9da5b4",
            "keybar.key": "bg:#1e1e1e #4fc1ff bold",
            "keybar.desc": "bg:#1e1e1e #9da5b4",
            "help.box": "bg:#252526 #d4d4d4",
            "help.title": "bg:#007acc #ffffff bold",
            "line-number": "bg:#1e1e1e #858585",
            "line-number.current": "bg:#1e1e1e #c6c6c6 bold",
            "completion-menu": "bg:#252526 #d4d4d4",
            "completion-menu.completion": "bg:#252526 #d4d4d4",
            "completion-menu.completion.current": "bg:#094771 #ffffff",
            "completion-menu.meta": "bg:#252526 #858585",
            "completion-menu.meta.current": "bg:#094771 #ffffff",
            "scrollbar.background": "bg:#1e1e1e",
            "scrollbar.button": "bg:#424242",
        })

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=self.style,
            full_screen=True,
            mouse_support=True,
            editing_mode=EditingMode.EMACS,
        )

    def _make_completer(self):
        if not self.completion_words:
            return None
        return WordCompleter(
            self.completion_words,
            ignore_case=False,
            sentence=True,
            meta_dict={word: self.language for word in self.completion_words},
        )

    def _get_lexer(self):
        if get_lexer_for_filename and self.filepath:
            try:
                return PygmentsLexer(get_lexer_for_filename(self.filepath).__class__)
            except Exception:
                return None
        return None

    def _accept_completion(self):
        if not self.text_buffer.complete_state:
            self.text_buffer.start_completion(select_first=True)
        state = self.text_buffer.complete_state
        if state and state.current_completion is None:
            self.text_buffer.complete_next()
            state = self.text_buffer.complete_state
        if state and state.current_completion:
            self.text_buffer.apply_completion(state.current_completion)

    def is_modified(self) -> bool:
        return self.text_buffer.text != self.original_content

    def _on_text_changed(self, buf):
        # Clear transient position message if user starts typing
        if self.message.startswith("[ line "):
            self.message = ""

    def _get_titlebar_text(self):
        term_width = shutil.get_terminal_size((80, 24)).columns
        status = "● Modified" if self.is_modified() else ""
        left = f"  Operator Editor  |  {self.filename}  "
        right = f"{self.language}  {status}  "
        padding = max(1, term_width - len(left) - len(right))
        return [
            ("class:titlebar", left),
            ("class:titlebar.bracket", f"{self.language_extension['package_id']}  " if self.language_extension else "No language extension  "),
            ("class:titlebar", " " * padding),
            ("class:titlebar.modified" if self.is_modified() else "class:titlebar", right),
        ]

    def _get_statusbar_text(self):
        if self.prompt_mode:
            return [("class:prompt.label", f" {self.prompt_text} ")]
        doc = self.text_buffer.document
        position = f"Ln {doc.cursor_position_row + 1}, Col {doc.cursor_position_col + 1}"
        extension_status = "Autocomplete on" if self.completion_words else "Autocomplete extension not installed"
        status = self.message or f"{self.language}  |  {extension_status}"
        return [
            ("class:statusbar.msg", f"  {status}  "),
            ("class:statusbar", f"{position}  "),
        ]

    def _get_keybar_text_row1(self):
        keys = [
            ("^S", "Save"),
            ("^F", "Find"),
            ("^K", "Cut Line"),
            ("^G", "Help"),
            ("^C", "Cursor"),
        ]
        return self._format_keybar(keys)

    def _get_keybar_text_row2(self):
        keys = [
            ("^X", "Quit"),
            ("Tab", "Complete"),
            ("^R", "Insert File"),
            ("^U", "Paste Line"),
            ("^_", "Go to Line"),
        ]
        return self._format_keybar(keys)

    def _format_keybar(self, keys):
        term_width = shutil.get_terminal_size((80, 24)).columns
        item_width = max(12, term_width // len(keys))
        tokens = []
        for key, desc in keys:
            tokens.append(("class:keybar.key", f" {key} "))
            txt = f"{desc}"
            padding = max(0, item_width - len(key) - 2 - len(txt))
            tokens.append(("class:keybar.desc", f" {txt}{' ' * padding}"))
        return tokens

    def _get_help_text(self):
        return """
  ====================== OPERATOR EDITOR HELP ======================
  Code editor with syntax highlighting and optional language completion.

  ^G (Ctrl+G)  Display this help window
  ^X (Ctrl+X)  Close current buffer / Exit
  ^O (Ctrl+O)  Write current buffer to disk (save file)
  ^S (Ctrl+S)  Save current file
  ^F (Ctrl+F)  Search for text in the current file
  ^K (Ctrl+K)  Cut current line into cutbuffer
  ^U (Ctrl+U)  Uncut (paste) cutbuffer text at current cursor
  ^C (Ctrl+C)  Display current cursor coordinates (line, col, char)
  ^_ (Ctrl+_)  Go to specific line and column number
  ^R (Ctrl+R)  Insert external file content into current buffer
  Tab          Accept the selected completion

  Navigation: Arrow keys move cursor, Home/End jump to line boundaries,
  PageUp/PageDown scroll viewport. Install editor.lang.<language> packages
  to enable that language's completion suggestions.
  =================================================================
        """.strip()

    def _create_layout(self, lexer):
        title_window = Window(
            content=FormattedTextControl(self._get_titlebar_text),
            height=1,
            style="class:titlebar",
        )

        self.editor_control = BufferControl(
            buffer=self.text_buffer,
            lexer=lexer,
        )
        editor_window = Window(
            content=self.editor_control,
            left_margins=[NumberedMargin()],
            wrap_lines=True,
            style="bg:#1e1e1e #d4d4d4",
        )

        # Status & Prompt bar
        status_window = Window(
            content=FormattedTextControl(self._get_statusbar_text),
            height=1,
            style="class:statusbar",
        )

        prompt_input_window = Window(
            content=BufferControl(buffer=self.prompt_buffer),
            height=1,
            style="class:prompt.input",
        )

        prompt_vsplit = VSplit([
            status_window,
            prompt_input_window,
        ])

        # Bottom Shortcut Keybars
        keybar1 = Window(
            content=FormattedTextControl(self._get_keybar_text_row1),
            height=1,
            style="class:keybar",
        )
        keybar2 = Window(
            content=FormattedTextControl(self._get_keybar_text_row2),
            height=1,
            style="class:keybar",
        )

        # Main Vertical Split
        main_hsplit = HSplit([
            title_window,
            editor_window,
            prompt_vsplit,
            keybar1,
            keybar2,
        ])

        # Help modal float
        help_window = Float(
            content=Window(
                content=FormattedTextControl(self._get_help_text),
                style="class:help.box",
            ),
            top=3,
            bottom=3,
            left=6,
            right=6,
            z_index=20,
        )

        root_container = FloatContainer(
            content=main_hsplit,
            floats=self._get_floats(help_window),
        )

        return Layout(root_container, focused_element=editor_window)

    def _get_floats(self, help_window=None):
        floats = [
            Float(content=CompletionsMenu(max_height=8), xcursor=True, ycursor=True, z_index=10),
        ]
        if self.show_help:
            if help_window is None:
                help_window = Float(
                    content=Window(
                        content=FormattedTextControl(self._get_help_text),
                        style="class:help.box",
                    ),
                    top=2,
                    bottom=2,
                    left=4,
                    right=4,
                    z_index=20,
                )
            floats.append(help_window)
        return floats

    def _create_keybindings(self):
        kb = KeyBindings()

        @kb.add("c-s")
        def handle_save(event):
            if self.filepath:
                self.save_file(self.filepath)
            else:
                self.prompt_mode = "writeout"
                self.prompt_text = "Save as:"
                self.prompt_buffer.text = "untitled.txt"
                self.prompt_buffer.cursor_position = len(self.prompt_buffer.text)
                self.layout.focus(self.prompt_buffer)

        @kb.add("c-g")
        def handle_help(event):
            self.show_help = not self.show_help
            self.layout.container.floats = self._get_floats()
            if not self.show_help:
                self.message = ""

        @kb.add("c-c")
        def handle_cursor_pos(event):
            doc = self.text_buffer.document
            row = doc.cursor_position_row + 1
            col = doc.cursor_position_col + 1
            total_rows = doc.line_count
            total_chars = len(doc.text)
            pct = int((row / max(1, total_rows)) * 100)
            self.message = f"[ line {row}/{total_rows} ({pct}%), col {col}, char {doc.cursor_position}/{total_chars} ]"

        @kb.add("c-k")
        def handle_cut(event):
            doc = self.text_buffer.document
            current_line = doc.current_line
            self.cut_buffer = current_line + "\n"
            # Delete current line
            start = doc.cursor_position - doc.cursor_position_col
            end = start + len(current_line)
            if end < len(doc.text) and doc.text[end] == "\n":
                end += 1
            # prompt_toolkit's Buffer has no delete_range method. Move the
            # cursor to the beginning of the line and delete the range from
            # there so Ctrl-K removes the complete current line.
            self.text_buffer.cursor_position = start
            self.text_buffer.delete(end - start)
            self.message = "[ Cut 1 line ]"

        @kb.add("c-u")
        def handle_paste(event):
            if self.cut_buffer:
                self.text_buffer.insert_text(self.cut_buffer)
                self.message = "[ Uncut (pasted) 1 line ]"
            else:
                self.message = "[ Cutbuffer is empty ]"

        @kb.add("c-o")
        def handle_writeout(event):
            default_path = self.filename if (self.filename and self.filename != "New Buffer") else "untitled.txt"
            self.prompt_mode = "writeout"
            self.prompt_text = "File Name to Write:"
            self.prompt_buffer.text = default_path
            self.prompt_buffer.cursor_position = len(default_path)
            self.layout.focus(self.prompt_buffer)

        @kb.add("c-x")
        def handle_exit(event):
            if self.show_help:
                self.show_help = False
                self.layout.container.floats = []
                return

            if self.prompt_mode:
                self.prompt_mode = None
                self.message = "[ Cancelled ]"
                self.layout.focus(self.text_buffer)
                return

            if self.is_modified():
                self.prompt_mode = "exit_confirm"
                self.prompt_text = "Save modified buffer? (Y)es, (N)o, (C)ancel: "
                self.prompt_buffer.text = ""
                self.layout.focus(self.prompt_buffer)
            else:
                event.app.exit(result=True)

        @kb.add("c-f")
        def handle_search(event):
            self.prompt_mode = "search"
            self.prompt_text = "Search:"
            self.prompt_buffer.text = ""
            self.layout.focus(self.prompt_buffer)

        @kb.add("tab", filter=Condition(lambda: bool(self.completion_words)))
        def handle_completion(event):
            self._accept_completion()

        @kb.add("c-r")
        def handle_read_file(event):
            self.prompt_mode = "read_file"
            self.prompt_text = "File to insert [from ./]:"
            self.prompt_buffer.text = ""
            self.layout.focus(self.prompt_buffer)

        @kb.add("c-_")
        def handle_goto_line(event):
            self.prompt_mode = "goto_line"
            self.prompt_text = "Enter line number, column number:"
            self.prompt_buffer.text = ""
            self.layout.focus(self.prompt_buffer)

        @kb.add("c-j")
        def handle_justify(event):
            self.message = "[ Justified paragraph ]"

        # Handle Enter inside Prompt Mode
        @kb.add("enter", filter=Condition(lambda: self.prompt_mode is not None))
        def handle_prompt_enter(event):
            val = self.prompt_buffer.text.strip()
            mode = self.prompt_mode
            self.prompt_mode = None
            self.layout.focus(self.text_buffer)

            if mode == "writeout":
                if val:
                    self.save_file(val)
                else:
                    self.message = "[ Cancelled ]"

            elif mode == "search":
                if val:
                    self.perform_search(val)
                else:
                    self.message = "[ Cancelled ]"

            elif mode == "goto_line":
                if val:
                    try:
                        line_num = int(val.split(",")[0].strip())
                        self.text_buffer.cursor_position = self.text_buffer.document.translate_row_col_to_index(
                            max(0, line_num - 1), 0
                        )
                        self.message = f"[ Jumped to line {line_num} ]"
                    except Exception:
                        self.message = "[ Invalid line number ]"

            elif mode == "read_file":
                if val and os.path.exists(val):
                    try:
                        with open(val, "r", encoding="utf-8", errors="replace") as f:
                            insert_content = f.read()
                        self.text_buffer.insert_text(insert_content)
                        lines = len(insert_content.splitlines())
                        self.message = f"[ Read {lines} line{'s' if lines != 1 else ''} from '{val}' ]"
                    except Exception as e:
                        self.message = f"[ Error reading '{val}': {e} ]"
                else:
                    self.message = f"[ File '{val}' not found ]"

        # Handle Y/N/C on Exit Confirmation Prompt
        @kb.add("y", filter=Condition(lambda: self.prompt_mode == "exit_confirm"))
        @kb.add("Y", filter=Condition(lambda: self.prompt_mode == "exit_confirm"))
        def handle_exit_yes(event):
            self.prompt_mode = None
            save_path = self.filepath or "untitled.txt"
            ok = self.save_file(save_path)
            if ok:
                event.app.exit(result=True)
            else:
                self.layout.focus(self.text_buffer)

        @kb.add("n", filter=Condition(lambda: self.prompt_mode == "exit_confirm"))
        @kb.add("N", filter=Condition(lambda: self.prompt_mode == "exit_confirm"))
        def handle_exit_no(event):
            self.prompt_mode = None
            event.app.exit(result=False)

        @kb.add("c", filter=Condition(lambda: self.prompt_mode == "exit_confirm"))
        @kb.add("C", filter=Condition(lambda: self.prompt_mode == "exit_confirm"))
        @kb.add("escape")
        def handle_cancel(event):
            if self.show_help:
                self.show_help = False
                self.layout.container.floats = self._get_floats()
                return
            self.prompt_mode = None
            self.message = "[ Cancelled ]"
            self.layout.focus(self.text_buffer)

        return kb

    def save_file(self, target_path: str) -> bool:
        try:
            path_obj = Path(target_path)
            if not path_obj.is_absolute():
                path_obj = Path(self.working_dir) / path_obj
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            with open(path_obj, "w", encoding="utf-8") as f:
                f.write(self.text_buffer.text)

            self.original_content = self.text_buffer.text
            self.filepath = str(path_obj)
            self.filename = path_obj.name
            self.language_extension = load_language_extension(self.filepath, self.extension_db_path)
            self.language = self.language_extension["language"] if self.language_extension else "Plain Text"
            self.completion_words = self.language_extension["completions"] if self.language_extension else []
            self.text_buffer.completer = self._make_completer()
            self.text_buffer.complete_while_typing = bool(self.completion_words)
            self.editor_control.lexer = self._get_lexer()
            lines = len(self.text_buffer.text.splitlines())
            self.message = f"[ Wrote {lines} line{'s' if lines != 1 else ''} to '{self.filename}' ]"
            return True
        except Exception as e:
            self.message = f"[ Error saving file: {e} ]"
            return False

    def perform_search(self, query: str):
        text = self.text_buffer.text
        cur_pos = self.text_buffer.cursor_position
        idx = text.lower().find(query.lower(), cur_pos + 1)
        if idx == -1:
            # Wrap around search
            idx = text.lower().find(query.lower(), 0)

        if idx != -1:
            self.text_buffer.cursor_position = idx
            self.message = f"[ Found match for '{query}' ]"
        else:
            self.message = f"[ '{query}' not found ]"

    def run(self):
        return self.app.run()


AtlasNanoEditor = OperatorCodeEditor


def main():
    target_file = sys.argv[1] if len(sys.argv) > 1 else None
    editor = AtlasNanoEditor(target_file)
    editor.run()


if __name__ == "__main__":
    main()
