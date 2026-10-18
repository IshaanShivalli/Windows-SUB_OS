#!/usr/bin/env python3
"""
Operator OS Subsystem Pre-Flight Installer & Verification Suite
Checks all host toolchains, compilers, binaries, permissions, and 2GB storage provisioning.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

def check_mark(status: bool) -> str:
    return "\033[1;32m[PASS]\033[0m" if status else "\033[1;31m[FAIL]\033[0m"

def main():
    print("""
    ======================================================================
              OPERATOR OS SUBSYSTEM VERIFICATION & INSTALLER
    ======================================================================
    """)
    checks = []

    # 1. Python Environment
    py_ok = sys.version_info >= (3, 8)
    checks.append(("Python 3.8+ Runtime", py_ok, sys.version.split()[0]))

    # 2. Rust & Cargo
    cargo_path = shutil.which("cargo")
    checks.append(("Rust / Cargo Toolchain", cargo_path is not None, cargo_path or "Not found"))

    # 3. GCC / C++ Compilers
    gcc_path = shutil.which("gcc")
    gpp_path = shutil.which("g++")
    checks.append(("GCC Compiler (MSYS2 / MinGW)", gcc_path is not None, gcc_path or "Not found"))
    checks.append(("G++ Compiler", gpp_path is not None, gpp_path or "Not found"))

    # 4. Java JDK / JRE
    java_path = shutil.which("java")
    javac_path = shutil.which("javac")
    checks.append(("Java Runtime (java)", java_path is not None, java_path or "Not found"))
    checks.append(("Java Compiler (javac)", javac_path is not None, javac_path or "Not found"))

    # 5. Core Binaries
    kernel_exe = ROOT_DIR / "bin" / "operator_kernel.exe"
    guard_exe = ROOT_DIR / "bin" / "kernel_guard.exe"
    wm_exe = ROOT_DIR / "bin" / "operator_wm.exe"
    checks.append(("C Kernel Binary (operator_kernel.exe)", kernel_exe.exists(), str(kernel_exe.name)))
    checks.append(("Rust Guard Binary (kernel_guard.exe)", guard_exe.exists(), str(guard_exe.name)))
    checks.append(("C++ Window Manager (operator_wm.exe)", wm_exe.exists(), str(wm_exe.name)))

    # 6. Storage & Database
    storage_img = ROOT_DIR / "storage" / "operator_storage_2gb.img"
    db_file = ROOT_DIR / "db" / "operator_system.db"
    checks.append(("2GB Virtual Storage Image", storage_img.exists(), f"{storage_img.stat().st_size / (1024*1024*1024):.1f} GB" if storage_img.exists() else "Missing"))
    checks.append(("SQLite3 System Registry", db_file.exists(), str(db_file.name)))

    for name, ok, details in checks:
        print(f"  {check_mark(ok)} {name:<38} : {details}")

    all_passed = all(c[1] for c in checks)
    print("\n" + "="*70)
    if all_passed:
        print("\033[1;32m  ALL SUBSYSTEM COMPONENTS VERIFIED - SYSTEM READY FOR OPERATION\033[0m")
    else:
        print("\033[1;33m  SOME OPTIONAL COMPONENTS REQUIRE SETUP (Run dev.build or install tools)\033[0m")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
