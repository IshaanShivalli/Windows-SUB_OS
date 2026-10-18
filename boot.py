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
7. C++ Cybernetic Desktop Window Manager
8. Polyglot Script & Shell Subsystem (.sh, .ps1, .bat, .opsh)
"""

import os
import sys
import subprocess
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from storage.storage_manager import OperatorStorageManager
from network.net_stack import OperatorNetworkStack

def log(tag, msg):
    print(f"\033[1;36m[{tag}]\033[0m {msg}")

def main():
    print("""
    ======================================================================
                  OPERATOR OS v2.0 - NEXT-GEN SUBSYSTEM
        2GB Inbuilt Storage | Full Network Stack | Script Polyglot
    ======================================================================
    """)

    # 1. Initialize SQLite Database
    log("STAGE 1: DB", "Synchronizing System Registry & Package Catalog...")
    db_file = ROOT_DIR / "db" / "operator_system.db"
    schema_file = ROOT_DIR / "db" / "init_schema.sql"
    import sqlite3
    with sqlite3.connect(db_file) as conn:
        conn.executescript(schema_file.read_text(encoding="utf-8"))
    log("STAGE 1: DB", f"Database online at {db_file.name}")

    # 2. Initialize 2GB Storage Device
    log("STAGE 2: STORAGE", "Mounting Inbuilt 2GB Raw Block Storage Device...")
    storage = OperatorStorageManager()
    disk_info = storage.get_disk_info()
    log("STAGE 2: STORAGE", f"Mounted {disk_info['device']} ({disk_info['capacity_gb']} GB, {disk_info['filesystem']})")

    # 3. Initialize Networking Subsystem
    log("STAGE 3: NETWORK", "Bringing up Network Adapters & Virtual Routing Table...")
    net = OperatorNetworkStack()
    ifaces = net.ifconfig()
    log("STAGE 3: NETWORK", f"Interfaces Active: {[i['name'] for i in ifaces]} | DNS: {net.dns_servers}")

    # 4. Boot C Microkernel
    log("STAGE 4: KERNEL-C", "Bootstrapping Microkernel Core...")
    kernel_exe = ROOT_DIR / "bin" / "operator_kernel.exe"
    p_kernel = subprocess.run([str(kernel_exe)], capture_output=True, text=True)
    print(p_kernel.stdout.strip())

    # 5. Boot Rust Safety Driver Layer
    log("STAGE 5: KERNEL-RUST", "Activating Hardware Safety Guard & Page Supervisor...")
    guard_exe = ROOT_DIR / "bin" / "kernel_guard.exe"
    p_guard = subprocess.run([str(guard_exe)], capture_output=True, text=True)
    print(p_guard.stdout.strip())

    # 6. Verify Java OVM Runtime
    log("STAGE 6: JAVA-OVM", "Starting Java Application Runtime (OVM)...")
    ovm_cmd = ["java", "-cp", "runtime_java/bin", "operator.runtime.OperatorRuntime", "calculator"]
    p_ovm = subprocess.run(ovm_cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
    print(p_ovm.stdout.strip())

    # 7. GUI Compositor Announcement
    log("STAGE 7: GUI-C++", "Desktop compositor ready. Type 'gui' in Operator Shell to open it.")
    log("STAGE 7: BROWSER", "Browser surface ready. Open it from the desktop when needed.")

    # 8. Start Polyglot Shell
    log("STAGE 8: SHELL", "Launching Operator Script Shell (supports .sh, .ps1, .bat, .opsh)...\n")
    shell_py = ROOT_DIR / "shell" / "opshell.py"
    subprocess.run([sys.executable, str(shell_py)])

if __name__ == "__main__":
    main()
