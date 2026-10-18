import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"

class SystemSettingsService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SystemSettingsService, cls).__new__(cls)
            cls._instance.init_settings()
        return cls._instance

    def init_settings(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sys_services (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    exec_cmd TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'STOPPED',
                    pid INTEGER DEFAULT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sys_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'string',
                    category TEXT NOT NULL DEFAULT 'general',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Seed default system services into SQLite
            services = [
                ("kernel_guard", "Kernel Memory Page Supervisor", "bin/kernel_guard.exe"),
                ("net_stack", "Virtual Network Gateway Daemon", "python network/net_stack.py"),
                ("storage_vfs", "2GB Raw Block Storage Journaler", "python storage/storage_manager.py"),
                ("compositor_wm", "C++ Desktop Window Manager", "bin/operator_wm.exe"),
            ]
            for s in services:
                conn.execute("INSERT OR IGNORE INTO sys_services (name, description, exec_cmd) VALUES (?, ?, ?)", s)
            conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT value FROM sys_settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str, category: str = "general") -> str:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO sys_settings (key, value, category) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, category=excluded.category, updated_at=CURRENT_TIMESTAMP
            """, (key, value, category))
            conn.commit()
        return f"[SETTINGS] Set '{key}' = '{value}'"

    def list_settings(self, category: Optional[str] = None) -> List[dict]:
        with sqlite3.connect(DB_PATH) as conn:
            if category:
                rows = conn.execute("SELECT key, value, category, type FROM sys_settings WHERE category = ?", (category,)).fetchall()
            else:
                rows = conn.execute("SELECT key, value, category, type FROM sys_settings").fetchall()
            return [{"key": r[0], "value": r[1], "category": r[2], "type": r[3]} for r in rows]

    # Service Manager (SQLite Backed)
    def list_services(self) -> List[dict]:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT name, description, status, enabled, pid FROM sys_services").fetchall()
            return [{"name": r[0], "description": r[1], "status": r[2], "enabled": bool(r[3]), "pid": r[4]} for r in rows]

    def start_service(self, name: str) -> str:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT exec_cmd FROM sys_services WHERE name = ?", (name,)).fetchone()
            if not row:
                return f"\033[31m[SRV ERR] Service '{name}' not found in SQLite registry.\033[0m"
            import subprocess
            p = subprocess.Popen(row[0], shell=True, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            conn.execute("UPDATE sys_services SET status = 'RUNNING', pid = ? WHERE name = ?", (p.pid, name))
            conn.commit()
            return f"\033[1;32m[SRV ACTIVE]\033[0m Started service '{name}' [PID: {p.pid}]"

    def stop_service(self, name: str) -> str:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT pid FROM sys_services WHERE name = ?", (name,)).fetchone()
            if row and row[0]:
                os.system(f"taskkill /PID {row[0]} /F >nul 2>&1")
            conn.execute("UPDATE sys_services SET status = 'STOPPED', pid = NULL WHERE name = ?", (name,))
            conn.commit()
            return f"\033[1;33m[SRV STOPPED]\033[0m Stopped service '{name}'"
