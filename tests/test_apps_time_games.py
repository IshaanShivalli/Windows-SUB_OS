import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.process import app_manager
from core.services.time_service import TimeService
from shell.opshell import OperatorShellEngine


class ApplicationManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.manifests = self.root / "manifests"
        self.sandboxes = self.root / "sandboxes"
        self.manifests.mkdir()
        (self.manifests / "app.calculator.json").write_text(
            json.dumps(
                {
                    "app_id": "app.calculator",
                    "name": "Calculator",
                    "runtime": "java",
                    "permissions": ["math"],
                    "exec_cmd": (
                        "java -cp runtime_java/bin "
                        "operator.runtime.OperatorRuntime calculator"
                    ),
                }
            ),
            encoding="utf-8",
        )
        self.manager = object.__new__(app_manager.ApplicationManager)
        self.manager.active_apps = {}

    def test_launch_uses_argument_list_and_inherits_console_output(self):
        process = Mock()
        process.pid = 1234
        process.poll.return_value = None
        process.wait.side_effect = app_manager.subprocess.TimeoutExpired("java", 0.15)
        with (
            patch.object(app_manager, "ROOT_DIR", self.root),
            patch.object(app_manager, "MANIFEST_DIR", self.manifests),
            patch.object(app_manager, "SANDBOX_DIR", self.sandboxes),
            patch.object(app_manager.subprocess, "Popen", return_value=process) as popen,
        ):
            result = self.manager.launch("Calculator")

        self.assertIn("[APP LAUNCHED]", result)
        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            [
                "java",
                "-cp",
                "runtime_java/bin",
                "operator.runtime.OperatorRuntime",
                "calculator",
            ],
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.root))
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertNotIn("stdout", popen.call_args.kwargs)
        self.assertEqual(self.manager.active_apps["app.calculator"]["pid"], 1234)

    def test_short_app_runs_report_completion_instead_of_stale_running_status(self):
        process = Mock()
        process.wait.return_value = 0
        with (
            patch.object(app_manager, "ROOT_DIR", self.root),
            patch.object(app_manager, "MANIFEST_DIR", self.manifests),
            patch.object(app_manager, "SANDBOX_DIR", self.sandboxes),
            patch.object(app_manager.subprocess, "Popen", return_value=process),
        ):
            result = self.manager.launch("app.calculator")

        self.assertIn("[APP COMPLETE]", result)
        self.assertEqual(self.manager.list_apps()[0]["status"], "INSTALLED")

    def test_missing_app_runtime_is_reported(self):
        with (
            patch.object(app_manager, "ROOT_DIR", self.root),
            patch.object(app_manager, "MANIFEST_DIR", self.manifests),
            patch.object(app_manager, "SANDBOX_DIR", self.sandboxes),
            patch.object(
                app_manager.subprocess,
                "Popen",
                side_effect=FileNotFoundError("java was not found"),
            ),
        ):
            result = self.manager.launch("Calculator")

        self.assertIn("Could not launch", result)
        self.assertIn("java was not found", result)


class TimeServiceTests(unittest.TestCase):
    def test_sync_uses_next_server_and_exposes_offset(self):
        service = TimeService(servers=("unavailable", "available"))
        with patch.object(
            service,
            "_query_server",
            side_effect=[OSError("unreachable"), 0.375],
        ):
            result = service.sync_now()

        self.assertIn("available", result)
        self.assertEqual(service.status()["offset_seconds"], 0.375)
        self.assertIsNotNone(service.status()["last_sync"])
        self.assertIsNone(service.status()["last_error"])

    def test_time_service_runs_and_stops_without_network(self):
        service = TimeService(servers=(), sync_interval=0.01)
        service.start()
        self.assertTrue(service.status()["running"])
        self.assertIn("failed", service.sync_now().lower())
        service.close()
        self.assertFalse(service.status()["running"])


