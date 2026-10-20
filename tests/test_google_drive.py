import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integrations.google_drive import DRIVE_SCOPE, GoogleDriveManager
from network.net_stack import OperatorNetworkStack
from shell.opshell import OperatorShellEngine


class GoogleDriveTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.mount = self.temp_path / "Users" / "operator" / "Google Drive"
        self.mount.mkdir(parents=True)
        self.storage = Mock()
        self.storage.resolve_vpath.side_effect = lambda path, cwd, user: (
            self.temp_path / "Users" / user / path.rsplit("/", 1)[-1],
            path,
        )
        self.network = Mock()
        self.manager = GoogleDriveManager(self.network, self.storage)
        self.manager._username = "operator"
        self.manager._mount_dir = self.mount
        self.manager._token = {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "client_id": "client.apps.googleusercontent.com",
            "scope": DRIVE_SCOPE,
            "expires_at": time.time() + 3600,
        }
        self.manager._service = Mock()

    def test_oauth_exchange_uses_operator_network_and_reports_http_errors(self):
        self.network.http_request.return_value = {
            "status_code": 200,
            "body": b'{"access_token":"access","refresh_token":"refresh","expires_in":3600}',
            "truncated": False,
        }
        token = self.manager._request_token({"grant_type": "authorization_code"})

        self.assertEqual(token["access_token"], "access")
        args, kwargs = self.network.http_request.call_args
        self.assertEqual(args[:2], ("POST", "https://oauth2.googleapis.com/token"))
        self.assertEqual(kwargs["data"], b"grant_type=authorization_code")

        self.network.http_request.return_value = {
            "status_code": 400,
            "body": b'{"error":"invalid_grant"}',
            "truncated": False,
        }
        with self.assertRaisesRegex(RuntimeError, "invalid_grant"):
            self.manager._request_token({"grant_type": "authorization_code"})

    def test_drive_download_sanitizes_filename_and_writes_into_user_mount(self):
        files = self.manager._service.files.return_value
        files.get.return_value.execute.return_value = {
            "id": "file-123",
            "name": "..\\..\\private.txt",
            "mimeType": "text/plain",
        }
        files.get_media.return_value = object()

        class Downloader:
            def __init__(self, destination, request):
                self.destination = destination

            def next_chunk(self):
                self.destination.write(b"drive contents")
                return None, True

        google_http = SimpleNamespace(MediaIoBaseDownload=Downloader)
        google_client = SimpleNamespace(http=google_http, __path__=[])
        with patch.dict(
            "sys.modules",
            {
                "googleapiclient": google_client,
                "googleapiclient.http": google_http,
            },
        ):
            downloaded = Path(self.manager.download_file("file-123"))

        self.assertEqual(downloaded.parent, self.mount)
        downloaded.resolve().relative_to(self.mount.resolve())
        self.assertEqual(downloaded.read_bytes(), b"drive contents")
        self.assertEqual(self.manager._index[downloaded.name]["file_id"], "file-123")

    def test_mount_prompts_for_client_id_and_mounts_the_current_user_folder(self):
        token_path = self.temp_path / "private" / "token.json"
        service = Mock()
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        credentials = object()
        self.manager._token_path = Mock(return_value=token_path)
        self.manager._authorize = Mock(return_value=self.manager._token.copy())
        self.manager._create_service = Mock(return_value=(credentials, service))
        self.manager._resolve_mount_dir = Mock(return_value=self.mount)

        with patch("integrations.google_drive.input", return_value="client.apps.googleusercontent.com", create=True), patch.object(
            self.manager, "_start_sync_worker"
        ):
            result = self.manager.mount_interactively(username="operator")

        self.assertIn("/Users/operator/Google Drive", result)
        self.manager._authorize.assert_called_once_with("client.apps.googleusercontent.com")
        self.assertTrue(token_path.is_file())
        self.assertNotIn("client_secret", token_path.read_text(encoding="utf-8"))
        self.assertTrue((self.mount / ".operator-drive-index.json").is_file())

    def test_mount_reauthorizes_tokens_with_an_old_narrow_drive_scope(self):
        token_path = self.temp_path / "private" / "token.json"
        token_path.parent.mkdir()
        token_path.write_text(
            json.dumps(
                {
                    **self.manager._token,
                    "scope": "https://www.googleapis.com/auth/drive.file",
                }
            ),
            encoding="utf-8",
        )
        service = Mock()
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        self.manager._token_path = Mock(return_value=token_path)
        self.manager._authorize = Mock(return_value=self.manager._token.copy())
        self.manager._create_service = Mock(return_value=(object(), service))
        self.manager._resolve_mount_dir = Mock(return_value=self.mount)

        with patch("integrations.google_drive.input", return_value="client.apps.googleusercontent.com", create=True), patch.object(
            self.manager, "_start_sync_worker"
        ):
            self.manager.mount_interactively(username="operator")

        self.manager._authorize.assert_called_once_with("client.apps.googleusercontent.com")

    def test_drive_mount_commands_cannot_access_a_different_users_account(self):
        with self.assertRaisesRegex(PermissionError, "different Operator OS user"):
            self.manager.list_files(username="root")
        with self.assertRaisesRegex(PermissionError, "different Operator OS user"):
            self.manager.download_file("file-123", username="root")
        with self.assertRaisesRegex(PermissionError, "different Operator OS user"):
            self.manager.upload_file(self.mount / "notes.txt", username="root")
        self.manager._service.files.assert_not_called()

    def test_write_unlock_hashes_local_passphrase_and_expires(self):
        policy = self.temp_path / "private" / "write.json"
        self.manager._write_policy_path = Mock(return_value=policy)
        with patch("integrations.google_drive.getpass.getpass", side_effect=["long-local-passphrase", "long-local-passphrase"]):
            message = self.manager.setup_write_passphrase()

        saved = json.loads(policy.read_text(encoding="utf-8"))
        self.assertNotIn("long-local-passphrase", policy.read_text(encoding="utf-8"))
        self.assertIn("3 hours", message)
        self.assertTrue(self.manager._is_write_unlocked())

        with patch("integrations.google_drive.getpass.getpass", return_value="wrong-passphrase"):
            with self.assertRaisesRegex(PermissionError, "Incorrect"):
                self.manager.unlock_writes()
        with patch("integrations.google_drive.getpass.getpass", return_value="long-local-passphrase"):
            self.manager.unlock_writes()
        self.assertTrue(self.manager._is_write_unlocked())

        self.manager._write_unlock_expires = time.monotonic() - 1
        self.assertFalse(self.manager._is_write_unlocked())
        self.assertIn("expired", self.manager._take_messages()[0])
        self.assertGreater(saved["iterations"], 100_000)

    def test_sync_uploads_changed_files_only_after_write_unlock(self):
        new_file = self.mount / "notes.txt"
        new_file.write_text("local edit", encoding="utf-8")
        self.manager._token = {**self.manager._token, "expires_at": time.time() + 3600}
        google_http = SimpleNamespace(MediaFileUpload=Mock())
        google_client = SimpleNamespace(http=google_http, __path__=[])
        with patch.dict(
            "sys.modules",
            {
                "googleapiclient": google_client,
                "googleapiclient.http": google_http,
            },
        ):
            self.manager._sync_pending_files()
            self.manager._service.files.return_value.create.return_value.execute.return_value = {
                "id": "remote-file"
            }
            self.manager._write_unlock_expires = time.monotonic() + 30
            self.manager._sync_pending_files()

        self.manager._service.files.return_value.create.assert_called_once()
        self.assertEqual(self.manager._index["notes.txt"]["file_id"], "remote-file")
        self.assertIn("Uploaded changed file: notes.txt", self.manager._take_messages())

    def test_shell_exposes_drive_mount_and_passes_current_user(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "ishaan"}
        shell.google_drive = Mock()
        shell.google_drive.mount_interactively.return_value = "Mounted"

        result = shell.eval_command("drive.mount")

        self.assertEqual(result, "Mounted")
        shell.google_drive.mount_interactively.assert_called_once_with(username="ishaan")

        shell.google_drive.mount_interactively.side_effect = RuntimeError("network offline")
        self.assertIn("network offline", shell.eval_command("drive.mount"))

    def test_network_stack_validates_oauth_http_requests(self):
        network = OperatorNetworkStack()
        with self.assertRaisesRegex(ValueError, "http or https"):
            network.http_request("POST", "file:///token")
        with self.assertRaisesRegex(ValueError, "Credentials"):
            network.http_request("GET", "https://user:password@example.com/")
        with self.assertRaisesRegex(ValueError, "Unsupported HTTP method"):
            network.http_request("TRACE", "https://example.com/")
        with patch.object(
            network,
            "http_request",
            return_value={"status_code": 403, "body": b"denied"},
        ):
            self.assertEqual(
                network.http_fetch("https://example.com/"),
                {"url": "https://example.com/", "error": "HTTP 403"},
            )


if __name__ == "__main__":
    unittest.main()
