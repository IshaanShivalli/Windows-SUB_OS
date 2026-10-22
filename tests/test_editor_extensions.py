import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from apps.nano import OperatorCodeEditor, VynLexer, load_language_extension
from packages import package_manager
from shell.opshell import AtlasCompleter, OperatorShellEngine


ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGE_REPO = ROOT_DIR / "packages" / "repo"


class EditorLanguageExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database = self.temp_path / "packages.sqlite"
        self.source_file = self.temp_path / "sample.py"
        self.source_file.write_text("", encoding="utf-8")
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE sys_packages (id TEXT PRIMARY KEY, name TEXT, version TEXT, "
                    "architecture TEXT, runtime TEXT, entrypoint TEXT, description TEXT, author TEXT, "
                    "installed_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT)"
                )
                connection.executemany(
                    "INSERT INTO sys_packages (id, name, version, runtime, entrypoint, status) "
                    "VALUES (?, ?, '1.0.0', 'python', 'apps/nano.py', 'active')",
                    [("core.shell", "Operator Shell"), ("app.editor", "Operator Code Editor")],
                )

    def install_extension(self, package_id, status="active"):
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    "INSERT OR REPLACE INTO sys_packages (id, status) VALUES (?, ?)",
                    (package_id, status),
                )

    def create_editor(self, filepath=None, new_buffer=False):
        with patch("apps.nano.Application", return_value=None):
            return OperatorCodeEditor(
                None if new_buffer else str(filepath or self.source_file),
                working_dir=str(self.temp_path),
                extension_db_path=self.database,
            )

    def test_save_as_activates_installed_language_extension(self):
        self.install_extension("editor.lang.python")
        editor = self.create_editor(new_buffer=True)
        self.assertFalse(editor.completion_words)

        self.assertTrue(editor.save_file("new_module.py"))
        self.assertEqual(editor.language, "Python")
        self.assertIn("print", editor.completion_words)
        self.assertIsNotNone(editor.text_buffer.completer)
        self.assertTrue(editor.text_buffer.complete_while_typing())

    def test_nano_shell_command_always_uses_operator_code_editor(self):
        file_path = self.temp_path / "sample.py"

        class Storage:
            def resolve_vpath(self, target, cwd, username):
                return file_path, str(file_path)

        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator", "SYS.CWD": "/Users/operator/home"}
        shell.storage = Storage()
        editor = unittest.mock.Mock()
        with patch("shell.opshell.OperatorCodeEditor", return_value=editor) as editor_type:
            shell.eval_command("nano sample.py")
        editor_type.assert_called_once_with(str(file_path), working_dir=str(self.temp_path))
        editor.run.assert_called_once_with()

    def test_shell_path_completion_preserves_selected_directory(self):
        class Storage:
            def normalize_vpath(self, path, cwd):
                return f"{cwd}/{path}"

            def virtual_listdir(self, path, cwd):
                self.listed_path = path
                return [{"name": "hello.txt", "is_dir": False}]

        storage = Storage()
        completer = AtlasCompleter([], lambda: "/Users/operator/home", storage)
        document = Document("nano Documents/", len("nano Documents/"))

        completion = next(completer.get_completions(document, CompleteEvent()))

        self.assertEqual(completion.text, "Documents/hello.txt")
        self.assertEqual(completion.start_position, -len("Documents/"))
        self.assertEqual(storage.listed_path, "/Users/operator/home/Documents")

    def test_powcurl_shell_command_runs_built_runtime_with_resolved_script(self):
        script_path = self.temp_path / "demo.powcurl"
        script_path.write_text('open "song.wav"\nplay\n', encoding="utf-8")
        binary = self.temp_path / "bin" / "powcurl.exe"
        binary.parent.mkdir()
        binary.write_bytes(b"runtime")

        class Storage:
            def resolve_vpath(self, target, cwd, username):
                return script_path, f"/Users/{username}/home/{target}"

        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator", "SYS.CWD": "/Users/operator/home"}
        shell.storage = Storage()
        with patch("shell.opshell.ROOT_DIR", self.temp_path), patch(
            "shell.opshell.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="Playback started", stderr=""),
        ) as run_runtime:
            result = shell.eval_command("powcurl demo.powcurl")

        self.assertEqual(result, "Playback started")
        run_runtime.assert_called_once_with(
            [str(binary), str(script_path)],
            cwd=str(self.temp_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_completion_is_disabled_until_matching_extension_is_installed(self):
        self.assertIsNone(load_language_extension(str(self.source_file), self.database))
        editor = self.create_editor()
        self.assertFalse(list(
            editor.text_buffer.completer.get_completions(
                Document("pri", 3),
                CompleteEvent(),
            )
        ))
        self.assertFalse(editor.completion_words)

        self.install_extension("editor.lang.python")
        extension = load_language_extension(str(self.source_file), self.database)
        self.assertEqual(extension["language"], "Python")

        editor = self.create_editor()
        self.assertIsNotNone(editor.text_buffer.completer)
        self.assertTrue(editor.text_buffer.complete_while_typing())
        self.assertTrue(editor.completion_words)
        completions = list(
            editor.text_buffer.completer.get_completions(
                Document("pri", 3),
                CompleteEvent(),
            )
        )
        self.assertIn("print", [completion.text for completion in completions])

    def test_python_completion_includes_user_symbols_and_contextual_builtin_members(self):
        self.install_extension("editor.lang.python")
        editor = self.create_editor()
        source = "def calculate_total(amount):\n    names = []\n    names.ap"
        function_completions = list(
            editor.text_buffer.completer.get_completions(
                Document("def calculate_total(amount):\n    cal", len("def calculate_total(amount):\n    cal")),
                CompleteEvent(),
            )
        )
        self.assertIn(
            "calculate_total",
            [completion.text for completion in function_completions],
        )
        completions = list(
            editor.text_buffer.completer.get_completions(
                Document(source, len(source)),
                CompleteEvent(),
            )
        )
        self.assertIn("append", [completion.text for completion in completions])

    def test_python_editor_reports_live_syntax_diagnostics(self):
        self.install_extension("editor.lang.python")
        editor = self.create_editor()

        editor.text_buffer.text = "def broken(:\n    pass"

        self.assertIn("line 1", editor.python_diagnostic)
        self.assertIn("Syntax error", "".join(text for _, text in editor._get_statusbar_text()[0:1]))

        editor.text_buffer.text = "def valid():\n    return 42\n"
        self.assertIsNone(editor.python_diagnostic)

    def test_editor_rendering_is_configured_for_immediate_shortcut_feedback(self):
        with patch("apps.nano.Application", return_value=None) as application:
            editor = OperatorCodeEditor(
                str(self.source_file),
                working_dir=str(self.temp_path),
                extension_db_path=self.database,
            )

        options = application.call_args.kwargs
        self.assertEqual(options["min_redraw_interval"], 0)
        self.assertEqual(options["max_render_postpone_time"], 0)
        self.assertEqual(options["terminal_size_polling_interval"], 1.0)
        self.assertFalse(editor.text_buffer.complete_while_typing())

    def test_editor_assigns_distinct_colors_to_syntax_token_categories(self):
        with patch("apps.nano.Application", return_value=None):
            editor = OperatorCodeEditor(
                str(self.source_file),
                working_dir=str(self.temp_path),
                extension_db_path=self.database,
            )

        colors = {
            category: editor.style.get_attrs_for_style_str(
                f"class:pygments.{category}"
            ).color
            for category in (
                "keyword",
                "name.builtin",
                "literal.string",
                "literal.number",
                "comment",
            )
        }

        self.assertEqual(len(set(colors.values())), len(colors))

    def test_inactive_or_nonmatching_extensions_do_not_enable_completions(self):
        self.install_extension("editor.lang.python", status="inactive")
        self.assertIsNone(load_language_extension(str(self.source_file), self.database))

        self.install_extension("editor.lang.javascript")
        self.assertIsNone(load_language_extension(str(self.source_file), self.database))

    def test_package_install_and_uninstall_control_completion_activation(self):
        manager = object.__new__(package_manager.PackageManager)
        manager.history_log = []
        with patch.object(package_manager, "DB_PATH", self.database):
            result = manager.install("editor.lang.python")
            self.assertIn("Installed", result)
            self.assertEqual(
                load_language_extension(str(self.source_file), self.database)["language"],
                "Python",
            )
            result = manager.uninstall("editor.lang.python")
        self.assertIn("uninstalled", result)
        self.assertIsNone(load_language_extension(str(self.source_file), self.database))

    def test_powcurl_and_batch_extensions_are_installable(self):
        manager = object.__new__(package_manager.PackageManager)
        manager.history_log = []
        with patch.object(package_manager, "DB_PATH", self.database):
            for package_id in ("editor.lang.powcurl", "editor.lang.batch"):
                with self.subTest(package=package_id):
                    self.assertIn("Installed", manager.install(package_id))
                    with closing(sqlite3.connect(self.database)) as connection:
                        row = connection.execute(
                            "SELECT status FROM sys_packages WHERE id = ?",
                            (package_id,),
                        ).fetchone()
                    self.assertEqual(row, ("active",))

    def test_vyn_extension_installs_completions_and_custom_syntax_lexer(self):
        vyn_file = self.temp_path / "sample.vyn"
        vyn_file.write_text('IF (ready) do\n  print("hello")\nend\n', encoding="utf-8")
        manager = object.__new__(package_manager.PackageManager)
        manager.history_log = []

        with patch.object(package_manager, "DB_PATH", self.database):
            result = manager.install("editor.lang.vyn")
        self.assertIn("Installed", result)

        extension = load_language_extension(str(vyn_file), self.database)
        self.assertEqual(extension["language"], "Vyn")
        self.assertIn("IF", extension["completions"])
        with patch("apps.nano.PygmentsLexer", return_value="vyn-lexer") as lexer_factory:
            editor = self.create_editor(filepath=vyn_file)
            self.assertEqual(editor._get_lexer(), "vyn-lexer")
            lexer_factory.assert_called_with(VynLexer)

    def test_vyn_completion_includes_symbols_declared_in_the_current_buffer(self):
        self.install_extension("editor.lang.vyn")
        vyn_file = self.temp_path / "sample.vyn"
        vyn_file.write_text("", encoding="utf-8")
        editor = self.create_editor(filepath=vyn_file)
        source = "function calculateTotal(a, b) perform\nendFunc\ncal"

        completions = list(
            editor.text_buffer.completer.get_completions(
                Document(source, len(source)),
                CompleteEvent(),
            )
        )

        self.assertIn("calculateTotal", [completion.text for completion in completions])

    def test_available_language_manifests_are_valid_and_installable(self):
        manifests = list(PACKAGE_REPO.glob("editor.lang.*.manifest.json"))
        self.assertGreaterEqual(len(manifests), 8)
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["id"].startswith("editor.lang."))
            self.assertEqual(manifest["runtime"], "editor-extension")
            extension = manifest["editor_extension"]
            self.assertTrue(extension["language"])
            self.assertTrue(extension["file_extensions"])
            self.assertTrue(extension["completions"])
            self.assertIn("app.editor", manifest["deps"])

    def test_requested_language_extensions_cover_their_file_types(self):
        expected = {
            "editor.lang.powcurl": ((".powcurl",), {"open", "play", "pause", "resume", "seek", "volume", "wait", "stop"}),
            "editor.lang.rust": ((".rs",), {"fn", "let", "match"}),
            "editor.lang.cpp": ((".cpp",), {"class", "namespace"}),
            "editor.lang.c": ((".c",), {"int", "struct"}),
            "editor.lang.powershell": ((".ps1",), {"function", "param"}),
            "editor.lang.batch": ((".bat", ".cmd"), {"echo", "if", "set"}),
            "editor.lang.vyn": ((".vyn",), {"IF", "function", "DOF"}),
        }
        for package_id, (suffixes, expected_words) in expected.items():
            with self.subTest(package=package_id):
                manifest_path = PACKAGE_REPO / f"{package_id}.manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                extension = manifest["editor_extension"]
                self.assertTrue(set(suffixes).issubset(extension["file_extensions"]))
                self.assertTrue(expected_words.intersection(extension["completions"]))

                self.install_extension(package_id)
                for suffix in suffixes:
                    source_path = self.temp_path / f"sample{suffix}"
                    source_path.write_text("", encoding="utf-8")
                    loaded = load_language_extension(str(source_path), self.database)
                    self.assertEqual(loaded["package_id"], package_id)
                    self.assertTrue(expected_words.intersection(loaded["completions"]))


if __name__ == "__main__":
    unittest.main()
