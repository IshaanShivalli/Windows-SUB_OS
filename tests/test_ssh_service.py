import socket
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import posixpath

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from unittest.mock import Mock, patch

from network.ssh_service import OperatorSSHService
from shell.opshell import OperatorShellEngine


class FakeStorage:
    def __init__(self, root):
        self.root = root

    def get_os_root(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def resolve_vpath(self, vpath, cwd="/", current_user="operator"):
        if vpath == "~":
            vpath = f"/Users/{current_user}/home"
        elif vpath.startswith("~/"):
            vpath = f"/Users/{current_user}/home/{vpath[2:]}"
        if vpath.startswith("/"):
            normalized = posixpath.normpath(vpath)
        else:
            normalized = posixpath.normpath(posixpath.join(cwd, vpath))
        physical = self.root.joinpath(*normalized.lstrip("/").split("/"))
        return physical, normalized


class FakeUserManager:
    def get_user(self, username):
        return {"username": username} if username == "operator" else None


class FakeShell:
    def __init__(self, storage, username="operator"):
        self.storage = storage
        self.variables = {"SYS.USER": username, "SYS.CWD": f"/Users/{username}/home"}

    def eval_command(self, command):
        return f"Atlas command: {command}"


class SSHServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        private_key = Ed25519PrivateKey.generate()
        private_key_path = Path(self.temp_dir.name) / "client_ed25519"
        private_key_path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            )
        )
        self.private_key_path = private_key_path
        self.client_key = paramiko.Ed25519Key.from_private_key_file(str(private_key_path))
        self.public_key = f"{self.client_key.get_name()} {self.client_key.get_base64()}"
        self.storage = FakeStorage(Path(self.temp_dir.name) / "operator_os_root")
        self.service = OperatorSSHService(
            self.storage,
            FakeUserManager(),
            lambda username: FakeShell(self.storage, username),
        )
        self.addCleanup(self.service.stop)

    def _connect(self, port):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            "127.0.0.1",
            port=port,
            username="operator",
            pkey=self.client_key,
            allow_agent=False,
            look_for_keys=False,
            timeout=5,
            banner_timeout=5,
            auth_timeout=5,
        )
        self.addCleanup(client.close)
        return client

    def test_public_key_can_be_enrolled_and_revoked_by_fingerprint(self):
        fingerprint = self.service.add_authorized_key("operator", self.public_key)

        self.assertEqual(self.service.list_authorized_keys("operator"), [fingerprint])
        self.assertTrue(self.service.remove_authorized_key("operator", fingerprint))
        self.assertEqual(self.service.list_authorized_keys("operator"), [])

    def test_only_ed25519_keys_for_existing_users_can_be_enrolled(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.service.add_authorized_key("missing", self.public_key)
        with self.assertRaisesRegex(ValueError, "Ed25519"):
            self.service.add_authorized_key("operator", "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ==")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.service.add_authorized_key(
                "operator",
                f"{self.public_key}\n{self.public_key}",
            )

    def test_loopback_server_runs_atlas_commands_and_rejects_host_commands(self):
        self.service.add_authorized_key("operator", self.public_key)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
            port_probe.bind(("127.0.0.1", 0))
            port = port_probe.getsockname()[1]
        self.service.start(port=port)
        self.assertIn("running", self.service.status())

        client = self._connect(port)
        _, stdout, _ = client.exec_command("echo hello")
        self.assertEqual(stdout.read().decode("utf-8").strip(), "Atlas command: echo hello")

        client.close()
        client = self._connect(port)
        _, stdout, _ = client.exec_command("python -c print(1)")
        self.assertIn("not available remotely", stdout.read().decode("utf-8"))
        self.assertEqual(stdout.channel.recv_exit_status(), 126)

        client.close()
        client = self._connect(port)
        _, stdout, _ = client.exec_command("cat /Users/root/home/secret.txt")
        self.assertIn("confined to the authenticated user's home", stdout.read().decode("utf-8"))
        self.assertEqual(stdout.channel.recv_exit_status(), 1)

    def test_native_openssh_client_can_connect_to_atlas_server(self):
        ssh_executable = shutil.which("ssh")
        ssh_keygen = shutil.which("ssh-keygen")
        if not ssh_executable or not ssh_keygen:
            self.skipTest("OpenSSH client and key generator are required")
        private_key_path = Path(self.temp_dir.name) / "openssh_client_key"
        subprocess.run(
            [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(private_key_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        public_key = private_key_path.with_suffix(".pub").read_text(encoding="utf-8")
        self.service.add_authorized_key("operator", public_key)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
            port_probe.bind(("127.0.0.1", 0))
            port = port_probe.getsockname()[1]
        self.service.start(port=port)

        result = subprocess.run(
            [
                ssh_executable,
                "-T",
                "-p", str(port),
                "-i", str(private_key_path),
                "-o", "IdentitiesOnly=yes",
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"UserKnownHostsFile={self.temp_dir.name}\\known_hosts",
                "-o", "LogLevel=ERROR",
                "operator@127.0.0.1",
                "echo hello",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Atlas command: echo hello", result.stdout)

    def test_server_requires_enrolled_keys_and_valid_bind_address(self):
        with self.assertRaisesRegex(ValueError, "Enroll"):
            self.service.start()
        self.service.add_authorized_key("operator", self.public_key)
        with self.assertRaisesRegex(ValueError, "IPv4"):
            self.service.start(host="example.com")

    def test_shell_ssh_client_uses_native_openssh_without_a_shell(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {"SYS.USER": "operator"}
        completed = Mock(returncode=0)
        with patch("shell.opshell.shutil.which", return_value="C:\\Windows\\ssh.exe"), patch(
            "shell.opshell.subprocess.run", return_value=completed
        ) as run:
            result = shell.eval_command("ssh -p 2222 operator@127.0.0.1")

        self.assertIsNone(result)
        run.assert_called_once_with(
            ["C:\\Windows\\ssh.exe", "-p", "2222", "operator@127.0.0.1"],
            check=False,
        )

    def test_key_add_accepts_an_absolute_host_public_key_path(self):
        with tempfile.TemporaryDirectory() as directory:
            public_key_path = Path(directory) / "atlas.pub"
            public_key_path.write_text(self.public_key, encoding="utf-8")
            shell = OperatorShellEngine.__new__(OperatorShellEngine)
            shell.variables = {
                "SYS.USER": "operator",
                "SYS.CWD": "/Users/operator/home",
            }
            shell.storage = Mock()
            shell.ssh_service = Mock()
            shell.ssh_service.add_authorized_key.return_value = "fingerprint"

            result = shell.eval_command(
                f'ssh.key.add operator "{public_key_path.as_posix()}"'
            )

        self.assertIn("Fingerprint: fingerprint", result)
        shell.storage.resolve_vpath.assert_not_called()
        shell.ssh_service.add_authorized_key.assert_called_once_with("operator", self.public_key)


if __name__ == "__main__":
    unittest.main()
