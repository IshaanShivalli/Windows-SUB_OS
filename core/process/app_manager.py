import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MANIFEST_DIR = ROOT_DIR / "apps" / "manifests"
SANDBOX_DIR = ROOT_DIR / "apps" / "sandboxes"

class ApplicationManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ApplicationManager, cls).__new__(cls)
            cls._instance.init_app_mgr()
        return cls._instance

    def init_app_mgr(self):
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        self.active_apps: Dict[str, dict] = {}
        self.seed_app_manifests()

    def seed_app_manifests(self):
        manifests = [
            {
                "name": "Calculator",
                "app_id": "app.calculator",
                "runtime": "java",
                "entrypoint": "calculator",
                "permissions": ["math", "filesystem"],
                "exec_cmd": "java -cp runtime_java/bin operator.runtime.OperatorRuntime calculator"
            },
            {
                "name": "SysDiagnostics",
                "app_id": "app.diagnostics",
                "runtime": "java",
                "entrypoint": "diagnostics",
                "permissions": ["hardware", "metrics"],
                "exec_cmd": "java -cp runtime_java/bin operator.runtime.OperatorRuntime diagnostics"
            },
        ]
        for m in manifests:
            mf = MANIFEST_DIR / f"{m['app_id']}.json"
            if not mf.exists():
                mf.write_text(json.dumps(m, indent=2), encoding="utf-8")

    def list_apps(self) -> List[dict]:
        apps = []
        for mf in MANIFEST_DIR.glob("*.json"):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                status = "RUNNING" if data["app_id"] in self.active_apps else "INSTALLED"
                data["status"] = status
                apps.append(data)
            except: pass
        return apps

    def launch(self, app_id_or_name: str) -> str:
        # Match by ID or Name
        target_mf = None
        for mf in MANIFEST_DIR.glob("*.json"):
            data = json.loads(mf.read_text(encoding="utf-8"))
            if data["app_id"].lower() == app_id_or_name.lower() or data["name"].lower() == app_id_or_name.lower():
                target_mf = data
                break

        if not target_mf:
            return f"\033[31m[APP ERR] Application '{app_id_or_name}' manifest not found.\033[0m"

        # Prepare sandboxed isolated working directory
        app_sandbox = SANDBOX_DIR / target_mf["app_id"]
        app_sandbox.mkdir(parents=True, exist_ok=True)

        cmd = target_mf["exec_cmd"]
        p = subprocess.Popen(cmd, shell=True, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.active_apps[target_mf["app_id"]] = {
            "name": target_mf["name"],
            "pid": p.pid,
            "runtime": target_mf["runtime"],
            "permissions": target_mf["permissions"],
            "process": p,
            "sandbox": str(app_sandbox)
        }
        return f"\033[1;32m[APP LAUNCHED]\033[0m '{target_mf['name']}' (Runtime: {target_mf['runtime']}) running in sandbox '{app_sandbox.name}' [Permissions: {target_mf['permissions']}]."

    def close(self, app_id_or_name: str) -> str:
        found_id = None
        for aid, info in self.active_apps.items():
            if aid.lower() == app_id_or_name.lower() or info["name"].lower() == app_id_or_name.lower():
                found_id = aid
                break

        if not found_id:
            return f"\033[31m[APP ERR] No active instance of '{app_id_or_name}' found.\033[0m"

        info = self.active_apps.pop(found_id)
        p = info.get("process")
        if p and p.poll() is None:
            try: p.kill()
            except: pass
        return f"\033[1;33m[APP CLOSED]\033[0m Terminated '{info['name']}' instance."
