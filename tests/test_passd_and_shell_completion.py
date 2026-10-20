import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from core.security import user_manager
from core.security.security_manager import SecurityManager
from shell.opshell import AtlasCompleter, OperatorShellEngine


class PassdAndCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "auth.sqlite"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "CREATE TABLE sys_passd_auth (username TEXT PRIMARY KEY, pass_hash TEXT, salt TEXT, iterations INTEGER)"
            )

    def test_fresh_system_schema_includes_passd_auth_table(self):
        schema_path = Path(__file__).resolve().parents[1] / "db" / "init_schema.sql"
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sys_passd_auth'"
            ).fetchone()

        self.assertEqual(table, ("sys_passd_auth",))

    def test_passd_password_uses_salted_hash_and_verifies(self):
        class Manager:
            PASSD_HASH_ITERATIONS = user_manager.UserManager.PASSD_HASH_ITERATIONS
            _validate_passd_password = staticmethod(user_manager.UserManager._validate_passd_password)
            _hash_passd_password = staticmethod(user_manager.UserManager._hash_passd_password)
            has_passd_password = user_manager.UserManager.has_passd_password
            set_passd_password = user_manager.UserManager.set_passd_password
            verify_passd_password = user_manager.UserManager.verify_passd_password

        manager = Manager()
        with patch.object(user_manager, "DB_PATH", self.database):
            manager.set_passd_password("operator", "correct horse battery staple")
            self.assertTrue(manager.has_passd_password("operator"))
            self.assertTrue(manager.verify_passd_password("operator", "correct horse battery staple"))
            self.assertFalse(manager.verify_passd_password("operator", "wrong password"))
            with self.assertRaisesRegex(ValueError, "at least 8 characters"):
                manager.set_passd_password("operator", "short")

        with closing(sqlite3.connect(self.database)) as connection:
            pass_hash, salt = connection.execute(
                "SELECT pass_hash, salt FROM sys_passd_auth WHERE username = 'operator'"
            ).fetchone()
        self.assertNotEqual(pass_hash, "correct horse battery staple")
        self.assertNotEqual(salt, "OP_SEC_SALT_2026")
        self.assertEqual(len(salt), 32)

    def test_account_password_is_not_replaced_when_security_manager_starts(self):
        database = self.database
        with closing(sqlite3.connect(database)) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE sys_auth (username TEXT PRIMARY KEY, pass_hash TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO sys_auth VALUES ('operator', 'custom-hash', 'user', 'custom-salt')"
                )

        class FakeSecurityManager:
            secrets_vault = {}
            hash_password = SecurityManager.hash_password
            store_secret = SecurityManager.store_secret

        manager = FakeSecurityManager()
        with patch("core.security.security_manager.DB_PATH", database):
            SecurityManager.seed_users_and_secrets(manager)

        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                "SELECT pass_hash, salt FROM sys_auth WHERE username = 'operator'"
            ).fetchone()
        self.assertEqual(row, ("custom-hash", "custom-salt"))

    def test_first_passd_command_sets_a_dedicated_password_then_runs(self):
        class PassdManager:
            def __init__(self):
                self.password = None

            def has_passd_password(self, username):
                return self.password is not None

            def set_passd_password(self, username, password):
                self.password = password

        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        shell._passd_auth_cache = {}
        shell.user_mgr = PassdManager()
        with patch("shell.opshell.sys.stdin.isatty", return_value=True), patch(
            "getpass.getpass",
            side_effect=["a-strong-passd-password", "a-strong-passd-password"],
        ), patch.object(shell, "eval_command", wraps=shell.eval_command) as evaluate:
            result = shell.eval_command("passd true")

        self.assertIsNone(result)
        self.assertEqual(shell.user_mgr.password, "a-strong-passd-password")
        self.assertEqual(shell.variables["SYS.USER"], "operator")
        self.assertNotIn("SYS.PASSD_ACTIVE", shell.variables)
        self.assertEqual(evaluate.call_args.args[0], "true")

    def test_passd_requests_three_attempts_and_does_not_run_on_failure(self):
        manager = Mock()
        manager.has_passd_password.return_value = True
        manager.verify_passd_password.return_value = False
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        shell._passd_auth_cache = {}
        shell.user_mgr = manager

        with patch("shell.opshell.sys.stdin.isatty", return_value=True), patch(
            "getpass.getpass",
            side_effect=["wrong-one", "wrong-two", "wrong-three"],
        ), patch.object(shell, "eval_command", wraps=shell.eval_command) as evaluate:
            result = shell.eval_command("passd true")

        self.assertIn("Three incorrect", result)
        manager.verify_passd_password.assert_any_call("operator", "wrong-three")
        self.assertEqual(manager.verify_passd_password.call_count, 3)
        self.assertEqual(evaluate.call_count, 1)

    def test_passd_subcommand_completes_after_multiple_words(self):
        completer = AtlasCompleter(
            ["help", "passd", "passd.setup", "shutdown", "show", "user.list"],
            lambda: "/Users/operator/home",
            Mock(),
        )
        document = Document("passd sh", len("passd sh"))
        completions = list(completer.get_completions(document, CompleteEvent()))

        self.assertEqual([completion.text for completion in completions], ["show", "shutdown"])
        self.assertTrue(all(completion.start_position == -2 for completion in completions))

    def test_passd_setup_is_suggested_from_a_short_prefix(self):
        completer = AtlasCompleter(
            ["passd", "passd.setup", "shutdown", "show"],
            lambda: "/Users/operator/home",
            Mock(),
        )
        document = Document("passd s", len("passd s"))
        completions = list(completer.get_completions(document, CompleteEvent()))

        self.assertIn("setup", [completion.text for completion in completions])
        self.assertIn("shutdown", [completion.text for completion in completions])

    def test_passd_target_command_completes_after_user_option(self):
        completer = AtlasCompleter(
            ["help", "passd", "shutdown", "show"],
            lambda: "/Users/operator/home",
            Mock(),
        )
        document = Document("passd -u operator sh", len("passd -u operator sh"))
        completions = list(completer.get_completions(document, CompleteEvent()))

        self.assertEqual([completion.text for completion in completions], ["show", "shutdown"])
        self.assertTrue(all(completion.start_position == -2 for completion in completions))

    def test_ssh_server_subcommands_complete_after_multiple_words(self):
        completer = AtlasCompleter(
            ["ssh", "ssh.server", "ssh.key.add"],
            lambda: "/Users/operator/home",
            Mock(),
        )
        document = Document("ssh.server st", len("ssh.server st"))
        completions = list(completer.get_completions(document, CompleteEvent()))

        self.assertEqual([completion.text for completion in completions], ["start", "status", "stop"])


if __name__ == "__main__":
    unittest.main()
