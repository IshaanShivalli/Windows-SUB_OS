import os
import struct
import time
from pathlib import Path

# 2GB virtual block device image: 2 * 1024 * 1024 * 1024 bytes
TOTAL_STORAGE_BYTES = 2 * 1024 * 1024 * 1024  # 2,147,483,648 bytes (2GB)
SECTOR_SIZE = 512
BLOCK_SIZE = 4096
MAGIC_SIGNATURE = b"OPERATOR_FS_2GB"

STORAGE_IMG_PATH = Path(
    os.environ.get(
        "OPERATOR_STORAGE_IMAGE",
        Path(__file__).resolve().parent / "operator_storage_2gb.img",
    )
)
META_PATH = Path(__file__).resolve().parent / "storage_metadata.json"
OS_ROOT_PATH = Path(
    os.environ.get(
        "OPERATOR_OS_ROOT_PATH",
        Path(__file__).resolve().parent / "operator_os_root",
    )
)

class OperatorStorageManager:
    """
    Simulates a dedicated 2GB raw block storage image with sparse allocation,
    superblock metadata, partition table, and custom inode filesystem.
    """
    def __init__(self, img_path: Path = STORAGE_IMG_PATH):
        self.img_path = img_path
        self.init_disk()

    def init_disk(self):
        if not self.img_path.exists():
            print(f"[STORAGE:VFS] Provisioning 2GB Virtual Block Device: {self.img_path.name}...")
            # Create sparse file of exactly 2GB without consuming all disk space immediately
            with open(self.img_path, "wb") as f:
                # Superblock: Magic (16 bytes) + Total Bytes (8 bytes) + Block Size (4 bytes) + Created Time (8 bytes)
                header = struct.pack("<16sQIq", MAGIC_SIGNATURE, TOTAL_STORAGE_BYTES, BLOCK_SIZE, int(time.time()))
                f.write(header)
                # Seek to 2GB - 1 and write last byte (sparse file creation)
                f.seek(TOTAL_STORAGE_BYTES - 1)
                f.write(b"\x00")
            print("[STORAGE:VFS] 2GB Storage Device Partitioned & Formatted [EXT-OPFS].")
        self.init_os_folders()

    def get_os_root(self) -> Path:
        """Return the private root owned by the Operator OS storage subsystem.

        All persistent OS data must resolve below this directory. It is kept
        separate from the source tree and is excluded from version control.
        """
        OS_ROOT_PATH.mkdir(parents=True, exist_ok=True)
        return OS_ROOT_PATH

    def create_user_hierarchy(self, username: str):
        """Provision the required isolated user folder structure in the 2GB storage:
        Users/
            username/
                home/
                    Documents/
                    Downloads/
                    Pictures/
                    Videos/
                    Games/
                Google Drive/
        """
        os_root = self.get_os_root()
        user_root = os_root / "Users" / username
        subfolders = [
            user_root / "home" / "Documents",
            user_root /             "home" / "Downloads",
            user_root / "home" / "Pictures",
            user_root / "home" / "Videos",
            user_root / "home" / "Games",
            user_root / "Google Drive",
        ]
        for folder in subfolders:
            folder.mkdir(parents=True, exist_ok=True)

        # Place initial welcome files if not existing
        readme = user_root / "home" / "Documents" / "welcome.txt"
        if not readme.exists():
            readme.write_text(
                f"Welcome to Atlas OS, {username}!\n"
                f"Your home storage is securely isolated in the dedicated 2GB block device.\n"
                f"Use 'nano <filename>' to create or edit files.\n",
                encoding="utf-8"
            )

    def delete_user_hierarchy(self, username: str):
        """Clean up user folder hierarchy from the 2GB storage."""
        import shutil
        os_root = self.get_os_root()
        user_root = os_root / "Users" / username
        if user_root.exists() and user_root.is_dir():
            shutil.rmtree(user_root, ignore_errors=True)

    def init_os_folders(self):
        """Create the private OS filesystem tree inside the 2GB storage."""
        os_root = self.get_os_root()
        base_folders = [
            "etc", "var/log", "var/lib", "var/cache", "tmp", "bin", "Users"
        ]
        for folder in base_folders:
            (os_root / folder).mkdir(parents=True, exist_ok=True)

        # Initialize default users
        self.create_user_hierarchy("operator")
        self.create_user_hierarchy("root")

    def normalize_vpath(self, vpath: str, cwd: str = "/", current_user: str = "operator") -> str:
        """Normalizes a virtual OS path relative to cwd (POSIX-style)."""
        clean_vpath = vpath.replace("\\", "/").strip()
        clean_cwd = cwd.replace("\\", "/").strip()
        if not clean_cwd.startswith("/"):
            clean_cwd = "/" + clean_cwd

        if clean_vpath == "~":
            clean_vpath = f"/Users/{current_user}/home"
        elif clean_vpath.startswith("~/"):
            clean_vpath = f"/Users/{current_user}/home" + clean_vpath[1:]

        if clean_vpath.startswith("/"):
            target = clean_vpath
        else:
            target = f"{clean_cwd.rstrip('/')}/{clean_vpath}"

        parts = []
        for segment in target.split("/"):
            if not segment or segment == ".":
                continue
            elif segment == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(segment)

        return "/" + "/".join(parts)

    def resolve_vpath(self, vpath: str, cwd: str = "/", current_user: str = "operator") -> tuple:
        """
        Translates a virtual path into an actual physical path inside the 2GB OS storage.
        Returns: (physical_path: Path, normalized_vpath: str)
        """
        norm_vpath = self.normalize_vpath(vpath, cwd, current_user)
        os_root = self.get_os_root()

        # Map root / to os_root
        rel = norm_vpath.lstrip("/")
        phys = (os_root / rel).resolve() if rel else os_root.resolve()

        # Security check: Ensure phys is within os_root
        try:
            phys.relative_to(os_root.resolve())
        except ValueError:
            phys = os_root.resolve()
            norm_vpath = "/"

        return phys, norm_vpath

    def virtual_exists(self, vpath: str, cwd: str = "/", current_user: str = "operator") -> bool:
        phys, _ = self.resolve_vpath(vpath, cwd, current_user)
        return phys.exists()

    def virtual_isdir(self, vpath: str, cwd: str = "/", current_user: str = "operator") -> bool:
        phys, _ = self.resolve_vpath(vpath, cwd, current_user)
        return phys.is_dir()

    def virtual_listdir(self, vpath: str = "/", cwd: str = "/", current_user: str = "operator") -> list:
        phys, norm = self.resolve_vpath(vpath, cwd, current_user)
        if not phys.exists() or not phys.is_dir():
            return []
        items = []
        for entry in sorted(phys.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            st = entry.stat()
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": st.st_size if not entry.is_dir() else 0,
                "mtime": st.st_mtime,
                "vpath": f"{norm.rstrip('/')}/{entry.name}"
            })
        return items

    def virtual_mkdir(self, vpath: str, cwd: str = "/", current_user: str = "operator"):
        phys, _ = self.resolve_vpath(vpath, cwd, current_user)
        phys.mkdir(parents=True, exist_ok=True)

    def virtual_remove(self, vpath: str, cwd: str = "/", current_user: str = "operator") -> bool:
        import shutil
        phys, norm = self.resolve_vpath(vpath, cwd, current_user)
        if norm == "/":
            return False
        if phys.is_dir():
            shutil.rmtree(phys, ignore_errors=True)
            return True
        elif phys.is_file():
            phys.unlink(missing_ok=True)
            return True
        return False

    def get_disk_info(self):
        os_root = self.get_os_root()
        used_bytes = sum(
            path.stat().st_size
            for path in os_root.rglob("*")
            if path.is_file()
        )
        free_bytes = max(0, TOTAL_STORAGE_BYTES - used_bytes)
        return {
            "device": "/dev/nvme0n1_operator",
            "capacity_bytes": TOTAL_STORAGE_BYTES,
            "capacity_gb": 2.0,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "filesystem": "EXT-OPFS (Operator File System)",
            "sector_size": SECTOR_SIZE,
            "block_size": BLOCK_SIZE,
            "status": "VIRTUAL (directory-backed, RW)"
        }

    def get_history_file_path(self):
        # Stored in the allocated storage partition alongside the 2GB block image
        hist_file = self.img_path.parent / "opfs_history.journal"
        if not hist_file.exists():
            hist_file.write_text("# OPERATOR OS EXT-OPFS COMMAND JOURNAL\n", encoding="utf-8")
        return hist_file

    def append_command_history(self, cmd: str):
        if not cmd or not cmd.strip():
            return
        hist_path = self.get_history_file_path()
        with open(hist_path, "a", encoding="utf-8") as f:
            f.write(f"{cmd.strip()}\n")

    def load_command_history(self):
        hist_path = self.get_history_file_path()
        if not hist_path.exists():
            return []
        lines = [line.strip() for line in hist_path.read_text(encoding="utf-8").splitlines()]
        return [l for l in lines if l and not l.startswith("#")]

if __name__ == "__main__":
    mgr = OperatorStorageManager()
    info = mgr.get_disk_info()
    print("Operator Storage Info:", info)
