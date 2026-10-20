#!/usr/bin/env python3
"""
Atlas OS Automatic User Memory Management Subsystem
Tracks, partitions, and allocates virtual memory slices per user.
Enforces memory boundaries and quotas across the multi-user environment.
"""

import sqlite3
import os
import ctypes
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"

# Total virtual system memory telemetry
TOTAL_SYSTEM_MEMORY_MB = 8192  # 8.00 GB
KERNEL_RESERVED_MEMORY_MB = 1024  # 1.00 GB Kernel Reserve
PAGE_SIZE_KB = 4  # 4 KB virtual pages


class UserMemoryManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UserMemoryManager, cls).__new__(cls)
            cls._instance.init_memory_manager()
        return cls._instance

    def init_memory_manager(self):
        self.total_memory_mb = TOTAL_SYSTEM_MEMORY_MB
        self.kernel_reserved_mb = KERNEL_RESERVED_MEMORY_MB
        self.user_allocations: Dict[str, int] = {}
        self.user_usage: Dict[str, int] = {}
        self.sync_with_db()

    def sync_with_db(self):
        """Load user memory allocations from SQLite sys_users table."""
        if not DB_PATH.exists():
            # Seed defaults
            self.user_allocations["root"] = 2048
            self.user_allocations["operator"] = 1024
            self.user_usage["root"] = 180
            self.user_usage["operator"] = 96
            return

        try:
            with sqlite3.connect(DB_PATH) as conn:
                # Ensure memory_mb column exists
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(sys_users);")
                cols = [c[1] for c in cursor.fetchall()]
                if "memory_mb" not in cols:
                    conn.execute("ALTER TABLE sys_users ADD COLUMN memory_mb INTEGER NOT NULL DEFAULT 1024;")
                    conn.commit()

                rows = conn.execute("SELECT username, memory_mb, role FROM sys_users").fetchall()
                for r in rows:
                    u, m, role = r[0], r[1], r[2]
                    alloc = m if m and m > 0 else (2048 if role == "root" else 1024)
                    self.user_allocations[u] = alloc
                    self.user_usage[u] = 120 if role == "root" else 64
        except Exception:
            self.user_allocations["root"] = 2048
            self.user_allocations["operator"] = 1024

    def get_unallocated_pool_mb(self) -> int:
        total_allocated = self.kernel_reserved_mb + sum(self.user_allocations.values())
        return max(256, self.total_memory_mb - total_allocated)

    def allocate_memory_for_user(self, username: str, requested_mb: Optional[int] = None, role: str = "user") -> int:
        """
        Automatically compute and dedicate a virtual memory slice for a newly created or active user.
        """
        unallocated = self.get_unallocated_pool_mb()
        if requested_mb is not None and requested_mb > 0:
            alloc_mb = min(requested_mb, unallocated)
        else:
            # Automatic heuristic allocation:
            if role == "root":
                alloc_mb = min(2048, max(512, unallocated // 2))
            else:
                alloc_mb = min(1024, max(256, unallocated // 4))

        self.user_allocations[username] = alloc_mb
        self.user_usage[username] = 32  # Initial base shell footprint

        # Persist to database if present
        if DB_PATH.exists():
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE sys_users SET memory_mb = ? WHERE username = ?", (alloc_mb, username))
                    conn.commit()
            except Exception:
                pass

        return alloc_mb

    def deallocate_user_memory(self, username: str):
        if username in self.user_allocations:
            del self.user_allocations[username]
        if username in self.user_usage:
            del self.user_usage[username]

    def get_user_memory(self, username: str) -> dict:
        alloc_mb = self.user_allocations.get(username, 1024)
        used_mb = self.user_usage.get(username, 48)
        free_mb = max(0, alloc_mb - used_mb)
        pct = round((used_mb / max(1, alloc_mb)) * 100, 1)
        pages = (alloc_mb * 1024) // PAGE_SIZE_KB

        return {
            "username": username,
            "allocated_mb": alloc_mb,
            "used_mb": used_mb,
            "free_mb": free_mb,
            "usage_pct": pct,
            "virtual_pages": pages,
            "page_size_kb": PAGE_SIZE_KB,
            "status": "NORMAL" if pct < 85 else "HIGH_LOAD"
        }

    def record_usage(self, username: str, delta_mb: int):
        alloc = self.user_allocations.get(username, 1024)
        cur = self.user_usage.get(username, 48)
        new_val = max(16, min(alloc, cur + delta_mb))
        self.user_usage[username] = new_val

    def get_system_summary(self) -> dict:
        total_user_alloc = sum(self.user_allocations.values())
        total_used = self.kernel_reserved_mb + sum(self.user_usage.values())
        return {
            "total_system_mb": self.total_memory_mb,
            "kernel_reserved_mb": self.kernel_reserved_mb,
            "user_allocated_mb": total_user_alloc,
            "unallocated_free_mb": max(0, self.total_memory_mb - (self.kernel_reserved_mb + total_user_alloc)),
            "active_users_count": len(self.user_allocations)
        }

    @staticmethod
    def get_host_memory_summary() -> dict[str, int | str | None]:
        """Read physical RAM and page-file/swap totals from the host OS."""
        swap_error = None
        if os.name == "nt":
            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            total = status.ullTotalPhys
            available = status.ullAvailPhys
            free = available
            pagefile_script = (
                "$p=@(Get-CimInstance Win32_PageFileUsage -ErrorAction Stop); "
                "[pscustomobject]@{"
                "TotalMB=[long](($p | Measure-Object -Property AllocatedBaseSize -Sum).Sum);"
                "UsedMB=[long](($p | Measure-Object -Property CurrentUsage -Sum).Sum)"
                "} | ConvertTo-Json -Compress"
            )
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", pagefile_script],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode:
                    raise OSError(result.stderr.strip() or f"PowerShell exited with status {result.returncode}")
                pagefile = json.loads(result.stdout)
                swap_total = int(pagefile["TotalMB"]) * 1024 * 1024
                swap_used = int(pagefile["UsedMB"]) * 1024 * 1024
                swap_free = max(0, swap_total - swap_used)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                swap_total = swap_used = swap_free = None
                swap_error = f"Page-file telemetry unavailable: {exc}"
        else:
            meminfo = Path("/proc/meminfo")
            if meminfo.exists():
                values = {}
                for line in meminfo.read_text(encoding="ascii").splitlines():
                    key, separator, value = line.partition(":")
                    if separator:
                        values[key] = int(value.strip().split()[0]) * 1024
                total = values["MemTotal"]
                free = values.get("MemFree", 0)
                available = values.get("MemAvailable", values.get("MemFree", 0))
                swap_total = values.get("SwapTotal", 0)
                swap_available = values.get("SwapFree", 0)
                swap_used = max(0, swap_total - swap_available)
            else:
                try:
                    page_size = os.sysconf("SC_PAGE_SIZE")
                    total = page_size * os.sysconf("SC_PHYS_PAGES")
                    free = page_size * os.sysconf("SC_AVPHYS_PAGES")
                    available = free
                except (AttributeError, OSError, ValueError) as exc:
                    raise OSError("Host RAM telemetry is not supported on this platform") from exc
                swap_total = 0
                swap_available = 0
                swap_used = 0
            swap_free = swap_available

        return {
            "total_bytes": total,
            "used_bytes": max(0, total - available),
            "free_bytes": free,
            "available_bytes": available,
            "swap_total_bytes": swap_total,
            "swap_used_bytes": swap_used,
            "swap_free_bytes": swap_free,
            "swap_error": swap_error,
        }
