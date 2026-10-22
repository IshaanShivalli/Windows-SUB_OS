"""Stage a compiled, modular Operator runtime inside the virtual OS storage tree."""

import compileall
import json
import os
import platform
import shutil
import sys
import uuid
from pathlib import Path


RUNTIME_DIRECTORIES = (
    "apps",
    "boot_target",
    "core",
    "db",
    "integrations",
    "install",
    "network",
    "packages",
    "pow",
    "shell",
    "storage",
)
NATIVE_SOURCE_SUFFIXES = {
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".rs",
    ".toml",
}
LOVE_RUNTIME_DLLS = (
    "love.dll",
    "lua51.dll",
    "mpg123.dll",
    "msvcp120.dll",
    "msvcr120.dll",
    "OpenAL32.dll",
    "SDL2.dll",
)
REQUIRED_BINARIES = (
    "atlas_service_runtime.dll",
    "kernel_guard.exe",
    "operator_kernel.exe",
    "powcurl.exe",
)


def _ignore_runtime_files(directory, names):
    ignored = {
        name
        for name in names
        if name in {"__pycache__", ".pytest_cache", "target"}
    }
    current = Path(directory)
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
    if current.name == "db":
        ignored.update(name for name in names if name.endswith(".db"))
    if current.name == "bin":
        return ignored
    ignored.update(
        name
        for name in names
        if Path(name).suffix.lower() in NATIVE_SOURCE_SUFFIXES
    )
    return ignored


def _stage_runtime_sources(root_dir, staging, binary_dir, java_bin):
    for name in ("boot.py", "atlas.py", "requirements.txt", "LICENSE"):
        source = root_dir / name
        if source.is_file():
            shutil.copy2(source, staging / name)

    for name in RUNTIME_DIRECTORIES:
        source = root_dir / name
        if source.is_dir():
            shutil.copytree(
                source,
                staging / name,
                ignore=_ignore_runtime_files,
            )

    shutil.copytree(binary_dir, staging / "bin")
    if java_bin.is_dir():
        (staging / "runtime_java").mkdir(parents=True, exist_ok=True)
        shutil.copytree(java_bin, staging / "runtime_java" / "bin")


def _stage_game_runtimes(os_root, distributions_root):
    games_roots = sorted(
        os_root.glob("Users/*/home/Games"),
        key=lambda path: str(path).casefold(),
    )
    for games_root in games_roots:
        for executable in games_root.glob("*.exe"):
            distribution = distributions_root / executable.stem / "dist"
            missing = [
                name
                for name in LOVE_RUNTIME_DLLS
                if not (executable.parent / name).is_file()
            ]
            if not missing:
                continue
            if not distribution.is_dir():
                raise FileNotFoundError(
                    f"Missing LÖVE runtime distribution for {executable.name}: "
                    f"{distribution}"
                )
            unavailable = [
                name for name in missing if not (distribution / name).is_file()
            ]
            if unavailable:
                raise FileNotFoundError(
                    f"LÖVE runtime for {executable.name} is missing: "
                    f"{', '.join(unavailable)}"
                )
            for name in missing:
                shutil.copy2(distribution / name, executable.parent / name)


def _write_runtime_manifest(staging):
    manifest = {
        "format_version": 1,
        "entrypoint": "boot.pyc",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_bytecode_only": True,
        "components": {
            "kernel": [
                "bin/operator_kernel.exe",
                "bin/kernel_guard.exe",
            ],
            "shell": ["shell", "apps"],
            "services": [
                "core/services",
                "bin/atlas_service_runtime.dll",
            ],
            "network": ["network"],
            "storage": ["storage"],
            "installer": ["install"],
            "java": ["runtime_java/bin"],
            "media": ["bin/powcurl.exe"],
            "google_drive": ["bin/rclone.exe"],
        },
    }
    (staging / "runtime_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def _install_staged_runtime(os_root, staging):
    destination = os_root / "System"
    previous = os_root / ".System-previous"
    if previous.exists():
        shutil.rmtree(previous)
    if destination.exists():
        os.replace(destination, previous)
    try:
        os.replace(staging, destination)
    except OSError:
        if previous.exists() and not destination.exists():
            os.replace(previous, destination)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def package_runtime(
    root_dir,
    rclone_executable,
    distributions_root=None,
    *,
    binary_dir=None,
    java_bin=None,
):
    root_dir = Path(root_dir).resolve()
    rclone_executable = Path(rclone_executable).resolve()
    if not rclone_executable.is_file():
        raise FileNotFoundError(f"rclone executable was not found: {rclone_executable}")

    bin_dir = Path(binary_dir) if binary_dir is not None else root_dir / "bin"
    java_bin = (
        Path(java_bin)
        if java_bin is not None
        else root_dir / "runtime_java" / "bin"
    )
    missing_binaries = [
        name for name in REQUIRED_BINARIES if not (bin_dir / name).is_file()
    ]
    if missing_binaries:
        raise FileNotFoundError(
            "Cannot package runtime; required built binaries are missing: "
            + ", ".join(missing_binaries)
        )
    if not java_bin.is_dir():
        raise FileNotFoundError(f"Java runtime classes were not built: {java_bin}")

    os_root = root_dir / "storage" / "operator_os_root"
    os_root.mkdir(parents=True, exist_ok=True)
    staging = os_root / f".System-staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        _stage_runtime_sources(root_dir, staging, bin_dir, java_bin)
        shutil.copy2(rclone_executable, staging / "bin" / "rclone.exe")

        if not compileall.compile_dir(staging, force=True, quiet=1, legacy=True):
            raise RuntimeError(f"Python bytecode compilation failed in {staging}")
        for source in staging.rglob("*.py"):
            source.unlink()
        for cache in staging.rglob("__pycache__"):
            shutil.rmtree(cache)

        distributions_root = (
            Path(distributions_root)
            if distributions_root is not None
            else root_dir.parent.parent / "CS50 2D"
        )
        _stage_game_runtimes(os_root, distributions_root)
        _write_runtime_manifest(staging)
        _install_staged_runtime(os_root, staging)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    print(f"[BUILD] Packaged modular runtime at {os_root / 'System'}")
    print(f"[BUILD] Included rclone from {rclone_executable}")
