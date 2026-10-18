import time
from pathlib import Path
from typing import List, Dict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = ROOT_DIR / "storage" / "logs"

class CentralLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CentralLogger, cls).__new__(cls)
            cls._instance.init_logger()
        return cls._instance

    def init_logger(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.event_log_file = LOG_DIR / "system_events.log"
        self.boot_log_file = LOG_DIR / "boot.log"
        if not self.event_log_file.exists():
            self.event_log_file.write_text(f"[{time.ctime()}] [INIT] Central Logging Subsystem Online\n", encoding="utf-8")
        if not self.boot_log_file.exists():
            self.boot_log_file.write_text(f"[{time.ctime()}] [BOOT] System cold boot sequence logged\n", encoding="utf-8")

    def log(self, category: str, message: str):
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{category.upper()}] {message}\n"
        with open(self.event_log_file, "a", encoding="utf-8") as f:
            f.write(entry)

    def log_boot(self, message: str):
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [BOOT] {message}\n"
        with open(self.boot_log_file, "a", encoding="utf-8") as f:
            f.write(entry)

    def show_logs(self, n: int = 25, log_type: str = "events") -> str:
        target = self.boot_log_file if log_type == "boot" else self.event_log_file
        if not target.exists():
            return "No logs recorded."
        lines = target.read_text(encoding="utf-8").splitlines()
        tail = lines[-n:]
        return "\n".join(tail)

    def clear_logs(self) -> str:
        self.event_log_file.write_text(f"[{time.ctime()}] [RESET] Logs cleared by operator\n", encoding="utf-8")
        return "\033[1;33m[LOGS CLEARED]\033[0m System event journal reset."
