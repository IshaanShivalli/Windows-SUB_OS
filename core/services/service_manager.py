import time
import threading
from typing import Dict, List, Optional
from pathlib import Path

class ServiceUnit:
    def __init__(self, name: str, description: str, exec_start: str, deps: List[str] = None):
        self.name = name
        self.description = description
        self.exec_start = exec_start
        self.deps = deps or []
        self.state = "INACTIVE" # INACTIVE, ACTIVATING, ACTIVE, FAILED
        self.logs: List[str] = []
        self.start_time: Optional[float] = None

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

class ServiceManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceManager, cls).__new__(cls)
            cls._instance.init_services()
        return cls._instance

    def init_services(self):
        self.services: Dict[str, ServiceUnit] = {}
        self.seed_core_services()

    def seed_core_services(self):
        self.register("kernel_guard.service", "Kernel Memory & Hardware Guard", "bin/kernel_guard.exe")
        self.register("net_stack.service", "Subsystem TCP/IP Network Gateway", "python network/net_stack.py", deps=["kernel_guard.service"])
        self.register("db_registry.service", "System SQLite Registry Daemon", "core/services/db_daemon", deps=["kernel_guard.service"])
        self.register("window_compositor.service", "C++ Desktop Window Manager", "bin/operator_wm.exe", deps=["kernel_guard.service", "db_registry.service"])

    def register(self, name: str, desc: str, cmd: str, deps: List[str] = None):
        self.services[name] = ServiceUnit(name, desc, cmd, deps)

    def start(self, name: str) -> str:
        if name not in self.services:
            return f"\033[31m[SRV ERR] Unknown service '{name}'.\033[0m"
        srv = self.services[name]

        # Verify startup dependencies
        for dep in srv.deps:
            if dep in self.services and self.services[dep].state != "ACTIVE":
                self.start(dep)

        srv.state = "ACTIVE"
        srv.start_time = time.time()
        srv.log(f"Started service '{srv.name}'")
        return f"\033[1;32m[SRV ACTIVE]\033[0m Started {srv.name} ({srv.description})"

    def stop(self, name: str) -> str:
        if name not in self.services:
            return f"\033[31m[SRV ERR] Unknown service '{name}'.\033[0m"
        srv = self.services[name]
        srv.state = "INACTIVE"
        srv.log(f"Stopped service '{srv.name}'")
        return f"\033[1;33m[SRV STOPPED]\033[0m Deactivated {srv.name}"

    def restart(self, name: str) -> str:
        self.stop(name)
        return self.start(name)

    def list_services(self) -> List[dict]:
        return [
            {
                "unit": s.name,
                "load": "loaded",
                "active": s.state.lower(),
                "sub": "running" if s.state == "ACTIVE" else "dead",
                "description": s.description
            }
            for s in self.services.values()
        ]

    def get_logs(self, name: str) -> List[str]:
        if name in self.services:
            return self.services[name].logs
        return [f"Service '{name}' not found."]
