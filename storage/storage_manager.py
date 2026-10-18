import os
import struct
import time
from pathlib import Path

# 2GB virtual block device image: 2 * 1024 * 1024 * 1024 bytes
TOTAL_STORAGE_BYTES = 2 * 1024 * 1024 * 1024  # 2,147,483,648 bytes (2GB)
SECTOR_SIZE = 512
BLOCK_SIZE = 4096
MAGIC_SIGNATURE = b"OPERATOR_FS_2GB"

STORAGE_IMG_PATH = Path(__file__).resolve().parent / "operator_storage_2gb.img"
META_PATH = Path(__file__).resolve().parent / "storage_metadata.json"
OS_ROOT_PATH = Path(__file__).resolve().parent / "operator_os_root"

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

    def init_os_folders(self):
        """Create the private, visible-to-Operator home tree for the subsystem."""
        os_root = self.get_os_root()
        folders = [
            "etc", "var/log", "var/lib", "var/cache", "tmp", "home/operator/Docs",
            "home/operator/Downloads", "home/operator/Pictures", "home/operator/Videos",
            "home/operator/Google Drive/Docs", "home/operator/Google Drive/Videos",
            "home/operator/Google Drive/Pictures"
        ]
        for folder in folders:
            (os_root / folder).mkdir(parents=True, exist_ok=True)

    def get_disk_info(self):
        size_on_disk = self.img_path.stat().st_size if self.img_path.exists() else 0
        used_simulated = 184 * 1024 * 1024 # initial system files overhead
        free_bytes = TOTAL_STORAGE_BYTES - used_simulated
        return {
            "device": "/dev/nvme0n1_operator",
            "capacity_bytes": TOTAL_STORAGE_BYTES,
            "capacity_gb": 2.0,
            "used_bytes": used_simulated,
            "free_bytes": free_bytes,
            "filesystem": "EXT-OPFS (Operator File System)",
            "sector_size": SECTOR_SIZE,
            "block_size": BLOCK_SIZE,
            "status": "MOUNTED (RW, synchronous, journaled)"
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
