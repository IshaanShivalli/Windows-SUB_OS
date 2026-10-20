import base64
import hashlib
import ipaddress
import logging
import posixpath
import socket
import threading
from typing import Callable

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


logger = logging.getLogger(__name__)


class _AtlasSSHSession(paramiko.ServerInterface):
    def __init__(self, service):
        self.service = service
        self.username = None
        self.command = None
        self.shell_requested = False
        self.request_event = threading.Event()

    def get_allowed_auths(self, _username):
        return "publickey"

    def check_auth_publickey(self, username, key):
        if self.service.is_authorized_key(username, key):
            self.username = username
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, _chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(
        self, _channel, _term, _width, _height, _pixelwidth, _pixelheight, _modes
    ):
        return True

    def check_channel_shell_request(self, _channel):
        self.shell_requested = True
        self.request_event.set()
        return True

    def check_channel_exec_request(self, _channel, command):
        self.command = command.decode("utf-8", errors="replace")
        self.request_event.set()
        return True


class OperatorSSHService:
    REMOTE_COMMANDS = {
        "cat", "cd", "date", "df", "echo", "false", "free", "gpu.probe", "hostname",
        "id", "la", "ll", "ls", "mem", "mkdir", "net.ifconfig", "net.resolve",
        "net.routes", "pwd", "storage.inspect", "sys.probe", "touch", "true", "uname",
        "uptime", "user.whoami", "whoami",
    }
    REMOTE_PATH_COMMANDS = {"cat", "cd", "la", "ll", "ls", "mkdir", "touch"}

    def __init__(self, storage, user_manager, shell_factory: Callable):
        self.storage = storage
        self.user_manager = user_manager
        self.shell_factory = shell_factory
        self.ssh_root = self.storage.get_os_root() / "etc" / "ssh"
        self.authorized_keys_dir = self.ssh_root / "authorized_keys"
        self.host_key_path = self.ssh_root / "host_ed25519_key"
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._listener = None
        self._thread = None
        self._transports = set()
        self._client_slots = threading.BoundedSemaphore(8)
        self._host_key = None
        self.host = None
        self.port = None
        self.last_error = None

    @staticmethod
    def _normalize_username(username):
        normalized = username.strip().lower()
        if not normalized or not normalized.isalnum():
            raise ValueError("Atlas SSH usernames must be alphanumeric")
        return normalized

    def _user_exists(self, username):
        try:
            return self.user_manager.get_user(username) is not None
        except (KeyError, ValueError):
            return False

    @staticmethod
    def _parse_public_key(public_key):
        lines = [line.strip() for line in public_key.splitlines() if line.strip()]
        if len(lines) != 1:
            raise ValueError("Provide exactly one OpenSSH public key per command")
        parts = lines[0].split()
        if len(parts) < 2 or parts[0] != "ssh-ed25519":
            raise ValueError("Only OpenSSH Ed25519 public keys are supported")
        try:
            key_data = base64.b64decode(parts[1], validate=True)
            key = paramiko.Ed25519Key(data=key_data)
        except (ValueError, TypeError, paramiko.SSHException) as exc:
            raise ValueError("Invalid Ed25519 public key") from exc
        return key

    def _key_file(self, username):
        return self.authorized_keys_dir / f"{self._normalize_username(username)}.pub"

    @staticmethod
    def _key_fingerprint(key):
        digest = hashlib.sha256(key.asbytes()).digest()
        encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
        return f"SHA256:{encoded}"

    def add_authorized_key(self, username, public_key):
        username = self._normalize_username(username)
        if not self._user_exists(username):
            raise ValueError(f"Atlas user '{username}' does not exist")
        key = self._parse_public_key(public_key)
        self.authorized_keys_dir.mkdir(parents=True, exist_ok=True)
        key_file = self._key_file(username)
        canonical_key = f"{key.get_name()} {key.get_base64()}"
        existing = key_file.read_text(encoding="utf-8").splitlines() if key_file.exists() else []
        if canonical_key not in existing:
            with key_file.open("a", encoding="utf-8", newline="\n") as key_stream:
                key_stream.write(canonical_key + "\n")
        return self._key_fingerprint(key)

    def list_authorized_keys(self, username):
        key_file = self._key_file(username)
        if not key_file.exists():
            return []
        fingerprints = []
        for line in key_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                fingerprints.append(self._key_fingerprint(self._parse_public_key(line)))
        return fingerprints

    def remove_authorized_key(self, username, fingerprint):
        key_file = self._key_file(username)
        if not key_file.exists():
            return False
        lines = key_file.read_text(encoding="utf-8").splitlines()
        retained = [
            line for line in lines
            if not line.strip()
            or self._key_fingerprint(self._parse_public_key(line)).lower() != fingerprint.lower()
        ]
        if len(retained) == len(lines):
            return False
        if retained:
            key_file.write_text("\n".join(retained) + "\n", encoding="utf-8")
        else:
            key_file.unlink()
        return True

    def is_authorized_key(self, username, key):
        try:
            username = self._normalize_username(username)
            if key.get_name() != "ssh-ed25519" or not self._user_exists(username):
                return False
            return self._key_fingerprint(key) in self.list_authorized_keys(username)
        except (OSError, ValueError):
            logger.exception("Could not validate an SSH public key")
            return False

    def _load_or_create_host_key(self):
        self.ssh_root.mkdir(parents=True, exist_ok=True)
        if not self.host_key_path.exists():
            private_key = Ed25519PrivateKey.generate()
            self.host_key_path.write_bytes(
                private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.OpenSSH,
                    serialization.NoEncryption(),
                )
            )
            self.host_key_path.chmod(0o600)
        return paramiko.Ed25519Key.from_private_key_file(str(self.host_key_path))

    def start(self, host="127.0.0.1", port=2222):
        try:
            address = str(ipaddress.IPv4Address(host))
        except ipaddress.AddressValueError as exc:
            raise ValueError("SSH bind address must be an IPv4 address") from exc
        if not 1 <= int(port) <= 65535:
            raise ValueError("SSH port must be between 1 and 65535")
        if not any(self.authorized_keys_dir.glob("*.pub")):
            raise ValueError("Enroll an Atlas user's Ed25519 key before starting the SSH server")

        with self._lock:
            if self._thread and self._thread.is_alive():
                return f"Atlas SSH server is already running on {self.host}:{self.port}."
            host_key = self._load_or_create_host_key()
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((address, int(port)))
                listener.listen(16)
                listener.settimeout(0.5)
            except OSError:
                listener.close()
                raise
            self._stop_event.clear()
            self._listener = listener
            self._host_key = host_key
            self.host = address
            self.port = int(port)
            self.last_error = None
            self._thread = threading.Thread(target=self._serve, name="atlas-ssh", daemon=True)
            self._thread.start()
        return f"Atlas SSH server listening on {self.host}:{self.port} (Ed25519 keys only)."

    def stop(self):
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                return "Atlas SSH server is not running."
            self._stop_event.set()
            listener = self._listener
            transports = list(self._transports)
        if listener:
            listener.close()
        for transport in transports:
            transport.close()
        self._thread.join(timeout=3)
        return "Atlas SSH server stopped."

    def status(self):
        running = bool(self._thread and self._thread.is_alive())
        state = f"running on {self.host}:{self.port}" if running else "stopped"
        if self.last_error:
            state += f"\nLast server error: {self.last_error}"
        return f"Atlas SSH server: {state}"

    def _serve(self):
        while not self._stop_event.is_set():
            try:
                client, address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    self.last_error = "SSH listener stopped unexpectedly"
                    logger.exception("Atlas SSH listener failed")
                break
            if not self._client_slots.acquire(blocking=False):
                client.close()
                continue
            thread = threading.Thread(
                target=self._handle_client,
                args=(client, address),
                name="atlas-ssh-client",
                daemon=True,
            )
            thread.start()
        with self._lock:
            self._listener = None

    def _handle_client(self, client, address):
        transport = None
        channel = None
        try:
            client.settimeout(30)
            transport = paramiko.Transport(client)
            with self._lock:
                self._transports.add(transport)
            transport.add_server_key(self._host_key)
            session = _AtlasSSHSession(self)
            transport.start_server(server=session)
            channel = transport.accept(30)
            if channel is None or not session.request_event.wait(30):
                return
            remote_shell = self.shell_factory(session.username)
            if session.shell_requested:
                self._run_interactive_shell(channel, remote_shell, session.username)
            elif session.command is not None:
                self._send_command_result(channel, remote_shell, session.command)
        except (OSError, paramiko.SSHException, UnicodeError) as exc:
            logger.info("Atlas SSH session from %s ended: %s", address, exc)
        except Exception:
            logger.exception("Unexpected Atlas SSH session failure from %s", address)
            if channel is not None and not channel.closed:
                try:
                    channel.sendall(b"Atlas SSH: internal session error.\n")
                    channel.send_exit_status(1)
                    channel.close()
                except (OSError, paramiko.SSHException):
                    pass
        finally:
            self._client_slots.release()
            if transport is not None:
                transport.close()
                with self._lock:
                    self._transports.discard(transport)
            else:
                client.close()

    @classmethod
    def _run_remote_command(cls, shell, command):
        try:
            import shlex

            words = shlex.split(command)
        except ValueError as exc:
            return f"Atlas SSH: invalid command syntax: {exc}", 2
        if not words:
            return "", 0
        if words[0].lower() in ("exit", "quit"):
            return "", 0
        command_name = words[0].lower()
        if command_name not in cls.REMOTE_COMMANDS:
            return f"Atlas SSH: command '{words[0]}' is not available remotely.", 126
        try:
            path_error = cls._validate_remote_paths(shell, command_name, words)
            if path_error:
                return path_error, 1
            output = shell.eval_command(command)
        except Exception as exc:
            logger.exception("Atlas SSH command failed")
            return f"Atlas SSH command error: {exc}", 1
        return ("" if output is None else str(output)), 0

    @classmethod
    def _validate_remote_paths(cls, shell, command_name, words):
        if command_name not in cls.REMOTE_PATH_COMMANDS:
            return None
        username = shell.variables["SYS.USER"]
        home_vpath = f"/Users/{username}/home"
        cwd = shell.variables.get("SYS.CWD", home_vpath)
        arguments = words[1:]
        if command_name in ("ls", "ll", "la"):
            paths = [argument for argument in arguments if not argument.startswith("-")]
            if len(paths) > 1:
                return "Atlas SSH: ls accepts at most one path."
        elif command_name == "cd":
            if len(arguments) > 1:
                return "Atlas SSH: cd accepts at most one path."
            paths = arguments or [home_vpath]
        elif command_name == "cat":
            if len(arguments) != 1:
                return "Atlas SSH: cat accepts exactly one file."
            paths = arguments
        elif command_name in ("mkdir", "touch"):
            if len(arguments) != 1:
                return f"Atlas SSH: {command_name} accepts exactly one path."
            paths = arguments
        else:
            return None

        home_path, _ = shell.storage.resolve_vpath(home_vpath, "/", username)
        resolved_home = home_path.resolve()
        for path in paths:
            physical_path, virtual_path = shell.storage.resolve_vpath(path, cwd, username)
            normalized = posixpath.normpath(virtual_path)
            if normalized != home_vpath and not normalized.startswith(home_vpath + "/"):
                return "Atlas SSH: file access is confined to the authenticated user's home directory."
            try:
                physical_path.resolve().relative_to(resolved_home)
            except ValueError:
                return "Atlas SSH: file access is confined to the authenticated user's home directory."
        return None

    @classmethod
    def _send_command_result(cls, channel, shell, command):
        output, exit_code = cls._run_remote_command(shell, command)
        if output:
            channel.sendall(output.encode("utf-8", errors="replace"))
            if not output.endswith("\n"):
                channel.sendall(b"\n")
        channel.send_exit_status(exit_code)
        channel.close()

    @classmethod
    def _run_interactive_shell(cls, channel, shell, username):
        channel.sendall(f"Atlas OS SSH shell for {username}. Type 'exit' to disconnect.\r\n".encode())
        channel.sendall(f"{username}@atlas:~$ ".encode())
        command = bytearray()
        while not channel.closed:
            try:
                data = channel.recv(1024)
            except (OSError, socket.timeout):
                return
            if not data:
                return
            for byte in data:
                if byte in (10, 13):
                    if not command:
                        continue
                    line = command.decode("utf-8", errors="replace")
                    command.clear()
                    if line.strip().lower() in ("exit", "quit"):
                        channel.sendall(b"\r\nSession closed.\r\n")
                        channel.send_exit_status(0)
                        channel.close()
                        return
                    output, exit_code = cls._run_remote_command(shell, line)
                    channel.sendall(b"\r\n")
                    if output:
                        channel.sendall(output.replace("\n", "\r\n").encode("utf-8", errors="replace"))
                        if not output.endswith("\n"):
                            channel.sendall(b"\r\n")
                    if exit_code:
                        channel.sendall(f"Exit code: {exit_code}\r\n".encode())
                    channel.sendall(f"{username}@atlas:~$ ".encode())
                elif byte in (8, 127):
                    if command:
                        command.pop()
                elif byte >= 32:
                    command.append(byte)
        channel.send_exit_status(0)
