#!/usr/bin/env python3
"""Install the Operator OS host subsystem for the current user."""

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
import venv
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent
MINIMUM_PYTHON = (3, 10)
_EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
    "venv",
}
_EXCLUDED_FILES = {
    ".db",
    ".img",
    ".pyc",
    ".pyo",
    ".dll",
    ".exe",
    ".o",
    ".a",
    ".lib",
    ".so",
    ".dylib",
    ".class",
}


def user_data_directory(
    platform_name: str | None = None,
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)

    if platform_name == "win32":
        base = environ.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / "OperatorOS"
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / "OperatorOS"
    if platform_name.startswith("linux"):
        base = environ.get("XDG_DATA_HOME")
        return (Path(base) if base else home / ".local" / "share") / "operator-os"
    raise ValueError(
        f"Unsupported operating system {platform_name!r}; "
        "supported hosts are Windows, macOS, and Linux."
    )


def _ignore_project_files(directory: str, names: list[str]) -> set[str]:
    current = Path(directory)
    ignored = {
        name
        for name in names
        if name in _EXCLUDED_DIRECTORIES
        or Path(name).suffix.lower() in _EXCLUDED_FILES
        or name.endswith(".WebView2")
    }
    if current.name == "storage":
        ignored.update(
            name
            for name in names
            if name
            in {
                "operator_os_root",
                "operator_storage_2gb.img",
                "storage_metadata.json",
                "opfs_history.journal",
                "logs",
                "restore_points",
                "crash_reports",
            }
        )
    return ignored


def _python_in_environment(environment: Path) -> Path:
    executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return environment / executable


def _write_launchers(install_dir: Path, data_dir: Path, environment: Path) -> Path:
    launcher = data_dir / "launch.py"
    launcher.write_text(
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        f"APP_DIR = Path({str(install_dir)!r})\n"
        f"DATA_DIR = Path({str(data_dir)!r})\n"
        "storage_dir = DATA_DIR / 'storage'\n"
        "env = os.environ.copy()\n"
        "env['OPERATOR_STORAGE_ROOT_PATH'] = str(storage_dir)\n"
        "env['OPERATOR_OS_ROOT_PATH'] = str(storage_dir / 'operator_os_root')\n"
        "env['OPERATOR_STORAGE_IMAGE'] = str(storage_dir / 'operator_storage_2gb.img')\n"
        "raise SystemExit(subprocess.call(\n"
        "    [sys.executable, str(APP_DIR / 'boot.py'), *sys.argv[1:]],\n"
        "    cwd=APP_DIR,\n"
        "    env=env,\n"
        "))\n",
        encoding="utf-8",
    )

    python = _python_in_environment(environment)
    if os.name == "nt":
        command_file = data_dir / "OperatorOS.cmd"
        command_file.write_text(
            f'@"{python}" "{launcher}" %*\n',
            encoding="utf-8",
        )
    else:
        command_file = data_dir / "operator-os"
        command_file.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(str(python))} {shlex.quote(str(launcher))} \"$@\"\n",
            encoding="utf-8",
        )
        command_file.chmod(command_file.stat().st_mode | 0o111)
    return command_file


def install_project(
    source_root: Path,
    install_dir: Path,
    data_dir: Path,
    *,
    install_dependencies: bool = True,
) -> Path:
    source_root = Path(source_root).resolve()
    install_dir = Path(install_dir).expanduser().resolve()
    data_dir = Path(data_dir).expanduser().resolve()
    if not (source_root / "boot.py").is_file() or not (
        source_root / "requirements.txt"
    ).is_file():
        raise ValueError(f"{source_root} is not an Operator OS source directory.")
    if (
        source_root == install_dir
        or source_root in install_dir.parents
        or install_dir in source_root.parents
    ):
        raise ValueError("The installation directory must be outside the source directory.")
    if source_root == data_dir or source_root in data_dir.parents:
        raise ValueError("The data directory must be outside the source directory.")
    if data_dir == install_dir or install_dir in data_dir.parents:
        raise ValueError(
            "The data directory must not be inside the application directory."
        )
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        raise RuntimeError(
            f"Python {required} or newer is required; found {platform.python_version()}."
        )

    install_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source_root,
        install_dir,
        dirs_exist_ok=True,
        ignore=_ignore_project_files,
    )

    environment = data_dir / "python"
    environment_python = _python_in_environment(environment)
    if not environment_python.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    if install_dependencies:
        subprocess.run(
            [
                str(environment_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(install_dir / "requirements.txt"),
            ],
            cwd=install_dir,
            check=True,
        )

    storage_dir = data_dir / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_env = os.environ.copy()
    storage_env["OPERATOR_STORAGE_ROOT_PATH"] = str(storage_dir)
    storage_env["OPERATOR_OS_ROOT_PATH"] = str(storage_dir / "operator_os_root")
    storage_env["OPERATOR_STORAGE_IMAGE"] = str(
        storage_dir / "operator_storage_2gb.img"
    )
    subprocess.run(
        [
            str(environment_python),
            "-c",
            "from storage.storage_manager import OperatorStorageManager; "
            "OperatorStorageManager()",
        ],
        cwd=install_dir,
        env=storage_env,
        check=True,
    )
    return _write_launchers(install_dir, data_dir, environment)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install Operator OS as a user-level host subsystem."
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        help="Application directory (defaults to the current user's data directory).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Persistent storage and Python environment directory.",
    )
    parser.add_argument(
        "--skip-dependencies",
        action="store_true",
        help="Do not download Python dependencies (for offline/test use only).",
    )
    args = parser.parse_args(argv)
    if sys.version_info < MINIMUM_PYTHON:
        print(
            f"[INSTALL ERROR] Python {'.'.join(map(str, MINIMUM_PYTHON))} or newer "
            f"is required; found {platform.python_version()}.",
            file=sys.stderr,
        )
        return 1

    try:
        user_root = user_data_directory()
        install_dir = args.install_dir or user_root / "app"
        data_dir = args.data_dir or user_root
        command_file = install_project(
            SOURCE_ROOT,
            install_dir,
            data_dir,
            install_dependencies=not args.skip_dependencies,
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[INSTALL ERROR] {exc}", file=sys.stderr)
        return 1

    print("[INSTALL] Operator OS is installed for this user.")
    print(f"[INSTALL] Application: {install_dir}")
    print(f"[INSTALL] Persistent storage: {data_dir / 'storage'}")
    print(f"[INSTALL] Launcher: {command_file}")
    if args.skip_dependencies:
        print(
            "[INSTALL] Python dependencies were skipped; install requirements.txt "
            "in the private environment before launching."
        )
    print("[INSTALL] Run the launcher to start Operator OS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
