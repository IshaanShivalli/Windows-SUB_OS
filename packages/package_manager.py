import json
import hashlib
import time
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"
REPO_DIR = ROOT_DIR / "packages" / "repo"

class PackageManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PackageManager, cls).__new__(cls)
            cls._instance.init_pkg_manager()
        return cls._instance

    def init_pkg_manager(self):
        REPO_DIR.mkdir(parents=True, exist_ok=True)
        self.history_log = []
        self.seed_repository()

    def seed_repository(self):
        # Sample signed packages in the repository
        pkgs = [
            {
                "id": "app.calc",
                "name": "Operator Scientific Calculator",
                "version": "1.2.0",
                "runtime": "java",
                "entrypoint": "runtime_java/bin/OperatorRuntime.jar",
                "deps": ["core.ovm"],
                "signature": "SHA256:d8a9f029381cbb471e9",
                "desc": "Precision mathematical engine with trigonometric sandboxing"
            },
            {
                "id": "tool.netdiag",
                "name": "Network Socket Analyzer",
                "version": "1.0.4",
                "runtime": "python",
                "entrypoint": "network/net_stack.py",
                "deps": ["core.shell"],
                "signature": "SHA256:aa918237190bc981df2",
                "desc": "Interface probing and deep packet latency telemetry"
            },
            {
                "id": "app.nano",
                "name": "Operator Code Editor",
                "version": "10.0.0",
                "runtime": "python",
                "entrypoint": "apps/nano.py",
                "deps": ["core.shell"],
                "signature": "SHA256:77918237190bc981aa1",
                "desc": "Terminal code editor with syntax highlighting and installable language completion extensions"
            },
            {
                "id": "app.editor",
                "name": "Operator Code Editor",
                "version": "10.0.0",
                "runtime": "python",
                "entrypoint": "apps/nano.py",
                "deps": ["core.shell"],
                "signature": "SHA256:55018274aee902bb14c",
                "desc": "Terminal code editor with syntax highlighting and installable language completion extensions"
            }
        ]
        for p in pkgs:
            p_file = REPO_DIR / f"{p['id']}.manifest.json"
            if not p_file.exists():
                p_file.write_text(json.dumps(p, indent=2), encoding="utf-8")

    def list_installed(self) -> List[dict]:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            rows = conn.execute("SELECT id, name, version, runtime, status, description FROM sys_packages").fetchall()
            return [{"id": r[0], "name": r[1], "version": r[2], "runtime": r[3], "status": r[4], "desc": r[5]} for r in rows]

    def list_available(self) -> List[dict]:
        available = []
        for mf in REPO_DIR.glob("*.manifest.json"):
            data = json.loads(mf.read_text(encoding="utf-8"))
            available.append(data)
        return available

    def install(self, pkg_id: str) -> str:
        mf_path = REPO_DIR / f"{pkg_id}.manifest.json"
        if not mf_path.exists():
            return f"\033[31m[PKG ERR] Package '{pkg_id}' not found in official repository.\033[0m"

        pkg_data = json.loads(mf_path.read_text(encoding="utf-8"))

        # Dependency resolution
        installed_ids = [p["id"] for p in self.list_installed()]
        for dep in pkg_data.get("deps", []):
            if dep not in installed_ids:
                return f"\033[31m[PKG DEP ERR] Missing dependency '{dep}' for package '{pkg_id}'.\033[0m"

        # Verify signature
        sig = pkg_data.get("signature", "")
        if not sig.startswith("SHA256:"):
            return f"\033[31m[PKG SEC ERR] Untrusted package signature on '{pkg_id}'.\033[0m"

        with closing(sqlite3.connect(DB_PATH)) as conn:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sys_packages (id, name, version, architecture, runtime, entrypoint, description, author, status)
                    VALUES (?, ?, ?, 'x86_64', ?, ?, ?, 'Operator System Repo', 'active')
                """, (pkg_data["id"], pkg_data["name"], pkg_data["version"], pkg_data["runtime"], pkg_data["entrypoint"], pkg_data["desc"]))

        self.history_log.append({"action": "INSTALL", "pkg": pkg_id, "version": pkg_data["version"], "time": time.time()})
        return f"\033[1;32m[PKG SUCCESS]\033[0m Installed '{pkg_data['name']}' v{pkg_data['version']} with verified signature."

    def uninstall(self, pkg_id: str) -> str:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            with conn:
                res = conn.execute("DELETE FROM sys_packages WHERE id = ?", (pkg_id,))
            if res.rowcount > 0:
                self.history_log.append({"action": "UNINSTALL", "pkg": pkg_id, "time": time.time()})
                return f"\033[1;33m[PKG REMOVED]\033[0m Successfully uninstalled '{pkg_id}'."
        return f"\033[31m[PKG ERR] Package '{pkg_id}' is not installed.\033[0m"

    def rollback(self) -> str:
        if not self.history_log:
            return "No previous package actions to rollback."
        last_op = self.history_log.pop()
        if last_op["action"] == "INSTALL":
            return self.uninstall(last_op["pkg"])
        return f"Rollback finished for {last_op['action']}."
