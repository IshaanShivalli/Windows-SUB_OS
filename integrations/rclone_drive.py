"""Rclone-backed Google Drive integration and per-user Operator OS mount."""

import base64
import getpass
import hashlib
import hmac
import json
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath

ROOT_DIR = Path(__file__).resolve().parent.parent
MOUNT_DIR = ROOT_DIR / "storage" / "operator_home" / "Google Drive"
INDEX_NAME = ".operator-drive-index.json"
WRITE_SESSION_SECONDS = 3 * 60 * 60
PBKDF2_ITERATIONS = 310_000
SYNC_INTERVAL_SECONDS = 3


class RcloneDriveManager:
    def __init__(self, network=None, storage=None):
        self.storage = storage
        self._username = None
        self._mount_dir = None
        self._config_path = None
        self._remote = None
        self._index = {}
        self._sync_lock = threading.RLock()
        self._messages_lock = threading.Lock()
        self._messages = []
        self._stop_event = threading.Event()
        self._sync_thread = None
        self._write_unlock_expires = 0.0
        self._lock_notice_sent = False

    def status(self, current_user="operator"):
        mount_dir = self._resolve_mount_dir(current_user)
        config_path = self._config_path_for(current_user)
        remote = self._read_remote(current_user)
        return {
            "configured": config_path.is_file() and remote is not None,
            "authenticated": self._remote is not None and current_user == self._username,
            "mount": str(self._mount_dir if current_user == self._username else mount_dir),
            "write_unlocked": current_user == self._username and self._is_write_unlocked(),
            "sync_messages": self._take_messages(),
        }

    def connect_interactively(self):
        return self.mount_interactively()

    def mount_interactively(self, username=None):
        username = username or self._username or "operator"
        if self.storage is None:
            raise RuntimeError("Google Drive requires the Operator storage service")
        rclone = self._find_rclone()
        config_path = self._config_path_for(username)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        remotes = self._list_remotes(rclone, config_path)

        if not remotes:
            print(
                "Starting rclone configuration. Choose 'Google Drive' as the storage type "
                "and complete the Google sign-in in the browser."
            )
            result = subprocess.run(
                [rclone, "--config", str(config_path), "config"],
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"rclone config exited with code {result.returncode}")
            remotes = self._list_remotes(rclone, config_path)
        if not remotes:
            raise RuntimeError(
                "No rclone remotes are configured. Run 'rclone config' and create a Google Drive remote."
            )

        remote = self._read_remote(username)
        if remote not in remotes:
            remote = self._choose_remote(remotes)
            self._write_remote(username, remote)

        mount_dir = self._resolve_mount_dir(username)
        mount_dir.mkdir(parents=True, exist_ok=True)
        self._run_rclone(
            rclone,
            "lsjson",
            self._remote_path(remote),
            config_path=config_path,
        )

        self._stop_sync_worker()
        self._username = username
        self._mount_dir = mount_dir
        self._config_path = config_path
        self._remote = remote
        self._index = self._read_index()
        if not (mount_dir / INDEX_NAME).exists():
            for local_path in self._iter_local_files():
                relative = local_path.relative_to(mount_dir).as_posix()
                self._index[relative] = {"sha256": self._hash_file(local_path)}
            self._write_index()
        self._write_unlock_expires = 0.0
        self._start_sync_worker()

        return (
            f"Google Drive rclone remote '{remote}' connected at /Users/{username}/Google Drive. "
            "Use drive.ls to list remote files and drive.download <file-id-or-path> to fetch a file. "
            "Automatic uploads are locked until drive.write.setup or drive.write.unlock."
        )

    def list_files(self, folder_id="root", username=None):
        self._require_mounted(username)
        relative = "" if folder_id in ("", "root") else self._normalize_remote_path(folder_id)
        result = self._run_rclone(
            self._find_rclone(),
            "lsjson",
            self._remote_path(self._remote, relative),
            config_path=self._config_path,
        )
        try:
            entries = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError("rclone returned invalid JSON while listing Google Drive") from exc
        if not isinstance(entries, list):
            raise RuntimeError("rclone returned an unexpected listing format")
        return [
            {
                "id": item.get("ID") or item.get("Path", item.get("Name", "")),
                "name": item.get("Name", ""),
                "mimeType": item.get("MimeType", ""),
                "size": item.get("Size", "-"),
                "modifiedTime": item.get("ModTime", ""),
            }
            for item in entries
        ]

    def download_file(self, file_id_or_path, username=None):
        self._require_mounted(username)
        if not file_id_or_path:
            raise ValueError("Usage: drive.download <file-id-or-path>")
        remote_path = self._find_remote_file(file_id_or_path)
        filename = self._safe_local_name(PurePosixPath(remote_path).name)
        destination = self._mount_dir / filename
        if destination.exists():
            suffix = hashlib.sha256(remote_path.encode()).hexdigest()[:8]
            destination = destination.with_name(
                f"{destination.stem} ({suffix}){destination.suffix}"
            )
            duplicate = 2
            while destination.exists():
                destination = destination.with_name(
                    f"{destination.stem} ({duplicate}){destination.suffix}"
                )
                duplicate += 1
        self._run_rclone(
            self._find_rclone(),
            "copyto",
            self._remote_path(self._remote, remote_path),
            str(destination),
            config_path=self._config_path,
        )
        destination.resolve().relative_to(self._mount_dir.resolve())
        self._index[destination.relative_to(self._mount_dir).as_posix()] = {
            "sha256": self._hash_file(destination),
        }
        self._write_index()
        return str(destination)

    def upload_file(self, local_path, username=None):
        self._require_mounted(username)
        path = Path(local_path).resolve()
        path.relative_to(self._mount_dir.resolve())
        if not path.is_file():
            raise FileNotFoundError(f"Drive upload source is not a file: {path}")
        if not self._is_write_unlocked():
            raise PermissionError(
                "Drive writes are locked; run drive.write.setup or drive.write.unlock"
            )
        with self._sync_lock:
            self._upload_local_file(path)
        return f"Uploaded '{path.name}' to Google Drive."

    def setup_write_passphrase(self, username=None):
        self._require_mounted()
        self._check_write_user(username)
        first = getpass.getpass("New local Drive write passphrase: ")
        second = getpass.getpass("Confirm local Drive write passphrase: ")
        if len(first) < 8:
            raise ValueError("Drive write passphrase must be at least 8 characters")
        if not hmac.compare_digest(first, second):
            raise ValueError("Passphrases do not match")

        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            first.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
        )
        policy = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(digest).decode("ascii"),
            "iterations": PBKDF2_ITERATIONS,
        }
        self._write_json(self._write_policy_path(self._username), policy)
        self._write_unlock_expires = time.monotonic() + WRITE_SESSION_SECONDS
        self._lock_notice_sent = False
        return "Drive uploads unlocked for this shell session (up to 3 hours)."

    def unlock_writes(self, username=None):
        self._require_mounted()
        self._check_write_user(username)
        policy_path = self._write_policy_path(self._username)
        if not policy_path.is_file():
            raise ValueError("No local Drive write passphrase is set; run drive.write.setup")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        iterations = int(policy["iterations"])
        if not 100_000 <= iterations <= 2_000_000:
            raise ValueError("Drive write passphrase configuration has an invalid hash work factor")
        supplied = getpass.getpass("Local Drive write passphrase: ")
        salt = base64.b64decode(policy["salt"], validate=True)
        expected = base64.b64decode(policy["hash"], validate=True)
        actual = hashlib.pbkdf2_hmac("sha256", supplied.encode("utf-8"), salt, iterations)
        if not hmac.compare_digest(actual, expected):
            raise PermissionError("Incorrect local Drive write passphrase")
        self._write_unlock_expires = time.monotonic() + WRITE_SESSION_SECONDS
        self._lock_notice_sent = False
        return "Drive uploads unlocked for this shell session (up to 3 hours)."

    def _find_remote_file(self, file_id_or_path):
        candidate = self._normalize_remote_path(file_id_or_path)
        result = self._run_rclone(
            self._find_rclone(),
            "lsjson",
            "--recursive",
            self._remote_path(self._remote),
            config_path=self._config_path,
        )
        try:
            entries = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError("rclone returned invalid JSON while searching Google Drive") from exc
        for item in entries:
            if item.get("ID") == file_id_or_path or item.get("Path") == candidate:
                if item.get("IsDir"):
                    raise ValueError("Downloading a folder is not supported; use drive.ls <remote-path>")
                return self._normalize_remote_path(item.get("Path", candidate))
        raise FileNotFoundError(f"Google Drive file was not found: {file_id_or_path}")

    def _upload_local_file(self, path):
        relative = path.relative_to(self._mount_dir).as_posix()
        digest = self._hash_file(path)
        if self._index.get(relative, {}).get("sha256") == digest:
            return False
        self._run_rclone(
            self._find_rclone(),
            "copyto",
            str(path),
            self._remote_path(self._remote, relative),
            config_path=self._config_path,
        )
        self._index[relative] = {"sha256": digest}
        self._write_index()
        return True

    def _sync_worker(self):
        while not self._stop_event.wait(SYNC_INTERVAL_SECONDS):
            try:
                self._sync_pending_files()
            except Exception as exc:
                self._record_message(f"Drive sync paused; local changes remain queued: {exc}")

    def _sync_pending_files(self):
        if not self._is_write_unlocked():
            return
        with self._sync_lock:
            for path in self._iter_local_files():
                relative = path.relative_to(self._mount_dir).as_posix()
                if self._index.get(relative, {}).get("sha256") == self._hash_file(path):
                    continue
                if not self._is_write_unlocked():
                    return
                if self._upload_local_file(path):
                    self._record_message(f"Uploaded changed file: {relative}")

    def _start_sync_worker(self):
        self._stop_event.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_worker,
            name="operator-drive-sync",
            daemon=True,
        )
        self._sync_thread.start()

    def _stop_sync_worker(self):
        self._stop_event.set()
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=30)
            if self._sync_thread.is_alive():
                raise RuntimeError("Drive sync is still active; try mounting the other account again")
        self._sync_thread = None

    def _is_write_unlocked(self):
        if self._write_unlock_expires <= 0:
            return False
        if time.monotonic() < self._write_unlock_expires:
            return True
        self._write_unlock_expires = 0.0
        if not self._lock_notice_sent:
            self._record_message(
                "Drive write session expired after 3 hours; run drive.write.unlock and enter the local passphrase"
            )
            self._lock_notice_sent = True
        return False

    def _resolve_mount_dir(self, username):
        path, _ = self.storage.resolve_vpath(
            f"/Users/{username}/Google Drive",
            "/",
            username,
        )
        return Path(path)

    def _config_path_for(self, username):
        return self._resolve_mount_dir(username).parent / ".operator" / "rclone.conf"

    def _remote_selection_path(self, username):
        return self._resolve_mount_dir(username).parent / ".operator" / "rclone_remote.json"

    def _write_policy_path(self, username):
        return self._resolve_mount_dir(username).parent / ".operator" / "google_drive_write.json"

    def _read_remote(self, username):
        path = self._remote_selection_path(username)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        remote = value.get("remote") if isinstance(value, dict) else None
        return remote if isinstance(remote, str) and remote else None

    def _write_remote(self, username, remote):
        self._write_json(self._remote_selection_path(username), {"remote": remote})

    def _list_remotes(self, rclone, config_path):
        result = self._run_rclone(rclone, "listremotes", config_path=config_path)
        return [line[:-1] for line in result.stdout.splitlines() if line.endswith(":")]

    @staticmethod
    def _choose_remote(remotes):
        if len(remotes) == 1:
            return remotes[0]
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Multiple rclone remotes are configured. Run drive.mount interactively to choose one."
            )
        preferred = "gdrive" if "gdrive" in remotes else remotes[0]
        selected = input(f"Rclone remote name [{preferred}]: ").strip() or preferred
        if selected not in remotes:
            raise ValueError(f"Rclone remote '{selected}' is not configured")
        return selected

    @staticmethod
    def _find_rclone():
        executable = shutil.which("rclone")
        if executable:
            return executable

        packaged_candidates = (
            ROOT_DIR / "bin" / "rclone.exe",
            ROOT_DIR / "storage" / "operator_os_root" / "System" / "bin" / "rclone.exe",
        )
        for candidate in packaged_candidates:
            if candidate.is_file():
                return str(candidate)
        raise RuntimeError(
            "rclone was not found on PATH or in the packaged Operator runtime. "
            "Install rclone or rebuild with --rclone-executable, then run drive.mount."
        )

    @staticmethod
    def _run_rclone(executable, *arguments, config_path):
        command = [
            executable,
            "--config",
            str(config_path),
            "--contimeout",
            "15s",
            "--timeout",
            "2m",
            *arguments,
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                f"rclone command failed with exit code {result.returncode}"
                + (f": {detail}" if detail else "")
            )
        return result

    @staticmethod
    def _normalize_remote_path(value):
        normalized = str(value).replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            raise ValueError("Google Drive remote path must be relative")
        normalized = normalized.strip("/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or any(part in (".", "..") for part in path.parts):
            raise ValueError("Google Drive remote path must be relative and cannot contain '..'")
        return "" if normalized in ("", ".") else path.as_posix()

    @classmethod
    def _remote_path(cls, remote, relative=""):
        relative = cls._normalize_remote_path(relative)
        return f"{remote}:{relative}" if relative else f"{remote}:"

    def _check_write_user(self, username):
        target = username or self._username
        if target != self._username:
            raise PermissionError("Only the mounted Drive account can unlock its write access")

    def _require_mounted(self, username=None):
        if self._remote is None or self._mount_dir is None or self._config_path is None:
            raise RuntimeError("Google Drive is not mounted; run drive.mount first")
        if username is not None and username != self._username:
            raise PermissionError("Google Drive is mounted for a different Operator OS user")

    def _read_index(self):
        path = self._mount_dir / INDEX_NAME
        if not path.is_file():
            return {}
        index = json.loads(path.read_text(encoding="utf-8"))
        return index if isinstance(index, dict) else {}

    def _write_index(self):
        self._write_json(self._mount_dir / INDEX_NAME, self._index)

    def _iter_local_files(self):
        for path in self._mount_dir.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.name != INDEX_NAME:
                yield path

    @staticmethod
    def _write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _hash_file(path):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_local_name(name):
        cleaned = "".join(
            "_" if character in '<>:"/\\|?*' or ord(character) < 32 else character
            for character in name
        ).strip().rstrip(". ")
        if not cleaned or cleaned in (".", ".."):
            cleaned = "unnamed"
        if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", cleaned, re.I):
            cleaned = "_" + cleaned
        return cleaned

    def _record_message(self, message):
        with self._messages_lock:
            if message not in self._messages:
                self._messages.append(message)
                self._messages = self._messages[-20:]

    def _take_messages(self):
        with self._messages_lock:
            messages = list(self._messages)
            self._messages.clear()
        return messages
