import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_VFS_BASE = ROOT_DIR / "storage" / "operator_os_root"

class HostFilesystemBridge:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HostFilesystemBridge, cls).__new__(cls)
            cls._instance.init_bridge()
        return cls._instance

    def init_bridge(self):
        DEFAULT_VFS_BASE.mkdir(parents=True, exist_ok=True)
        self.mount_map: Dict[str, Path] = {
            "/": DEFAULT_VFS_BASE,
            "/home/operator": DEFAULT_VFS_BASE / "home" / "operator",
            "/host-storage": ROOT_DIR / "storage"
        }
        for p in self.mount_map.values():
            p.mkdir(parents=True, exist_ok=True)

    def mount_host_folder(self, host_path: str, vfs_mount_point: str) -> str:
        h_path = Path(host_path)
        if not h_path.exists():
            return f"\033[31m[BRIDGE ERR] Host path '{host_path}' does not exist.\033[0m"

        vfs_mount_point = vfs_mount_point.replace("\\", "/")
        if not vfs_mount_point.startswith("/"):
            vfs_mount_point = "/" + vfs_mount_point

        self.mount_map[vfs_mount_point] = h_path.resolve()
        return f"\033[1;32m[BRIDGE OK]\033[0m Mapped host '{h_path.resolve()}' -> VFS '{vfs_mount_point}'"

    def resolve(self, vfs_path: str) -> Path:
        vfs_path = vfs_path.replace("\\", "/")
        if not vfs_path.startswith("/"):
            vfs_path = "/" + vfs_path

        # Match longest mount prefix
        best_prefix = "/"
        for prefix in self.mount_map:
            if vfs_path == prefix or vfs_path.startswith(prefix + "/"):
                if len(prefix) > len(best_prefix):
                    best_prefix = prefix

        rel = vfs_path[len(best_prefix):].lstrip("/")
        return self.mount_map[best_prefix] / rel

    def list_dir(self, vfs_path: str = "/") -> List[dict]:
        target = self.resolve(vfs_path)
        if not target.exists():
            return []
        items = []
        if target.is_dir():
            for child in target.iterdir():
                items.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 4096,
                    "host_path": str(child.resolve())
                })
        return items

    def copy(self, src: str, dst: str) -> str:
        s = self.resolve(src)
        d = self.resolve(dst)
        if not s.exists():
            return f"\033[31m[BRIDGE ERR] Source '{src}' not found.\033[0m"
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        return f"\033[1;32m[BRIDGE OK]\033[0m Copied '{src}' -> '{dst}'"

    def move(self, src: str, dst: str) -> str:
        s = self.resolve(src)
        d = self.resolve(dst)
        if not s.exists():
            return f"\033[31m[BRIDGE ERR] Source '{src}' not found.\033[0m"
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"\033[1;32m[BRIDGE OK]\033[0m Moved '{src}' -> '{dst}'"

    def remove(self, path: str) -> str:
        t = self.resolve(path)
        if not t.exists():
            return f"\033[31m[BRIDGE ERR] Target '{path}' not found.\033[0m"
        if t.is_dir():
            shutil.rmtree(t)
        else:
            t.unlink()
        return f"\033[1;33m[BRIDGE OK]\033[0m Removed '{path}'"
