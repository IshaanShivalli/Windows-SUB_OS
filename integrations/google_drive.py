"""Optional runtime Google Drive integration for Operator OS.

Nothing in this module runs during boot. Authentication starts only when the
user explicitly invokes ``drive.connect`` from Operator Shell.
"""

import json
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
CLIENT_FILE = CONFIG_DIR / "google_drive_oauth.json"
TOKEN_FILE = CONFIG_DIR / "google_drive_token.json"
MOUNT_DIR = ROOT_DIR / "storage" / "operator_home" / "Google Drive"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_NAMES = ("Docs", "Videos", "Pictures")


class GoogleDriveManager:
    def status(self):
        return {
            "configured": CLIENT_FILE.exists(),
            "authenticated": TOKEN_FILE.exists(),
            "mount": str(MOUNT_DIR),
            "folders": list(FOLDER_NAMES),
        }

    def connect_interactively(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            return "Google Drive support is optional. Run: python -m pip install -r requirements.txt"

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CLIENT_FILE.exists():
            supplied = input("OAuth client JSON path (blank to cancel): ").strip().strip('"')
            if not supplied:
                return "Google Drive connection cancelled."
            source = Path(supplied).expanduser()
            if not source.exists():
                return f"OAuth client file not found: {source}"
            CLIENT_FILE.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

        credentials = None
        if TOKEN_FILE.exists():
            credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
            credentials = flow.run_local_server(port=0, open_browser=True)
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

        service = build("drive", "v3", credentials=credentials)
        root = self._find_or_create_folder(service, "Operator OS", None)
        MOUNT_DIR.mkdir(parents=True, exist_ok=True)
        for name in FOLDER_NAMES:
            self._find_or_create_folder(service, name, root["id"])
            (MOUNT_DIR / name).mkdir(exist_ok=True)
        return "Google Drive connected. Operator OS folders are ready."

    @staticmethod
    def _find_or_create_folder(service, name, parent_id):
        query = "name = '{}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false".format(name.replace("'", "\\'"))
        if parent_id:
            query += f" and '{parent_id}' in parents"
        result = service.files().list(q=query, spaces="drive", fields="files(id,name)").execute()
        if result.get("files"):
            return result["files"][0]
        body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            body["parents"] = [parent_id]
        return service.files().create(body=body, fields="id,name").execute()