class ShellAppAndGameCommandTests(unittest.TestCase):
    def test_semicolon_runs_multiple_commands_and_cd_updates_between_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "Users" / "operator" / "home"
            (home / "Documents").mkdir(parents=True)
            (home / "Games").mkdir()

            class Storage:
                def resolve_vpath(self, target, cwd, username):
                    if target.startswith("/"):
                        virtual_path = target
                    else:
                        virtual_path = str(Path(cwd) / target).replace("\\", "/")
                    normalized = []
                    for part in virtual_path.split("/"):
                        if part == "..":
                            if normalized:
                                normalized.pop()
                        elif part and part != ".":
                            normalized.append(part)
                    normalized_path = "/" + "/".join(normalized)
                    return root.joinpath(*normalized_path.strip("/").split("/")), normalized_path

            shell = OperatorShellEngine.__new__(OperatorShellEngine)
            shell.storage = Storage()
            shell.variables = {
                "SYS.USER": "operator",
                "SYS.CWD": "/Users/operator/home/Documents",
            }

            result = shell.eval_command("cd ..; cd Games")

            self.assertIsNone(result)
            self.assertEqual(shell.variables["SYS.CWD"], "/Users/operator/home/Games")

    def test_shell_quotes_escapes_and_windows_backslashes_are_preserved(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)

        result = shell.eval_command(
            r'''echo "first; value"; echo 'say \'hello\''; echo "C:\Users\Admin\Games\MATCH 3.exe"; echo escaped\ space; echo left\;right'''
        )

        self.assertEqual(
            result,
            "first; value\nsay 'hello'\nC:\\Users\\Admin\\Games\\MATCH 3.exe\nescaped space\nleft;right",
        )

    def test_unterminated_shell_quote_returns_syntax_error(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)

        result = shell.eval_command('echo "unfinished')

        self.assertIn("[SYNTAX ERROR]", result)
        self.assertIn("unterminated quoted string", result)

    def test_games_list_shows_executables_and_omits_license_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            games = Path(temporary)
            (games / "PONG.exe").write_bytes(b"game")
            (games / "My Game.exe").write_bytes(b"game")
            (games / "licenses").mkdir()

            class Storage:
                def resolve_vpath(self, target, cwd, username):
                    return games, target

            shell = OperatorShellEngine.__new__(OperatorShellEngine)
            shell.storage = Storage()
            shell.variables = {
                "SYS.USER": "operator",
                "SYS.CWD": "/Users/operator/home",
            }

            result = shell.eval_command("games.list")

        self.assertIn("PONG", result)
        self.assertIn("My Game.exe", result)
        self.assertNotIn("licenses", result)

    def test_app_launch_accepts_multiword_manifest_names(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.app_mgr = Mock()
        shell.app_mgr.launch.return_value = "[APP COMPLETE]"

        result = shell.eval_command("app.launch SysDiagnostics")

        self.assertEqual(result, "[APP COMPLETE]")
        shell.app_mgr.launch.assert_called_once_with("SysDiagnostics")

    def test_help_shows_topic_details_and_complete_feature_menu(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)

        topic_help = shell.eval_command("help games.list")
        menu_help = shell.eval_command("help menu")
        general_help = shell.eval_command("help ls")

        self.assertIn("List installed game executables", topic_help)
        self.assertIn("srv.register", menu_help)
        self.assertIn("time.service", menu_help)
        self.assertIn("No feature-specific help", general_help)

    def test_time_command_uses_time_service(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.time_service = Mock()
        shell.time_service.current_time.return_value = SimpleNamespace(
            strftime=lambda pattern: "Tuesday, October 20, 2026 11:30:00 PM IST"
        )
        shell.time_service.status.return_value = {
            "offset_seconds": 0.125,
            "last_sync": None,
            "last_error": None,
            "running": True,
        }

        result = shell.eval_command("time")

        self.assertIn("Tuesday, October 20, 2026", result)
        self.assertIn("NTP offset +0.125s", result)


if __name__ == "__main__":
    unittest.main()
