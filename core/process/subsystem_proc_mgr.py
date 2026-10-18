import os
import sys
import time
import subprocess
import threading
from typing import Dict, List, Optional
from pathlib import Path

class SubsystemProcess:
    def __init__(self, pid: int, name: str, runtime: str, cmd: str, user: str = "operator", prio: int = 10):
        self.pid = pid
        self.name = name
        self.runtime = runtime.lower() # python, java, native, powershell, bash, windows
        self.cmd = cmd
        self.user = user
        self.prio = prio
        self.state = "RUNNING" # RUNNING, STOPPED, TERMINATED
        self.start_time = time.time()
        self.cpu_usage_pct = 1.2
        self.mem_mb = 16.4
        self.exit_code: Optional[int] = None
        self.popen_obj: Optional[subprocess.Popen] = None
        self.thread_obj: Optional[threading.Thread] = None

class SubsystemProcessManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SubsystemProcessManager, cls).__new__(cls)
            cls._instance.init_subsystem()
        return cls._instance

    def init_subsystem(self):
        self.next_pid = 200
        self.procs: Dict[int, SubsystemProcess] = {}
        self.lock = threading.Lock()
        self.seed_core_daemons()

    def seed_core_daemons(self):
        # Seed running subsystem runtimes
        p1 = SubsystemProcess(1, "system_init", "native", "core/services/init", "root", 20)
        p1.mem_mb = 32.0
        p2 = SubsystemProcess(2, "kernel_guard", "native (rust)", "bin/kernel_guard.exe", "root", 18)
        p2.mem_mb = 12.5
        p3 = SubsystemProcess(3, "java_ovm_engine", "java", "operator.runtime.OperatorRuntime", "operator", 12)
        p3.mem_mb = 64.0
        p4 = SubsystemProcess(4, "python_shell_subsystem", "python", "shell/opshell.py", "operator", 10)
        p4.mem_mb = 24.2
        p5 = SubsystemProcess(5, "cpp_compositor_wm", "native (c++)", "bin/operator_wm.exe", "operator", 15)
        p5.mem_mb = 45.8
        for p in [p1, p2, p3, p4, p5]:
            self.procs[p.pid] = p

    def detect_runtime(self, cmd: str) -> str:
        c = cmd.lower()
        if "java" in c: return "java"
        if "python" in c or c.endswith(".py"): return "python"
        if "powershell" in c or c.endswith(".ps1"): return "powershell"
        if "wsl" in c or "bash" in c or c.endswith(".sh"): return "bash"
        if c.endswith(".exe"): return "native"
        return "windows"

    def start_process(self, name: str, cmd: str, user: str = "operator", prio: int = 10, cwd: str = None) -> int:
        with self.lock:
            pid = self.next_pid
            self.next_pid += 1
            rt = self.detect_runtime(cmd)
            proc = SubsystemProcess(pid, name, rt, cmd, user, prio)
            self.procs[pid] = proc

        def runner():
            try:
                p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                proc.popen_obj = p
                out, err = p.communicate()
                proc.exit_code = p.returncode
            except Exception as e:
                proc.exit_code = -1
            proc.state = "TERMINATED"

        t = threading.Thread(target=runner, daemon=True)
        proc.thread_obj = t
        t.start()
        return pid

    def stop_process(self, pid: int) -> bool:
        with self.lock:
            if pid not in self.procs: return False
            p = self.procs[pid]
        p.state = "STOPPED"
        if p.popen_obj and p.popen_obj.poll() is None:
            try: p.popen_obj.terminate()
            except: pass
        return True

    def kill_process(self, pid: int) -> bool:
        with self.lock:
            if pid not in self.procs: return False
            p = self.procs[pid]
        p.state = "TERMINATED"
        p.exit_code = 137
        if p.popen_obj and p.popen_obj.poll() is None:
            try: p.popen_obj.kill()
            except: pass
        return True

    def get_info(self, pid: int) -> Optional[dict]:
        with self.lock:
            if pid not in self.procs: return None
            p = self.procs[pid]
            return {
                "pid": p.pid,
                "name": p.name,
                "runtime": p.runtime,
                "user": p.user,
                "priority": p.prio,
                "state": p.state,
                "uptime": f"{time.time() - p.start_time:.1f}s",
                "cpu": f"{p.cpu_usage_pct}%",
                "memory": f"{p.mem_mb:.1f} MB",
                "command": p.cmd,
                "exit_code": p.exit_code
            }

    def list_all(self) -> List[dict]:
        with self.lock:
            records = []
            for pid, p in self.procs.items():
                records.append({
                    "pid": p.pid,
                    "name": p.name,
                    "runtime": p.runtime,
                    "user": p.user,
                    "state": p.state,
                    "prio": p.prio,
                    "mem": f"{p.mem_mb:.1f}MB",
                    "cmd": p.cmd[:35]
                })
            return sorted(records, key=lambda x: x["pid"])
