import time
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from storage.storage_manager import OperatorStorageManager

STORAGE_DIR = Path(__file__).resolve().parent.parent

class VFSNode:
    def __init__(self, path: str, is_dir: bool = False, owner: str = "root", perms: str = "rwxr-xr-x"):
        self.path = path
        self.is_dir = is_dir
        self.owner = owner
        self.perms = perms
        self.created = time.time()
        self.size = 0

class VirtualFileSystem:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VirtualFileSystem, cls).__new__(cls)
            cls._instance.init_vfs()
        return cls._instance

    def init_vfs(self):
        VFS_ROOT = OperatorStorageManager().get_os_root()
        self.vfs_root = VFS_ROOT
        VFS_ROOT.mkdir(parents=True, exist_ok=True)
        self.mount_table: Dict[str, str] = {
            "/": str(VFS_ROOT),
            "/dev": str(STORAGE_DIR / "dev"),
            "/etc": str(VFS_ROOT / "etc"),
            "/home": str(VFS_ROOT / "home"),
            "/var/log": str(VFS_ROOT / "var_log")
        }
        for p in self.mount_table.values():
            Path(p).mkdir(parents=True, exist_ok=True)

        # Seed essential VFS virtual nodes
        (VFS_ROOT / "etc" / "hostname").write_text("operator-core-node\n", encoding="utf-8")
        (VFS_ROOT / "etc" / "os-release").write_text("NAME=Operator OS\nVERSION=2.0-PRO\nID=operator\n", encoding="utf-8")
        (VFS_ROOT / "var_log" / "syslog").write_text(f"[{time.ctime()}] VFS initialized with journaled blocks.\n", encoding="utf-8")

    def resolve_path(self, virtual_path: str) -> Path:
        virtual_path = virtual_path.replace("\\", "/")
        if not virtual_path.startswith("/"):
            virtual_path = "/" + virtual_path
        # Map root
        candidate = (self.vfs_root / virtual_path.lstrip("/")).resolve()
        if candidate != self.vfs_root and self.vfs_root not in candidate.parents:
            raise ValueError("VFS path escapes the Operator OS storage root")
        return candidate

    def mount(self, target: str, source: str) -> str:
        self.mount_table[target] = source
        return f"[VFS] Mounted '{source}' at '{target}'"

    def list_mounts(self) -> Dict[str, str]:
        return self.mount_table

    def copy(self, src: str, dst: str) -> str:
        s_path = self.resolve_path(src)
        d_path = self.resolve_path(dst)
        if not s_path.exists():
            return f"\033[31m[VFS ERR] Source '{src}' not found.\033[0m"
        if s_path.is_dir():
            shutil.copytree(s_path, d_path, dirs_exist_ok=True)
        else:
            d_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s_path, d_path)
        return f"\033[1;32m[VFS OK]\033[0m Copied '{src}' -> '{dst}'"

    def move(self, src: str, dst: str) -> str:
        s_path = self.resolve_path(src)
        d_path = self.resolve_path(dst)
        if not s_path.exists():
            return f"\033[31m[VFS ERR] Source '{src}' not found.\033[0m"
        d_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s_path), str(d_path))
        return f"\033[1;32m[VFS OK]\033[0m Moved '{src}' -> '{dst}'"

    def delete(self, path: str) -> str:
        t_path = self.resolve_path(path)
        if not t_path.exists():
            return f"\033[31m[VFS ERR] Target '{path}' not found.\033[0m"
        if t_path.is_dir():
            shutil.rmtree(t_path)
        else:
            t_path.unlink()
        return f"\033[1;33m[VFS OK]\033[0m Deleted '{path}'"

    def list_dir(self, v_path: str = "/") -> List[dict]:
        target = self.resolve_path(v_path)
        if not target.exists() or not target.is_dir():
            return []
        items = []
        for child in target.iterdir():
            items.append({
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 4096,
                "perms": "drwxr-xr-x" if child.is_dir() else "-rw-r--r--",
                "owner": "root"
            })
        return items
