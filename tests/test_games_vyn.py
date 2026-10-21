import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.gpu.gpu_manager import GPUManager
from core.process import game_manager
from core.process.game_manager import GameManager, LOVE_RUNTIME_DLLS
from shell.opshell import OperatorShellEngine


class GameManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.games = self.root / "Games"
        self.games.mkdir()
        self.distributions = self.root / "CS50 2D"
        self.dist = self.distributions / "PONG" / "dist"
        self.dist.mkdir(parents=True)
        self.executable = self.games / "PONG.exe"
        self.executable.write_bytes(b"game")
        for name in LOVE_RUNTIME_DLLS:
            (self.dist / name).write_bytes(name.encode("ascii"))
        self.gpu = Mock()
        self.gpu.set_high_performance_preference.return_value = (
            "Windows high-performance GPU preference requested."
        )
        self.gpu.launch_command.return_value = SimpleNamespace(pid=7331, poll=lambda: None)
        self.manager = GameManager(self.gpu)

    def test_launch_stages_love_dlls_and_uses_gpu_aware_launcher(self):
        with patch.object(game_manager, "GAME_DISTRIBUTIONS_ROOT", self.distributions):
            result = self.manager.launch("PONG.exe", self.games, args=["--windowed"])

        self.assertIn("[GAME LAUNCHED] PONG (PID 7331)", result)
        self.assertIn("high-performance GPU", result)
        for name in LOVE_RUNTIME_DLLS:
            self.assertEqual((self.games / name).read_bytes(), name.encode("ascii"))
        self.gpu.set_high_performance_preference.assert_called_once_with(self.executable)
        self.gpu.launch_command.assert_called_once_with(
            str(self.executable),
            args=["--windowed"],
            cwd=self.games.resolve(),
        )
        self.assertEqual(self.manager.list_games(self.games)[0]["status"], "RUNNING")

    def test_launch_accepts_executable_names_with_spaces(self):
        executable = self.games / "MATCH 3.exe"
        executable.write_bytes(b"game")
        for name in LOVE_RUNTIME_DLLS:
            (self.games / name).write_bytes(name.encode("ascii"))

        result = self.manager.launch("MATCH 3.exe", self.games)

        self.assertIn("[GAME LAUNCHED] MATCH 3 (PID 7331)", result)
        self.gpu.launch_command.assert_called_once_with(
            str(executable),
            args=None,
            cwd=self.games.resolve(),
        )

    def test_launch_reports_missing_runtime_instead_of_starting_broken_game(self):
        (self.dist / "SDL2.dll").unlink()
        with (
            patch.object(game_manager, "GAME_DISTRIBUTIONS_ROOT", self.distributions),
            self.assertRaisesRegex(FileNotFoundError, "SDL2.dll"),
        ):
            self.manager.launch("PONG", self.games)
        self.gpu.launch_command.assert_not_called()

    def test_unknown_game_is_not_launched(self):
        with self.assertRaisesRegex(FileNotFoundError, "not found"):
            self.manager.launch("not-installed", self.games)
        self.gpu.launch_command.assert_not_called()

    def test_game_listing_marks_running_processes_and_clears_finished_processes(self):
        self.manager.active_games["pong"] = {
            "process": SimpleNamespace(poll=lambda: None),
        }
        self.assertEqual(self.manager.list_games(self.games)[0]["status"], "RUNNING")

        self.manager.active_games["pong"]["process"] = SimpleNamespace(poll=lambda: 0)
        self.assertEqual(self.manager.list_games(self.games)[0]["status"], "INSTALLED")
        self.assertNotIn("pong", self.manager.active_games)


