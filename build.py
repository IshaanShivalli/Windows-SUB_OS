#!/usr/bin/env python3
"""Build the native and managed Operator OS components."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from install.runtime_packager import package_runtime


ROOT_DIR = Path(__file__).resolve().parent


class BuildError(RuntimeError):
    """Raised when a required build tool or build step fails."""


def find_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise BuildError(f"Required build tool was not found on PATH: {name}")
    return executable


def find_optional_tool(name: str) -> str | None:
    return shutil.which(name)


def run(command: list[str], label: str, *, cwd: Path = ROOT_DIR) -> None:
    print(f"[BUILD] {label}")
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise BuildError(f"Could not start {label}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"{label} failed with exit code {exc.returncode}.") from exc


def _build_components(args, runtime_java_bin: Path, bin_dir: Path) -> None:
    runtime_java_bin.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    javac = find_tool("javac")
    java_sources = sorted((ROOT_DIR / "runtime_java" / "src").rglob("*.java"))
    if not java_sources:
        raise BuildError("No Java source files were found under runtime_java/src.")
    run(
        [javac, "-d", str(runtime_java_bin), *(str(path) for path in java_sources)],
        "Java runtime compilation",
    )

    gcc = find_optional_tool("gcc")
    if gcc:
        run(
            [
                gcc,
                str(ROOT_DIR / "kernel" / "core_kernel.c"),
                "-o",
                str(bin_dir / "operator_kernel.exe"),
            ],
            "C microkernel compilation",
        )
        run(
            [
                gcc,
                str(ROOT_DIR / "shell" / "operator_shell.c"),
                "-o",
                str(bin_dir / "operator_shell.exe"),
            ],
            "C shell launcher compilation",
        )

    cpp_compiler = find_tool("g++")
    run(
        [
            cpp_compiler,
            "-std=c++17",
            str(ROOT_DIR / "shell" / "pow_console.cpp"),
            "-o",
            str(bin_dir / "pow_console.exe"),
        ],
        "C++ POW console compilation",
    )
    run(
        [
            cpp_compiler,
            "-std=c++17",
            str(ROOT_DIR / "shell" / "net_speed.cpp"),
            "-o",
            str(bin_dir / "net_speed.exe"),
            "-lwinhttp",
        ],
        "C++ network speed tester compilation",
    )
    run(
        [
            cpp_compiler,
            "-std=c++17",
            "-shared",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-static-libgcc",
            "-static-libstdc++",
            str(ROOT_DIR / "core" / "services" / "service_runtime.cpp"),
            "-o",
            str(bin_dir / "atlas_service_runtime.dll"),
            "-lws2_32",
        ],
        "C++ service and scheduler runtime compilation",
    )

    if sys.platform == "win32":
        thread_runtime = Path(cpp_compiler).resolve().parent / "libwinpthread-1.dll"
        if not thread_runtime.is_file():
            raise BuildError(f"MinGW thread runtime was not found: {thread_runtime}")
        shutil.copy2(thread_runtime, bin_dir / thread_runtime.name)

    cargo = find_tool("cargo")
    cargo_projects = (
        (
            ROOT_DIR / "kernel" / "kernel_guard" / "Cargo.toml",
            "kernel_guard",
            "Rust kernel guard",
        ),
        (ROOT_DIR / "powcurl" / "Cargo.toml", "powcurl", "Powcurl Rust/C media runtime"),
    )
    profile = "release" if args.release else "debug"
    for manifest, target, label in cargo_projects:
        command = [cargo, "build", "--manifest-path", str(manifest)]
        if args.release:
            command.append("--release")
        run(command, f"{label} build")

        built = manifest.parent / "target" / profile / f"{target}.exe"
        if not built.is_file():
            raise BuildError(f"Cargo completed but the expected output was not found: {built}")
        destination = bin_dir / f"{target}.exe"
        shutil.copy2(built, destination)
        print(f"[BUILD] Copied {target} to {destination}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release",
        action="store_true",
        help="Build Rust components with release optimizations.",
    )
    parser.add_argument(
        "--package-runtime",
        action="store_true",
        help="Package the built runtime under storage/operator_os_root/System.",
    )
    parser.add_argument(
        "--rclone-executable",
        type=Path,
        help="Local rclone.exe to include with --package-runtime.",
    )
    args = parser.parse_args(argv)
    if args.package_runtime and args.rclone_executable is None:
        parser.error("--rclone-executable is required with --package-runtime.")

    if args.package_runtime:
        with tempfile.TemporaryDirectory(prefix="operator-runtime-build-") as temporary:
            output = Path(temporary)
            bin_dir = output / "bin"
            runtime_java_bin = output / "runtime_java" / "bin"
            _build_components(args, runtime_java_bin, bin_dir)
            try:
                package_runtime(
                    ROOT_DIR,
                    args.rclone_executable,
                    binary_dir=bin_dir,
                    java_bin=runtime_java_bin,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise BuildError(f"Runtime packaging failed: {exc}") from exc
    else:
        _build_components(
            args,
            ROOT_DIR / "runtime_java" / "bin",
            ROOT_DIR / "bin",
        )

    print("[BUILD] All requested components built successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"[BUILD ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
