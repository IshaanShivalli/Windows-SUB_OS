"""Google Drive OAuth and per-user Operator OS mount."""

import base64
import getpass
import hashlib
import hmac
import json
import mimetypes
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
MOUNT_DIR = ROOT_DIR / "storage" / "operator_home" / "Google Drive"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
FOLDER_MIME = "application/vnd.google-apps.folder"
INDEX_NAME = ".operator-drive-index.json"
WRITE_SESSION_SECONDS = 3 * 60 * 60
PBKDF2_ITERATIONS = 310_000
EXPORT_TYPES = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}


class GoogleDriveManager:
    def __init__(self, network=None, storage=None):
        self.network = network
        self.storage = storage
        self._service = None
        self._credentials = None
        self._username = None
        self._mount_dir = None
        self._token = None
        self._index = {}
        self._folder_ids = {"": "root"}
        self._sync_lock = threading.RLock()
        self._token_lock = threading.Lock()
        self._messages_lock = threading.Lock()
        self._messages = []
        self._stop_event = threading.Event()
        self._sync_thread = None
        self._write_unlock_expires = 0.0
        self._lock_notice_sent = False

    def status(self, current_user="operator"):
        mount_path = self._mount_dir
        if self.storage is not None and current_user != self._username:
            mount_path = self._resolve_mount_dir(current_user)
        return {
            "configured": self._token_path(current_user).is_file(),
            "authenticated": self._service is not None and current_user == self._username,
            "mount": str(mount_path or MOUNT_DIR),
            "write_unlocked": current_user == self._username and self._is_write_unlocked(),
            "sync_messages": self._take_messages(),
        }

    def connect_interactively(self):
        return self.mount_interactively()

    def mount_interactively(self, username=None, client_id=None):
        username = username or self._username or "operator"
        if self.network is None or self.storage is None:
            raise RuntimeError("Google Drive requires the Operator network and storage services")

        token_path = self._token_path(username)
        token = self._read_token(token_path)
        if token is None or token.get("scope") != DRIVE_SCOPE:
            if client_id is None:
                client_id = input("Google OAuth Client ID: ").strip()
            token = self._authorize(client_id)
            self._write_token(token_path, token)
        else:
            if client_id and client_id != token.get("client_id"):
                token = self._authorize(client_id)
                self._write_token(token_path, token)
            elif token.get("expires_at", 0) <= time.time() + 60:
                if not token.get("refresh_token"):
                    if client_id is None:
                        client_id = input("Google OAuth Client ID: ").strip()
                    token = self._authorize(client_id)
                else:
                    token = self._refresh(token)
                self._write_token(token_path, token)

        credentials, service = self._create_service(token)
        service.files().list(pageSize=1, fields="files(id)").execute()
        mount_dir = self._resolve_mount_dir(username)
        mount_dir.mkdir(parents=True, exist_ok=True)

        self._stop_sync_worker()
        self._username = username
        self._token = token
        self._credentials = credentials
        self._service = service
        self._mount_dir = mount_dir
        self._index = self._read_index()
        if not (mount_dir / INDEX_NAME).exists():
            for local_path in self._iter_local_files():
                relative = local_path.relative_to(mount_dir).as_posix()
                self._index[relative] = {"sha256": self._hash_file(local_path)}
            self._write_index()
        self._write_unlock_expires = 0.0
        self._start_sync_worker()

        return (
            f"Google Drive mounted at /Users/{username}/Google Drive. "
            "Use drive.ls to list remote files and drive.download <file-id> to fetch a file. "
            "Automatic uploads are locked until drive.write.setup or drive.write.unlock."
        )

    def list_files(self, folder_id="root", username=None):
        self._require_mounted(username)
        self._ensure_fresh_token()
        files = []
        page_token = None
        while True:
            self._ensure_fresh_token()
            response = self._service.files().list(
                q=f"'{self._escape_query_value(folder_id)}' in parents and trashed = false",
                pageSize=1000,
                pageToken=page_token,
                orderBy="name",
                fields="nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink)",
            ).execute()
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return files

    def download_file(self, file_id, username=None):
        self._require_mounted(username)
        if not file_id:
            raise ValueError("Usage: drive.download <file-id>")
        self._ensure_fresh_token()
        metadata = self._service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,modifiedTime",
        ).execute()
        mime_type = metadata.get("mimeType", "application/octet-stream")
        export = EXPORT_TYPES.get(mime_type)
        if mime_type == FOLDER_MIME:
            raise ValueError("Downloading a folder is not supported; use drive.ls <folder-id>")
        if mime_type.startswith("application/vnd.google-apps.") and not export:
            raise ValueError(f"Google Drive export is not supported for {mime_type}")
        self._ensure_fresh_token()

        name = self._safe_local_name(metadata["name"])
        if export:
            request = self._service.files().export_media(
                fileId=file_id,
                mimeType=export[0],
            )
            name = Path(name).stem + export[1]
        else:
            request = self._service.files().get_media(fileId=file_id)

        destination = self._mount_dir / name
        index_key = destination.relative_to(self._mount_dir).as_posix()
        current = self._index.get(index_key, {})
        if destination.exists() and (
            current.get("file_id") != file_id
            or current.get("sha256") != self._hash_file(destination)
        ):
            destination = destination.with_name(
                f"{destination.stem} ({file_id[:8]}){destination.suffix}"
            )
            index_key = destination.relative_to(self._mount_dir).as_posix()
        destination = destination.resolve()
        destination.relative_to(self._mount_dir.resolve())
        temporary = destination.with_name(destination.name + ".operator-download")

        try:
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as exc:
            raise RuntimeError(
                "Google Drive support is optional. Run: python -m pip install -r requirements.txt"
            ) from exc

        try:
            with temporary.open("wb") as output:
                downloader = MediaIoBaseDownload(output, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        self._index[index_key] = {
            "file_id": file_id,
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
        username = username or self._username
        if username != self._username:
            raise PermissionError("Only the mounted Drive account can unlock its write access")
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
        self._write_json(self._write_policy_path(username), policy)
        self._write_unlock_expires = time.monotonic() + WRITE_SESSION_SECONDS
        self._lock_notice_sent = False
        return "Drive uploads unlocked for this shell session (up to 3 hours)."

    def unlock_writes(self, username=None):
        self._require_mounted()
        username = username or self._username
        if username != self._username:
            raise PermissionError("Only the mounted Drive account can unlock its write access")
        policy_path = self._write_policy_path(username)
        if not policy_path.is_file():
            raise ValueError("No local Drive write passphrase is set; run drive.write.setup")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        iterations = int(policy["iterations"])
        if not 100_000 <= iterations <= 2_000_000:
            raise ValueError("Drive write passphrase configuration has an invalid hash work factor")
        supplied = getpass.getpass("Local Drive write passphrase: ")
        salt = base64.b64decode(policy["salt"], validate=True)
        expected = base64.b64decode(policy["hash"], validate=True)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            supplied.encode("utf-8"),
            salt,
            iterations,
        )
        if not hmac.compare_digest(actual, expected):
            raise PermissionError("Incorrect local Drive write passphrase")
        self._write_unlock_expires = time.monotonic() + WRITE_SESSION_SECONDS
        self._lock_notice_sent = False
        return "Drive uploads unlocked for this shell session (up to 3 hours)."

    def _authorize(self, client_id):
        if (
            not client_id
            or any(character.isspace() for character in client_id)
            or not client_id.endswith(".apps.googleusercontent.com")
        ):
            raise ValueError("A valid Google OAuth Client ID is required")
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        result = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                if query.get("state", [""])[0] != state:
                    self.send_response(400)
                    self.end_headers()
                    return
                if query.get("error"):
                    result["error"] = query["error"][0]
                elif not query.get("code"):
                    result["error"] = "OAuth callback did not include an authorization code"
                else:
                    result["code"] = query["code"][0]
                self.send_response(200 if "code" in result else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"Sign-in received. You can close this browser tab and return to Operator OS."
                    if "code" in result
                    else b"Sign-in could not be completed. Return to Operator OS."
                )

            def log_message(self, format_string, *args):
                return

        callback = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        deadline = time.monotonic() + 180
        redirect_uri = f"http://127.0.0.1:{callback.server_port}/"
        query = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": DRIVE_SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        authorization_url = f"{AUTH_URI}?{query}"
        print("Opening Google sign-in. The browser will return to this local Operator session.")
        try:
            if not webbrowser.open(authorization_url):
                print(f"Open this URL to authorize Google Drive:\n{authorization_url}")
            while not result and time.monotonic() < deadline:
                callback.timeout = min(1, max(0, deadline - time.monotonic()))
                callback.handle_request()
        finally:
            callback.server_close()
        if "error" in result:
            raise RuntimeError(f"Google sign-in failed: {result['error']}")
        if "code" not in result:
            raise TimeoutError("Google sign-in timed out before the local callback arrived")

        token = self._request_token(
            {
                "client_id": client_id,
                "code": result["code"],
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )
        token["client_id"] = client_id
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
        granted_scopes = token.get("scope", "").split()
        if granted_scopes and DRIVE_SCOPE not in granted_scopes:
            raise PermissionError("Google did not grant the full Drive access scope")
        token["scope"] = DRIVE_SCOPE
        if not token.get("refresh_token"):
            raise RuntimeError(
                "Google did not return a refresh token. Revoke this app in Google Account settings and authorize again."
            )
        return token

    def _refresh(self, token):
        response = self._request_token(
            {
                "client_id": token["client_id"],
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            }
        )
        updated = {**token, **response}
        updated["refresh_token"] = response.get("refresh_token", token["refresh_token"])
        updated["client_id"] = token["client_id"]
        updated["expires_at"] = time.time() + int(response.get("expires_in", 3600))
        updated["scope"] = DRIVE_SCOPE
        return updated

    def _ensure_fresh_token(self):
        with self._token_lock:
            if self._token.get("expires_at", 0) > time.time() + 60:
                return
            if not self._token.get("refresh_token"):
                raise RuntimeError(
                    "Google Drive authorization expired; run drive.mount to sign in again"
                )
            self._token = self._refresh(self._token)
            self._write_token(self._token_path(self._username), self._token)
            self._credentials, self._service = self._create_service(self._token)

    def _request_token(self, parameters):
        response = self.network.http_request(
            "POST",
            TOKEN_URI,
            data=urllib.parse.urlencode(parameters).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
            max_bytes=1024 * 1024,
        )
        if response.get("truncated"):
            raise RuntimeError("Google OAuth response exceeded the configured size limit")
        try:
            payload = json.loads(response["body"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Google OAuth returned an invalid response") from exc
        if response["status_code"] < 200 or response["status_code"] >= 300:
            error = payload.get("error_description") or payload.get("error") or "request rejected"
            raise RuntimeError(f"Google OAuth token request failed: {error}")
        if not payload.get("access_token"):
            raise RuntimeError("Google OAuth response did not contain an access token")
        return payload

    @staticmethod
    def _create_service(token):
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Drive support is optional. Run: python -m pip install -r requirements.txt"
            ) from exc
        credentials = Credentials(
            token=token["access_token"],
            refresh_token=None,
            token_uri=TOKEN_URI,
            client_id=token["client_id"],
            scopes=[DRIVE_SCOPE],
            expiry=datetime.fromtimestamp(token["expires_at"], timezone.utc),
        )
        return credentials, build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

    def _upload_local_file(self, path):
        from googleapiclient.http import MediaFileUpload

        self._ensure_fresh_token()
        relative = path.relative_to(self._mount_dir).as_posix()
        digest = self._hash_file(path)
        previous = self._index.get(relative, {})
        if previous.get("sha256") == digest:
            return False

        parent_id = self._ensure_remote_parent(Path(relative).parent)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
        file_id = previous.get("file_id")
        if file_id:
            response = self._service.files().update(
                fileId=file_id,
                media_body=media,
                fields="id,name,modifiedTime",
            ).execute()
        else:
            response = self._service.files().create(
                body={"name": path.name, "parents": [parent_id]},
                media_body=media,
                fields="id,name,modifiedTime",
            ).execute()
        self._index[relative] = {
            "file_id": response["id"],
            "sha256": digest,
        }
        self._write_index()
        return True

    def _ensure_remote_parent(self, relative_parent):
        if str(relative_parent) in ("", "."):
            return "root"
        current_path = Path()
        parent_id = "root"
        for part in relative_parent.parts:
            current_path /= part
            key = current_path.as_posix()
            if key in self._folder_ids:
                parent_id = self._folder_ids[key]
                continue
            escaped_name = self._escape_query_value(part)
            response = self._service.files().list(
                q=(
                    f"name = '{escaped_name}' and mimeType = '{FOLDER_MIME}' "
                    f"and '{parent_id}' in parents and trashed = false"
                ),
                pageSize=1,
                fields="files(id)",
            ).execute()
            folders = response.get("files", [])
            if folders:
                parent_id = folders[0]["id"]
            else:
                folder = self._service.files().create(
                    body={
                        "name": part,
                        "mimeType": FOLDER_MIME,
                        "parents": [parent_id],
                    },
                    fields="id",
                ).execute()
                parent_id = folder["id"]
            self._folder_ids[key] = parent_id
        return parent_id

    def _sync_worker(self):
        while not self._stop_event.wait(3):
            try:
                self._sync_pending_files()
            except Exception as exc:
                self._record_message(f"Drive sync paused; local changes remain queued: {exc}")

    def _sync_pending_files(self):
        if not self._is_write_unlocked():
            return
        self._ensure_fresh_token()
        with self._sync_lock:
            for path in self._iter_local_files():
                relative = path.relative_to(self._mount_dir).as_posix()
                digest = self._hash_file(path)
                if self._index.get(relative, {}).get("sha256") == digest:
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

    def _token_path(self, username):
        mount = self._resolve_mount_dir(username)
        return mount.parent / ".operator" / "google_drive_token.json"

    def _write_policy_path(self, username):
        mount = self._resolve_mount_dir(username)
        return mount.parent / ".operator" / "google_drive_write.json"

    def _read_token(self, path):
        if not path.is_file():
            return None
        token = json.loads(path.read_text(encoding="utf-8"))
        if not token.get("access_token") or not token.get("client_id"):
            raise ValueError(f"Invalid Google Drive token file: {path}")
        return token

    @staticmethod
    def _write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _write_token(self, path, token):
        self._write_json(path, token)

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

    @staticmethod
    def _escape_query_value(value):
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _require_mounted(self, username=None):
        if self._service is None or self._mount_dir is None:
            raise RuntimeError("Google Drive is not mounted; run drive.mount first")
        if username is not None and username != self._username:
            raise PermissionError("Google Drive is mounted for a different Operator OS user")

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
