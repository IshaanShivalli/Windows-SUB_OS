import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from install import installer


class PortableInstallerTests(unittest.TestCase):
    def test_user_data_directory_uses_platform_conventions(self):
        home = Path("C:/Users/example")
        self.assertEqual(
            installer.user_data_directory(
                "win32",
                environ={"LOCALAPPDATA": "C:/Users/example/AppData/Local"},
                home=home,
            ),
            Path("C:/Users/example/AppData/Local/OperatorOS"),
        )
        self.assertEqual(
            installer.user_data_directory("darwin", environ={}, home=home),
            home / "Library" / "Application Support" / "OperatorOS",
        )
        self.assertEqual(
            installer.user_data_directory(
                "linux",
                environ={"XDG_DATA_HOME": "/tmp/operator-data"},
                home=home,
            ),
            Path("/tmp/operator-data/operator-os"),
        )

    def test_install_copies_source_skips_host_binaries_and_writes_launcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "boot.py").write_text("pass\n", encoding="utf-8")
            (source / "requirements.txt").write_text("", encoding="utf-8")
            (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            (source / "native.exe").write_bytes(b"windows binary")
            (source / "target").mkdir()
            (source / "target" / "build.bin").write_bytes(b"build output")
            install_dir = root / "installed" / "app"
            data_dir = root / "installed" / "data"
            environment = data_dir / "python"
            python = environment / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )

            def create_environment(_builder, _environment):
                python.parent.mkdir(parents=True)
                python.write_bytes(b"python")

            with (
                patch.object(installer.venv.EnvBuilder, "create", create_environment),
                patch.object(installer.subprocess, "run") as run,
                patch.object(installer.sys, "version_info", (3, 11)),
            ):
                launcher = installer.install_project(
                    source,
                    install_dir,
                    data_dir,
                    install_dependencies=False,
                )

            self.assertTrue((install_dir / "module.py").is_file())
            self.assertFalse((install_dir / "native.exe").exists())
            self.assertFalse((install_dir / "target").exists())
            self.assertTrue((data_dir / "launch.py").is_file())
            self.assertTrue((data_dir / "storage").is_dir())
            self.assertTrue(launcher.is_file())
            self.assertTrue(launcher.name in {"OperatorOS.cmd", "operator-os"})
            self.assertEqual(run.call_count, 1)
            self.assertEqual(
                run.call_args.kwargs["env"]["OPERATOR_STORAGE_ROOT_PATH"],
                str(data_dir / "storage"),
            )

    def test_install_rejects_destination_inside_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "boot.py").write_text("", encoding="utf-8")
            (source / "requirements.txt").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "outside the source"):
                installer.install_project(
                    source,
                    source / "installed",
                    Path(temporary) / "data",
                    install_dependencies=False,
                )

    def test_install_rejects_data_inside_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "boot.py").write_text("", encoding="utf-8")
            (source / "requirements.txt").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "data directory"):
                installer.install_project(
                    source,
                    root / "installed",
                    root / "installed" / "storage",
                    install_dependencies=False,
                )


if __name__ == "__main__":
    unittest.main()
