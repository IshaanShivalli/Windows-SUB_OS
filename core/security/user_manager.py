#!/usr/bin/env python3
"""
Atlas OS Multi-User Management Subsystem
Handles user creation, deletion, authentication, session switching,
automatic memory allocation, and folder hierarchy provisioning.
"""

import sqlite3
import hashlib
import hmac
import secrets
import time
from contextlib import closing
from pathlib import Path
from typing import List, Dict, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"

from storage.storage_manager import OperatorStorageManager
from core.memory.user_memory_manager import UserMemoryManager


class UserManager:
    _instance = None
    PASSD_HASH_ITERATIONS = 310_000

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UserManager, cls).__new__(cls)
            cls._instance.init_user_manager()
        return cls._instance

    def init_user_manager(self):
        self.storage = OperatorStorageManager()
        self.memory = UserMemoryManager()
        self.active_user = "operator"
        self.active_role = "user"
        self.init_db_tables()

    def hash_password(self, password: str, salt: str = "OP_SEC_SALT_2026") -> str:
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    def init_db_tables(self):
        if not DB_PATH.exists():
            return
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sys_users (
                    uid INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    shell TEXT DEFAULT '/bin/opshell',
                    home_dir TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    memory_mb INTEGER NOT NULL DEFAULT 1024,
                    quota_mb INTEGER NOT NULL DEFAULT 256,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sys_auth (
                    username TEXT PRIMARY KEY,
                    pass_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    salt TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sys_passd_auth (
                    username TEXT PRIMARY KEY,
                    pass_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    iterations INTEGER NOT NULL
                );
            """)

            # Ensure columns exist if older schema
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(sys_users);")
            cols = [c[1] for c in cursor.fetchall()]
            if "memory_mb" not in cols:
                conn.execute("ALTER TABLE sys_users ADD COLUMN memory_mb INTEGER NOT NULL DEFAULT 1024;")
            if "quota_mb" not in cols:
                conn.execute("ALTER TABLE sys_users ADD COLUMN quota_mb INTEGER NOT NULL DEFAULT 256;")

            # Seed default users
            conn.execute("""
                INSERT OR IGNORE INTO sys_users (uid, username, shell, home_dir, role, memory_mb, quota_mb)
                VALUES (0, 'root', '/bin/opshell', '/Users/root/home', 'root', 2048, 1024);
            """)
            conn.execute("""
                INSERT OR IGNORE INTO sys_users (uid, username, shell, home_dir, role, memory_mb, quota_mb)
                VALUES (1000, 'operator', '/bin/opshell', '/Users/operator/home', 'user', 1024, 512);
            """)
            conn.execute(
                "INSERT OR IGNORE INTO sys_auth VALUES ('root', ?, 'root', 'OP_SEC_SALT_2026')",
                (self.hash_password("toor"),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO sys_auth VALUES ('operator', ?, 'user', 'OP_SEC_SALT_2026')",
                (self.hash_password("operator"),),
            )
            conn.commit()

        # Ensure their storage trees exist in the 2GB virtual storage
        self.storage.create_user_hierarchy("operator")
        self.storage.create_user_hierarchy("root")

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        memory_mb: Optional[int] = None,
        quota_mb: int = 512
    ) -> Tuple[bool, str]:
        """
        Creates a new user, automatically allocates memory, provisions directory tree,
        and saves credentials to system registry.
        """
        username = username.strip().lower()
        if not username or not username.isalnum():
            return False, "Username must contain alphanumeric characters only."

        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute("SELECT username FROM sys_users WHERE username = ?", (username,)).fetchone()
            if existing:
                return False, f"User '{username}' already exists in Atlas OS registry."

            # Automatically allocate dedicated memory for the user
            allocated_ram = self.memory.allocate_memory_for_user(username, memory_mb, role)
            home_dir = f"/Users/{username}/home"

            # Insert into sys_users and sys_auth
            conn.execute("""
                INSERT INTO sys_users (username, shell, home_dir, role, memory_mb, quota_mb)
                VALUES (?, '/bin/opshell', ?, ?, ?, ?)
            """, (username, home_dir, role, allocated_ram, quota_mb))

            pass_hash = self.hash_password(password)
            conn.execute("""
                INSERT OR REPLACE INTO sys_auth (username, pass_hash, role, salt)
                VALUES (?, ?, ?, 'OP_SEC_SALT_2026')
            """, (username, pass_hash, role))
            conn.commit()

        # Automatically provision the required folder hierarchy in 2GB storage
        self.storage.create_user_hierarchy(username)

        return True, f"User '{username}' created successfully with {allocated_ram} MB dedicated RAM and home '{home_dir}'."

    def delete_user(self, username: str, requesting_user: str = "operator") -> Tuple[bool, str]:
        """Deletes a user, reclaims their memory, and removes their storage tree."""
        username = username.strip().lower()
        if username in ("root", "operator"):
            return False, f"Cannot delete critical system user '{username}'."
        if username == self.active_user:
            return False, "Cannot delete the currently logged-in user session."

        with sqlite3.connect(DB_PATH) as conn:
            user_row = conn.execute("SELECT username FROM sys_users WHERE username = ?", (username,)).fetchone()
            if not user_row:
                return False, f"User '{username}' does not exist."

            conn.execute("DELETE FROM sys_users WHERE username = ?", (username,))
            conn.execute("DELETE FROM sys_auth WHERE username = ?", (username,))
            conn.commit()

        # Deallocate memory and storage
        self.memory.deallocate_user_memory(username)
        self.storage.delete_user_hierarchy(username)

        return True, f"User '{username}' deleted and {username}'s allocated resources reclaimed."

    def authenticate(self, username: str, password: str) -> bool:
        username = username.strip().lower()
        pass_hash = self.hash_password(password)
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT role FROM sys_auth WHERE username = ? AND pass_hash = ?", (username, pass_hash)).fetchone()
            if row:
                self.active_user = username
                self.active_role = row[0]
                return True
        return False

    @staticmethod
    def _validate_passd_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("passd password must be at least 8 characters")
        if len(password) > 1024:
            raise ValueError("passd password must be no longer than 1024 characters")

    @staticmethod
    def _hash_passd_password(password: str, salt: bytes, iterations: int) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        ).hex()

    def has_passd_password(self, username: str) -> bool:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT 1 FROM sys_passd_auth WHERE username = ?",
                (username.strip().lower(),),
            ).fetchone()
        return row is not None

    def set_passd_password(self, username: str, password: str) -> None:
        username = username.strip().lower()
        self._validate_passd_password(password)
        salt = secrets.token_bytes(16)
        iterations = self.PASSD_HASH_ITERATIONS
        pass_hash = self._hash_passd_password(password, salt, iterations)
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sys_passd_auth
                    (username, pass_hash, salt, iterations)
                VALUES (?, ?, ?, ?)
                """,
                (username, pass_hash, salt.hex(), iterations),
            )
            conn.commit()

    def verify_passd_password(self, username: str, password: str) -> bool:
        username = username.strip().lower()
        with closing(sqlite3.connect(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT pass_hash, salt, iterations FROM sys_passd_auth WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return False
        expected, encoded_salt, iterations = row
        if not 100_000 <= iterations <= 2_000_000:
            raise ValueError("Invalid passd password hash configuration")
        actual = self._hash_passd_password(password, bytes.fromhex(encoded_salt), iterations)
        return hmac.compare_digest(actual, expected)

    def list_users(self) -> List[dict]:
        self.init_db_tables()
        users = []
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT uid, username, role, home_dir, memory_mb, quota_mb, created_at
                FROM sys_users ORDER BY uid ASC
            """).fetchall()
            for r in rows:
                u_name = r[1]
                mem_info = self.memory.get_user_memory(u_name)
                users.append({
                    "uid": r[0],
                    "username": u_name,
                    "role": r[2],
                    "home_dir": r[3],
                    "memory_mb": mem_info["allocated_mb"],
                    "used_mb": mem_info["used_mb"],
                    "quota_mb": r[5],
                    "created_at": r[6],
                    "is_active": (u_name == self.active_user)
                })
        return users

    def get_user(self, username: str) -> Optional[dict]:
        username = username.strip().lower()
        with sqlite3.connect(DB_PATH) as conn:
            r = conn.execute("""
                SELECT uid, username, role, home_dir, memory_mb, quota_mb, created_at
                FROM sys_users WHERE username = ?
            """, (username,)).fetchone()
            if r:
                mem_info = self.memory.get_user_memory(r[1])
                return {
                    "uid": r[0],
                    "username": r[1],
                    "role": r[2],
                    "home_dir": r[3],
                    "memory_mb": mem_info["allocated_mb"],
                    "used_mb": mem_info["used_mb"],
                    "quota_mb": r[5],
                    "created_at": r[6]
                }
        return None
