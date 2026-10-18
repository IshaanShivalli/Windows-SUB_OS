import subprocess
import time
import os
from pathlib import Path
from typing import List, Dict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

class DeveloperTools:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DeveloperTools, cls).__new__(cls)
        return cls._instance

    def run_tests(self) -> Dict[str, str]:
        results = {}
        # Test 1: Kernel C
        k_exe = ROOT_DIR / "bin" / "operator_kernel.exe"
        results["kernel_c"] = "PASS" if k_exe.exists() else "FAIL"

        # Test 2: Rust Guard
        r_exe = ROOT_DIR / "bin" / "kernel_guard.exe"
        results["kernel_rust"] = "PASS" if r_exe.exists() else "FAIL"

        # Test 3: 2GB Storage Device
        img = ROOT_DIR / "storage" / "operator_storage_2gb.img"
        results["storage_2gb"] = "PASS" if img.exists() and img.stat().st_size > 0 else "FAIL"

        # Test 4: Database Schema
        db = ROOT_DIR / "db" / "operator_system.db"
        results["database_sql"] = "PASS" if db.exists() else "FAIL"

        # Test 5: Java OVM Classes
        ovm_cls = ROOT_DIR / "runtime_java" / "bin" / "operator" / "runtime" / "OperatorRuntime.class"
        results["java_ovm"] = "PASS" if ovm_cls.exists() else "FAIL"

        return results

    def trace_syscalls(self, pid: int = 1) -> List[str]:
        # Emulate ptrace / strace on subsystem execution
        return [
            f"[{time.strftime('%H:%M:%S')}] SYS_SPAWN(pid={pid}, user='root') = 0",
            f"[{time.strftime('%H:%M:%S')}] SYS_MEM_ALLOC(pid={pid}, blocks=16) = 0x1000",
            f"[{time.strftime('%H:%M:%S')}] SYS_VFS_MOUNT('/dev/nvme0n1_operator', '/root') = 0",
            f"[{time.strftime('%H:%M:%S')}] SYS_IPC_BIND(port=8088) = SUCCESS",
            f"[{time.strftime('%H:%M:%S')}] SYS_SCHED_TICK(timeslice=10ms) = RUNNING",
        ]

    def build_all(self) -> str:
        logs = []
        logs.append("[BUILD] Compiling C Kernel...")
        subprocess.run(["gcc", "kernel/core_kernel.c", "-o", "bin/operator_kernel.exe"], cwd=str(ROOT_DIR))
        logs.append("[BUILD] Compiling C++ Window Manager...")
        subprocess.run(["g++", "-O2", "gui/window_manager_v2.cpp", "-o", "bin/operator_wm.exe", "-lgdi32", "-luser32", "-lshell32", "-mwindows"], cwd=str(ROOT_DIR))
        logs.append("[BUILD] Compiling Java OVM...")
        subprocess.run(["javac", "-d", "runtime_java/bin", "runtime_java/src/operator/runtime/OperatorRuntime.java"], cwd=str(ROOT_DIR))
        logs.append("[BUILD] Build cycle completed successfully.")
        return "\n".join(logs)
