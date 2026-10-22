#!/usr/bin/env python3
"""
Operator OS Master Bootstrapper (v2.0)
Initializes:
1. SQL System Registry & Packages
2. C Core Kernel & Scheduler
3. Rust Kernel Guard & Safety Bus
4. Inbuilt 2GB Dedicated Block Storage Device
5. Full Networking Subsystem (DNS, Ping, Sockets, Routes)
6. Java OVM Application Runtime
7. Polyglot Script & Shell Subsystem (.sh, .ps1, .bat, .opsh)
"""

import argparse
import json
import os
import platform
import shutil
import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from storage.storage_manager import OperatorStorageManager
from network.net_stack import OperatorNetworkStack

from rich.console import Console

console = Console()


def log(message, style="green"):
    console.print(f"[{style}]{message}[/{style}]")


def run_boot_component(label, command, verbose=False):
    """Run an optional diagnostic component without flooding boot output."""
    executable = shutil.which(command[0]) if not Path(command[0]).is_absolute() else command[0]
    if not executable or (Path(command[0]).is_absolute() and not Path(executable).is_file()):
        log(f"[WARN] {label} skipped: executable not found ({command[0]}).", "yellow")
        return

    try:
        result = subprocess.run(
            [executable, *command[1:]],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"[WARN] {label} could not start: {exc}", "yellow")
        return

    if result.returncode:
        detail = result.stderr.strip().splitlines()
        message = f"[WARN] {label} exited with code {result.returncode}"
        if detail:
            message += f": {detail[0]}"
        log(message, "yellow")
    elif verbose:
        output = result.stdout.strip()
        if output:
            console.print(output)


def _run_shell(shell_py, env):
    process = subprocess.Popen(
        [sys.executable, str(shell_py)],
        cwd=ROOT_DIR,
        env=env,
    )
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            continue


def migrate_database(conn):
    """Bring registries created by earlier Atlas/Operator releases forward."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sys_users'").fetchone()
    if not exists:
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sys_users)")}
    if "memory_mb" not in columns:
        conn.execute("ALTER TABLE sys_users ADD COLUMN memory_mb INTEGER NOT NULL DEFAULT 1024")
    if "quota_mb" not in columns:
        conn.execute("ALTER TABLE sys_users ADD COLUMN quota_mb INTEGER NOT NULL DEFAULT 512")

def main(argv=None):
    parser = argparse.ArgumentParser(description="Start the Operator OS subsystem.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show diagnostic output from kernel and runtime startup components.",
    )
    parser.add_argument(
        "--source",
        action="store_true",
        help="Run the source checkout instead of the packaged runtime.",
    )
    args = parser.parse_args(argv)

    packaged_root = ROOT_DIR / "storage" / "operator_os_root" / "System"
    packaged_entrypoint = packaged_root / "boot.pyc"
    manifest_path = packaged_root / "runtime_manifest.json"
    if not args.source and (packaged_root.exists() or packaged_entrypoint.exists()):
        if not packaged_entrypoint.is_file() or not manifest_path.is_file():
            print(
                "[BOOT ERROR] Packaged runtime is incomplete. "
                "Run `python build.py --package-runtime --rclone-executable <path-to-rclone.exe>`.",
                file=sys.stderr,
            )
            return 1
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[BOOT ERROR] Could not read packaged runtime manifest: {exc}", file=sys.stderr)
            return 1
        required_version = manifest.get("python_version")
        current_version = ".".join(map(str, sys.version_info[:3]))
        required_implementation = manifest.get("python_implementation")
        if (
            required_version != current_version
            or required_implementation != platform.python_implementation()
        ):
            print(
                "[BOOT ERROR] Packaged bytecode requires "
                f"{required_implementation} {required_version}; the active interpreter is "
                f"{platform.python_implementation()} {current_version}. "
                "Rebuild the package with this Python.",
                file=sys.stderr,
            )
            return 1

        runtime_env = os.environ.copy()
        runtime_env["OPERATOR_OS_ROOT_PATH"] = str(packaged_root.parent)
        runtime_env["OPERATOR_STORAGE_IMAGE"] = str(
            ROOT_DIR / "storage" / "operator_storage_2gb.img"
        )
        runtime_env["OPERATOR_STORAGE_ROOT_PATH"] = str(ROOT_DIR / "storage")
        return subprocess.call(
            [sys.executable, str(packaged_entrypoint), *(
                ["--verbose"] if args.verbose else []
            )],
            cwd=packaged_root,
            env=runtime_env,
        )

    log("Starting Operator OS...")
    try:
        import sqlite3

        db_file = ROOT_DIR / "db" / "operator_system.db"
        schema_file = ROOT_DIR / "db" / "init_schema.sql"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_file) as conn:
            migrate_database(conn)
            conn.executescript(schema_file.read_text(encoding="utf-8"))
        log("System registry ready.")

        storage = OperatorStorageManager()
        disk_info = storage.get_disk_info()
        log(f"Storage ready ({disk_info['capacity_gb']} GB).")

        OperatorNetworkStack()
        log("Network subsystem ready.")

        run_boot_component(
            "C kernel",
            [str(ROOT_DIR / "bin" / "operator_kernel.exe")],
            args.verbose,
        )
        run_boot_component(
            "Rust guard",
            [str(ROOT_DIR / "bin" / "kernel_guard.exe")],
            args.verbose,
        )
        run_boot_component(
            "Java runtime",
            [
                "java",
                "-cp",
                str(ROOT_DIR / "runtime_java" / "bin"),
                "operator.runtime.OperatorRuntime",
                "calculator",
            ],
            args.verbose,
        )

        shell_py = ROOT_DIR / "shell" / "opshell.py"
        if not shell_py.is_file():
            shell_py = shell_py.with_suffix(".pyc")
        log("Starting Operator Shell...")
        shell_env = os.environ.copy()
        shell_env["OPERATOR_QUIET_START"] = "1"
        shell_returncode = _run_shell(shell_py, shell_env)
        if shell_returncode:
            log(f"Operator Shell exited with code {shell_returncode}.", "red")
        else:
            log("Operator Shell closed.")
        return shell_returncode
    except Exception as exc:
        log(f"Boot failed: {exc}", "red")
        if args.verbose:
            raise
        return 1

if __name__ == "__main__":
    sys.exit(main())