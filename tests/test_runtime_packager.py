import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from install.runtime_packager import LOVE_RUNTIME_DLLS, package_runtime
from integrations import rclone_drive
from storage import storage_manager


class RuntimePackagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()
        self.os_root = self.root / "storage" / "operator_os_root"
        self.games = self.os_root / "Users" / "operator" / "home" / "Games"
        self.games.mkdir(parents=True)
        (self.games / "TestGame.exe").write_bytes(b"game")
        self.source = self.root / "apps"
        self.source.mkdir()
        (self.source / "__init__.py").write_text("", encoding="utf-8")
        (self.source / "sample.py").write_text("VALUE = 42\n", encoding="utf-8")
        (self.root / "boot.py").write_text("print('packaged boot')\n", encoding="utf-8")
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for name in (
            "atlas_service_runtime.dll",
            "kernel_guard.exe",
            "operator_kernel.exe",
            "powcurl.exe",
        ):
            (self.bin_dir / name).write_bytes(name.encode())
        self.java_bin = self.root / "runtime_java" / "bin"
        self.java_bin.mkdir(parents=True)
        (self.java_bin / "Runtime.class").write_bytes(b"class")
        self.rclone = self.root / "downloads" / "rclone.exe"
        self.rclone.parent.mkdir()
        self.rclone.write_bytes(b"rclone")
        self.distributions = self.root / "distributions"
        distribution = self.distributions / "TestGame" / "dist"
        distribution.mkdir(parents=True)
        for name in LOVE_RUNTIME_DLLS:
            (distribution / name).write_bytes(name.encode())

    def test_packager_stages_bytecode_rclone_and_game_runtime(self):
        package_runtime(self.root, self.rclone, self.distributions)
        system = self.os_root / "System"

        self.assertTrue((system / "apps" / "sample.pyc").is_file())
        self.assertFalse((system / "apps" / "sample.py").exists())
        self.assertEqual((system / "bin" / "rclone.exe").read_bytes(), b"rclone")
        self.assertEqual(
            (system / "runtime_java" / "bin" / "Runtime.class").read_bytes(),
            b"class",
        )
        manifest = json.loads(
            (system / "runtime_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["entrypoint"], "boot.pyc")
        self.assertTrue(manifest["python_bytecode_only"])
        for name in LOVE_RUNTIME_DLLS:
            self.assertTrue((self.games / name).is_file())

        result = subprocess.run(
            [sys.executable, str(system / "boot.pyc")],
            cwd=system,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("packaged boot", result.stdout)

    def test_rclone_lookup_falls_back_to_staged_runtime(self):
        packaged = self.root / "storage" / "operator_os_root" / "System" / "bin"
        packaged.mkdir(parents=True)
        executable = packaged / "rclone.exe"
        executable.write_bytes(b"rclone")
        with (
            patch.object(rclone_drive, "ROOT_DIR", self.root),
            patch("integrations.rclone_drive.shutil.which", return_value=None),
        ):
            self.assertEqual(
                rclone_drive.RcloneDriveManager._find_rclone(),
                str(executable),
            )

    def test_storage_usage_counts_virtual_tree_files(self):
        user_file = self.os_root / "Users" / "operator" / "home" / "note.txt"
        user_file.parent.mkdir(parents=True, exist_ok=True)
        user_file.write_bytes(b"12345")
        manager = object.__new__(storage_manager.OperatorStorageManager)
        with patch.object(storage_manager, "OS_ROOT_PATH", self.os_root):
            info = manager.get_disk_info()
        self.assertEqual(info["used_bytes"], 9)
        self.assertEqual(
            info["free_bytes"],
            storage_manager.TOTAL_STORAGE_BYTES - 9,
        )


if __name__ == "__main__":
    unittest.main()