class GPUPreferenceTests(unittest.TestCase):
    def test_sets_windows_high_performance_preference_per_executable(self):
        import sys

        registry = Mock()
        registry.HKEY_CURRENT_USER = object()
        registry.KEY_SET_VALUE = 2
        registry.REG_SZ = 1
        registry.CreateKeyEx.return_value = object()
        fake_os = SimpleNamespace(name="nt")
        with (
            patch("core.gpu.gpu_manager.os", fake_os),
            patch.dict(sys.modules, {"winreg": registry}),
        ):
            result = GPUManager.set_high_performance_preference(
                r"C:\Games\PONG.exe"
            )

        self.assertIn("requested", result)
        registry.SetValueEx.assert_called_once()
        self.assertEqual(registry.SetValueEx.call_args.args[1:], (
            r"C:\Games\PONG.exe",
            0,
            registry.REG_SZ,
            "GpuPreference=2;",
        ))
        registry.CloseKey.assert_called_once()


class GameAndVynShellTests(unittest.TestCase):
    def test_python_check_reports_syntax_without_running_the_script(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {
            "SYS.USER": "operator",
            "SYS.CWD": "/Users/operator/home",
        }
        shell.storage = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "invalid.py"
            source.write_text("def broken(:\n    pass\n", encoding="utf-8")
            shell.storage.resolve_vpath.return_value = (
                source,
                "/Users/operator/home/invalid.py",
            )
            result = shell.eval_command("python.check invalid.py")

        self.assertIn("[PYTHON SYNTAX ERROR]", result)
        self.assertIn("line 1", result)

    def test_python_run_uses_interpreter_arguments_and_reports_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "hello.py"
            source.write_text("print('hello')\n", encoding="utf-8")
            shell = OperatorShellEngine.__new__(OperatorShellEngine)
            shell.variables = {
                "SYS.USER": "operator",
                "SYS.CWD": "/Users/operator/home",
            }
            shell.storage = Mock()
            shell.storage.resolve_vpath.return_value = (
                source,
                "/Users/operator/home/hello.py",
            )
            with patch(
                "shell.opshell.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="hello\n", stderr=""),
            ) as run_python:
                result = shell.eval_command("python.run hello.py argument")

        self.assertEqual(result, "hello")
        self.assertEqual(
            run_python.call_args.args[0],
            [sys.executable, str(source.resolve()), "argument"],
        )
        self.assertEqual(run_python.call_args.kwargs["cwd"], str(source.parent))

    def test_games_launch_passes_quoted_game_name_and_arguments(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {
            "SYS.USER": "operator",
            "SYS.CWD": "/Users/operator/home",
        }
        shell.storage = Mock()
        shell.storage.resolve_vpath.return_value = (Path("C:/Games"), "/Games")
        shell.game_mgr = Mock()
        shell.game_mgr.launch.return_value = "[GAME LAUNCHED]"

        result = shell.eval_command('games.launch "MATCH 3.exe" --fullscreen')

        self.assertEqual(result, "[GAME LAUNCHED]")
        shell.game_mgr.launch.assert_called_once_with(
            "MATCH 3.exe",
            Path("C:/Games"),
            args=["--fullscreen"],
        )

    def test_vyn_run_invokes_the_supplied_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "vyn"
            runtime.mkdir()
            (runtime / "main.py").write_text("", encoding="utf-8")
            (runtime / "dependency.py").write_text("", encoding="utf-8")
            script = root / "hello.vyn"
            script.write_text('print("hello")', encoding="utf-8")
            shell = OperatorShellEngine.__new__(OperatorShellEngine)
            shell.variables = {
                "SYS.USER": "operator",
                "SYS.CWD": "/Users/operator/home",
            }
            shell.storage = Mock()
            shell.storage.resolve_vpath.return_value = (script, "/Users/operator/home/hello.vyn")
            with (
                patch("shell.opshell.VYN_RUNTIME_DIR", runtime),
                patch(
                    "shell.opshell.subprocess.run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout="hello",
                        stderr="",
                    ),
                ) as run_vyn,
            ):
                result = shell.eval_command("vyn.run hello.vyn")

        self.assertEqual(result, "hello")
        command = run_vyn.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "-c"])
        self.assertEqual(command[-1], str(script))
        self.assertEqual(run_vyn.call_args.kwargs["cwd"], str(runtime))

    def test_vyn_run_rejects_non_vyn_files(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        self.assertEqual(shell.eval_command("vyn.run script.py"), "Usage: vyn.run <file.vyn>")


if __name__ == "__main__":
    unittest.main()
