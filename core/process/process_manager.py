import os
import signal
import time
import threading
import subprocess
from enum import Enum
from typing import Dict, Optional, List

class ProcessState(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    SLEEPING = "SLEEPING"
    STOPPED = "STOPPED"
    ZOMBIE = "ZOMBIE"
    TERMINATED = "TERMINATED"

class ProcessControlBlock:
    def __init__(self, pid: int, name: str, cmd: str, user: str, priority: int = 10, is_service: bool = False):
        self.pid = pid
        self.name = name
        self.cmd = cmd
        self.user = user
        self.priority = priority # 1 (lowest) - 20 (highest, realtime)
        self.state = ProcessState.READY
        self.start_time = time.time()
        self.cpu_time = 0.0
        self.exit_code: Optional[int] = None
        self.is_service = is_service
        self.popen_obj: Optional[subprocess.Popen] = None
        self.thread_obj: Optional[threading.Thread] = None
        self.signals_received: List[str] = []

class RealProcessManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RealProcessManager, cls).__new__(cls)
            cls._instance.init_manager()
        return cls._instance

    def init_manager(self):
        self.next_pid = 100
        self.pcb_table: Dict[int, ProcessControlBlock] = {}
        self.lock = threading.Lock()

        # Seed PID 1 (Init daemon / systemd equivalent)
        init_pcb = ProcessControlBlock(1, "system_init", "core/services/init", "root", priority=20, is_service=True)
        init_pcb.state = ProcessState.RUNNING
        self.pcb_table[1] = init_pcb

    def spawn(self, name: str, cmd: str, user: str = "operator", priority: int = 10, run_async: bool = True) -> int:
        with self.lock:
            pid = self.next_pid
            self.next_pid += 1
            pcb = ProcessControlBlock(pid, name, cmd, user, priority)
            self.pcb_table[pid] = pcb

        def runner():
            pcb.state = ProcessState.RUNNING
            t0 = time.time()
            try:
                # Dispatches native command or script
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                pcb.popen_obj = proc
                out, err = proc.communicate()
                pcb.exit_code = proc.returncode
            except Exception as e:
                pcb.exit_code = -1
            pcb.cpu_time = time.time() - t0
            pcb.state = ProcessState.TERMINATED

        if run_async:
            t = threading.Thread(target=runner, daemon=True)
            pcb.thread_obj = t
            t.start()
        else:
            runner()
        return pid

    def signal_process(self, pid: int, sig_name: str) -> bool:
        with self.lock:
            if pid not in self.pcb_table:
                return False
            pcb = self.pcb_table[pid]

        pcb.signals_received.append(sig_name)
        if sig_name in ("SIGKILL", "KILL"):
            if pcb.popen_obj and pcb.popen_obj.poll() is None:
                try: pcb.popen_obj.kill()
                except: pass
            pcb.state = ProcessState.TERMINATED
            pcb.exit_code = 137
            return True
        elif sig_name in ("SIGTERM", "TERM"):
            if pcb.popen_obj and pcb.popen_obj.poll() is None:
                try: pcb.popen_obj.terminate()
                except: pass
            pcb.state = ProcessState.TERMINATED
            pcb.exit_code = 143
            return True
        elif sig_name in ("SIGSTOP", "STOP"):
            pcb.state = ProcessState.STOPPED
            return True
        elif sig_name in ("SIGCONT", "CONT"):
            pcb.state = ProcessState.RUNNING
            return True
        return False

    def get_top(self) -> List[dict]:
        with self.lock:
            records = []
            for pid, pcb in self.pcb_table.items():
                records.append({
                    "pid": pid,
                    "name": pcb.name,
                    "user": pcb.user,
                    "priority": pcb.priority,
                    "state": pcb.state.value,
                    "cpu_time": f"{pcb.cpu_time:.2f}s",
                    "uptime": f"{time.time() - pcb.start_time:.1f}s",
                    "cmd": pcb.cmd[:32]
                })
            return sorted(records, key=lambda x: x["pid"])
