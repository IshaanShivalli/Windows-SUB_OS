import hashlib
import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"

class SecurityManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SecurityManager, cls).__new__(cls)
            cls._instance.init_security()
        return cls._instance

    def init_security(self):
        self.current_user: str = "operator"
        self.current_role: str = "user" # 'root', 'user', 'guest'
        self.acl_rules: Dict[str, Dict[str, str]] = {} # path -> {user: perms}
        self.firewall_rules: List[dict] = [
            {"id": 1, "action": "ALLOW", "proto": "TCP", "port": 8088, "desc": "PHP Web Browser"},
            {"id": 2, "action": "ALLOW", "proto": "TCP", "port": 9000, "desc": "Java OVM Sandbox"},
            {"id": 3, "action": "ALLOW", "proto": "UDP", "port": 53, "desc": "DNS Resolver"},
            {"id": 4, "action": "DENY", "proto": "ALL", "port": 23, "desc": "Telnet Insecure"},
        ]
        self.app_sandboxes: Dict[str, List[str]] = {
            "core.shell": ["CAP_SYS_EXEC", "CAP_NET_PROBE", "CAP_FS_RW"],
            "core.browser": ["CAP_NET_CLIENT", "CAP_RENDER"],
            "core.ovm": ["CAP_MATH_DSP", "CAP_MEMORY_ISOLATION"],
        }
        self.secrets_vault: Dict[str, str] = {}
        self.seed_users_and_secrets()

    def hash_password(self, password: str, salt: str = "OP_SEC_SALT_2026") -> str:
        return hashlib.sha256((salt + password).encode()).hexdigest()

    def seed_users_and_secrets(self):
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sys_auth (
                        username TEXT PRIMARY KEY,
                        pass_hash TEXT NOT NULL,
                        role TEXT NOT NULL,
                        salt TEXT NOT NULL
                    )
                """)
                # Seed root (pass: toor) and operator (pass: operator)
                h_root = self.hash_password("toor")
                h_user = self.hash_password("operator")
                conn.execute("INSERT OR REPLACE INTO sys_auth VALUES ('root', ?, 'root', 'OP_SEC_SALT_2026')", (h_root,))
                conn.execute("INSERT OR REPLACE INTO sys_auth VALUES ('operator', ?, 'user', 'OP_SEC_SALT_2026')", (h_user,))
                conn.commit()

        # Seed initial secret vault entries (AES/SHA simulated storage)
        self.store_secret("NET_GATEWAY_TOKEN", "op_sec_token_99a8b1c4e2")
        self.store_secret("STORAGE_CRYPTO_KEY", "opfs_aes256_k_881928371")

    def authenticate(self, username: str, password: str) -> bool:
        pass_hash = self.hash_password(password)
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT role FROM sys_auth WHERE username = ? AND pass_hash = ?", (username, pass_hash)).fetchone()
            if row:
                self.current_user = username
                self.current_role = row[0]
                return True
        return False

    def can_access(self, target_path: str, mode: str = "read") -> bool:
        if self.current_role == "root":
            return True
        # Enforce basic UNIX-style ACL
        if target_path.startswith("/root") or target_path.startswith("/etc/shadow"):
            return False
        return True

    def app_has_permission(self, app_id: str, cap: str) -> bool:
        caps = self.app_sandboxes.get(app_id, [])
        return cap in caps

    def store_secret(self, key: str, value: str):
        self.secrets_vault[key] = hashlib.sha256(value.encode()).hexdigest()

    def get_firewall_rules(self) -> List[dict]:
        return self.firewall_rules

    def add_firewall_rule(self, action: str, proto: str, port: int, desc: str):
        rule_id = len(self.firewall_rules) + 1
        self.firewall_rules.append({"id": rule_id, "action": action.upper(), "proto": proto.upper(), "port": port, "desc": desc})
