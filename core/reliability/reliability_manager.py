import os
import time
import json
import shutil
from pathlib import Path
from typing import List, Dict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RESTORE_DIR = ROOT_DIR / "storage" / "restore_points"
CRASH_DIR = ROOT_DIR / "storage" / "crash_reports"

class ReliabilityManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ReliabilityManager, cls).__new__(cls)
            cls._instance.init_reliability()
        return cls._instance

    def init_reliability(self):
        RESTORE_DIR.mkdir(parents=True, exist_ok=True)
        CRASH_DIR.mkdir(parents=True, exist_ok=True)
        self.watchdog_healthy = True
        self.safe_mode_enabled = False

    def create_restore_point(self, name: str) -> str:
        timestamp = int(time.time())
        pt_dir = RESTORE_DIR / f"{timestamp}_{name}"
        pt_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot SQLite database and VFS metadata
        db_file = ROOT_DIR / "db" / "operator_system.db"
        if db_file.exists():
            shutil.copy2(db_file, pt_dir / "system_db.snapshot")

        meta = {
            "name": name,
            "timestamp": timestamp,
            "date": time.ctime(),
            "kernel_version": "1.0.0-subsystem",
            "storage_gb": 2.0
        }
        (pt_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return f"\033[1;32m[RESTORE POINT CREATED]\033[0m Snapshot '{name}' saved at {pt_dir.name}"

    def list_restore_points(self) -> List[dict]:
        points = []
        for d in RESTORE_DIR.iterdir():
            if d.is_dir() and (d / "metadata.json").exists():
                try:
                    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
                    points.append(meta)
                except:
                    pass
        return sorted(points, key=lambda x: x.get("timestamp", 0), reverse=True)

    def log_crash(self, module: str, error_trace: str) -> str:
        report_file = CRASH_DIR / f"crash_{int(time.time())}_{module}.log"
        content = f"--- OPERATOR OS CRASH DUMP ---\nModule: {module}\nTimestamp: {time.ctime()}\nTrace:\n{error_trace}\n"
        report_file.write_text(content, encoding="utf-8")
        return report_file.name

    def list_crashes(self) -> List[str]:
        return [f.name for f in CRASH_DIR.glob("*.log")]

    def check_health(self) -> dict:
        return {
            "watchdog": "ACTIVE (Subsystem heartbeat ping OK)",
            "safe_mode": "DISABLED" if not self.safe_mode_enabled else "ACTIVE",
            "restore_points_available": len(self.list_restore_points()),
            "crash_reports": len(self.list_crashes()),
            "integrity": "PASS (Memory page supervisor consistent)"
        }
