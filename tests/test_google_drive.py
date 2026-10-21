import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integrations.rclone_drive import RcloneDriveManager
from shell.opshell import OperatorShellEngine


class RcloneDriveTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.mount = self.temp_path / "Users" / "operator" / "Google Drive"
        self.mount.mkdir(parents=True)
        self.storage = Mock()
        self.storage.resolve_vpath.side_effect = lambda path, cwd, user: (
            self.temp_path / "Users" / user / "Google Drive",
            path,
        )
        self.manager = RcloneDriveManager(storage=self.storage)
        self.manager._username = "operator"
        self.manager._mount_dir = self.mount
        self.manager._config_path = self.temp_path / "private" / "rclone.conf"
        self.manager._config_path.parent.mkdir(parents=True)
        self.manager._config_path.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
        self.manager._remote = "gdrive"

    def test_mount_uses_existing_rclone_remote_and_checks_connectivity(self):
        self.manager._config_path_for = Mock(return_value=self.manager._config_path)
        self.manager._resolve_mount_dir = Mock(return_value=self.mount)
        with (
            patch("integrations.rclone_drive.shutil.which", return_value="rclone.exe"),
            patch.object(self.manager, "_run_rclone") as run_rclone,
            patch.object(self.manager, "_start_sync_worker"),
        ):
            run_rclone.side_effect = [
                SimpleNamespace(stdout="gdrive:\n"),
                SimpleNamespace(stdout="[]"),
            ]
            result = self.manager.mount_interactively(username="operator")

        self.assertIn("rclone remote 'gdrive'", result)
        self.assertEqual(self.manager._remote, "gdrive")
        self.assertEqual(run_rclone.call_args_list[0].args[1:], ("listremotes",))
        self.assertEqual(run_rclone.call_args_list[1].args[1:], ("lsjson", "gdrive:"))

    def test_mount_runs_rclone_setup_when_no_remote_exists(self):
        self.manager._config_path_for = Mock(return_value=self.manager._config_path)
        self.manager._resolve_mount_dir = Mock(return_value=self.mount)
        with (
            patch("integrations.rclone_drive.shutil.which", return_value="rclone.exe"),
            patch("integrations.rclone_drive.subprocess.run") as run_process,
            patch.object(self.manager, "_run_rclone") as run_rclone,
            patch.object(self.manager, "_start_sync_worker"),
        ):
            run_process.return_value = SimpleNamespace(returncode=0)
            run_rclone.side_effect = [
                SimpleNamespace(stdout=""),
                SimpleNamespace(stdout="gdrive:\n"),
                SimpleNamespace(stdout="[]"),
            ]
            self.manager.mount_interactively(username="operator")

        self.assertEqual(
            run_process.call_args.args[0][:3],
            ["rclone.exe", "--config", str(self.manager._config_path)],
        )
        self.assertEqual(run_process.call_args.args[0][-1], "config")
        self.assertIn("--config", run_process.call_args.args[0])
        self.assertEqual(self.manager._read_remote("operator"), "gdrive")

    def test_lists_remote_entries_as_drive_file_records(self):
        self.manager._run_rclone = Mock(
            return_value=SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "ID": "remote-id",
                            "Path": "Reports/annual.pdf",
                            "Name": "annual.pdf",
                            "MimeType": "application/pdf",
                            "Size": 1234,
                            "ModTime": "2026-01-01T00:00:00Z",
                        }
                    ]
                )
            )
        )

        with patch.object(self.manager, "_find_rclone", return_value="rclone.exe"):
            entries = self.manager.list_files("Reports", username="operator")

        self.assertEqual(
            entries,
            [
                {
                    "id": "remote-id",
                    "name": "annual.pdf",
                    "mimeType": "application/pdf",
                    "size": 1234,
                    "modifiedTime": "2026-01-01T00:00:00Z",
                }
            ],
        )
        self.manager._run_rclone.assert_called_once()
        self.assertIn("gdrive:Reports", self.manager._run_rclone.call_args.args)

    def test_download_resolves_rclone_id_and_sanitizes_local_filename(self):
        def run_rclone(executable, *arguments, config_path):
            if arguments[0] == "lsjson":
                return SimpleNamespace(
                    stdout=json.dumps(
                        [{"ID": "remote-id", "Path": "Reports/annual.pdf", "IsDir": False}]
                    )
                )
            self.assertEqual(arguments[0], "copyto")
            Path(arguments[2]).write_bytes(b"remote data")
            return SimpleNamespace(stdout="")

        self.manager._run_rclone = Mock(side_effect=run_rclone)

        with patch.object(self.manager, "_find_rclone", return_value="rclone.exe"):
            downloaded = Path(self.manager.download_file("remote-id", username="operator"))

        self.assertEqual(downloaded.parent, self.mount)
        self.assertEqual(downloaded.name, "annual.pdf")
        self.assertEqual(downloaded.read_bytes(), b"remote data")
        self.assertIn("annual.pdf", self.manager._index)

    def test_remote_paths_reject_absolute_and_parent_traversal(self):
        self.manager._run_rclone = Mock()
        for invalid_path in ("/private.txt", "C:\\private.txt", "../private.txt"):
            with self.subTest(path=invalid_path), self.assertRaises(ValueError):
                self.manager.list_files(invalid_path, username="operator")
        self.manager._run_rclone.assert_not_called()

    def test_drive_mount_commands_cannot_access_a_different_users_account(self):
        with self.assertRaisesRegex(PermissionError, "different Operator OS user"):
            self.manager.list_files(username="root")
        with self.assertRaisesRegex(PermissionError, "different Operator OS user"):
            self.manager.download_file("remote-id", username="root")
        with self.assertRaisesRegex(PermissionError, "different Operator OS user"):
            self.manager.upload_file(self.mount / "notes.txt", username="root")

    def test_write_unlock_hashes_local_passphrase_and_expires(self):
        policy = self.temp_path / "private" / "write.json"
        self.manager._write_policy_path = Mock(return_value=policy)
        with patch(
            "integrations.rclone_drive.getpass.getpass",
            side_effect=["long-local-passphrase", "long-local-passphrase"],
        ):
            message = self.manager.setup_write_passphrase()

        saved = json.loads(policy.read_text(encoding="utf-8"))
        self.assertNotIn("long-local-passphrase", policy.read_text(encoding="utf-8"))
        self.assertIn("3 hours", message)
        self.assertTrue(self.manager._is_write_unlocked())

        with patch(
            "integrations.rclone_drive.getpass.getpass",
            return_value="wrong-passphrase",
        ):
            with self.assertRaisesRegex(PermissionError, "Incorrect"):
                self.manager.unlock_writes()
        with patch(
            "integrations.rclone_drive.getpass.getpass",
            return_value="long-local-passphrase",
        ):
            self.manager.unlock_writes()
        self.assertTrue(self.manager._is_write_unlocked())

        self.manager._write_unlock_expires = time.monotonic() - 1
        self.assertFalse(self.manager._is_write_unlocked())
        self.assertIn("expired", self.manager._take_messages()[0])
        self.assertGreater(saved["iterations"], 100_000)

    def test_sync_uploads_changed_files_only_after_write_unlock(self):
        new_file = self.mount / "notes.txt"
        new_file.write_text("local edit", encoding="utf-8")
        self.manager._run_rclone = Mock(return_value=SimpleNamespace(stdout=""))
        with patch("integrations.rclone_drive.shutil.which", return_value="rclone.exe"):
            self.manager._sync_pending_files()
            self.manager._write_unlock_expires = time.monotonic() + 30
            self.manager._sync_pending_files()

        self.manager._run_rclone.assert_called_once()
        self.assertEqual(self.manager._run_rclone.call_args.args[1:4], (
            "copyto",
            str(new_file),
            "gdrive:notes.txt",
        ))
        self.assertIn("Uploaded changed file: notes.txt", self.manager._take_messages())

    def test_shell_exposes_rclone_mount_and_passes_current_user(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "ishaan"}
        shell.google_drive = Mock()
        shell.google_drive.mount_interactively.return_value = "Mounted"

        result = shell.eval_command("drive.mount")

        self.assertEqual(result, "Mounted")
        shell.google_drive.mount_interactively.assert_called_once_with(username="ishaan")

        shell.google_drive.mount_interactively.side_effect = RuntimeError("rclone missing")
        self.assertIn("rclone missing", shell.eval_command("drive.mount"))

    def test_cancelling_drive_connection_keeps_shell_available(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "ishaan"}
        shell.google_drive = Mock()
        shell.google_drive.mount_interactively.side_effect = KeyboardInterrupt

        result = shell.eval_command("drive.connect")

        self.assertIn("cancelled", result.lower())
        self.assertIn("still running", result.lower())


if __name__ == "__main__":
    unittest.main()
