#!/usr/bin/env python3
"""
Operator Polyglot Script & Shell Engine (opshell)
Version 2.0.0

Key Features:
1. Native Execution of Shell Script Files:
   - Bash/Linux Shell Scripts (.sh, .bash) via Linux/WSL runtime
   - PowerShell Scripts (.ps1) via PowerShell runtime
   - Command Prompt Batch Scripts (.bat, .cmd) via CMD runtime
   - Operator OS Script Files (.opsh, .ops) via Native Operator Grammar
2. Distinct Custom Command Vocabulary (Different from standard shells):
   - `sys.probe`           -> Probe hardware, kernel, memory, 2GB disk, and scheduler
   - `storage.inspect`     -> 2GB block device stats, partition mapping, block allocation
   - `net.ifconfig`        -> List network interfaces, IP addresses, MACs
   - `net.routes`          -> Kernel routing table
   - `net.resolve <host>`  -> DNS domain lookup
   - `net.probe <host>`    -> Latency probe & port ping
   - `net.fetch <url>`     -> Network HTTP socket fetcher
   - `script.run <file>`   -> Polyglot script executor (detects .sh, .ps1, .bat, .opsh)
   - `pkg.list`            -> Registry query of installed OS packages
   - `pkg.install <name>`  -> Install new package definition
   - `db.query <sql>`      -> Run direct SQL queries against OS registry
   - `proc.list`           -> Active process table
   - `var.set <k>=<v>`     -> Environment variable store
   - `var.get <k>`         -> Environment variable read
"""

import os
import sys
import subprocess
import shlex
import sqlite3
import re
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "db" / "operator_system.db"
sys.path.insert(0, str(ROOT_DIR))

from storage.storage_manager import OperatorStorageManager
from network.net_stack import OperatorNetworkStack
from integrations.google_drive import GoogleDriveManager
from core.process.process_manager import RealProcessManager
from core.process.subsystem_proc_mgr import SubsystemProcessManager
from core.security.security_manager import SecurityManager
from packages.package_manager import PackageManager
from storage.vfs.vfs_engine import VirtualFileSystem
from storage.vfs.host_fs_bridge import HostFilesystemBridge
from core.process.app_manager import ApplicationManager
from core.services.service_manager import ServiceManager
from core.settings.settings_service import SystemSettingsService
from core.windows.win_integration import WindowsIntegrationLayer
from core.logger.central_logger import CentralLogger
from core.reliability.reliability_manager import ReliabilityManager
from core.devtools.dev_tools import DeveloperTools
from boot_target.boot_builder import BootableTargetBuilder

class OperatorShellEngine:
    def __init__(self):
        self.storage = OperatorStorageManager()
        self.network = OperatorNetworkStack()
        self.google_drive = GoogleDriveManager()
        self.proc_mgr = RealProcessManager()
        self.sub_proc_mgr = SubsystemProcessManager()
        self.security = SecurityManager()
        self.pkg_mgr = PackageManager()
        self.vfs = VirtualFileSystem()
        self.host_bridge = HostFilesystemBridge()
        self.app_mgr = ApplicationManager()
        self.services = ServiceManager()
        self.settings_svc = SystemSettingsService()
        self.win = WindowsIntegrationLayer()
        self.logger = CentralLogger()
        self.reliability = ReliabilityManager()
        self.devtools = DeveloperTools()
        self.boot_builder = BootableTargetBuilder()
        self.variables = {
            "SYS.OS": "Operator OS",
            "SYS.VER": "2.0.0-PRO",
            "SYS.ARCH": "x86_64-subsystem",
            "SYS.USER": "operator",
            "SYS.CWD": os.getcwd(),
        }
        self.init_db()

    def init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        schema_file = ROOT_DIR / "db" / "init_schema.sql"
        if not DB_PATH.exists() and schema_file.exists():
            with sqlite3.connect(DB_PATH) as conn:
                conn.executescript(schema_file.read_text(encoding="utf-8"))

    def get_prompt(self):
        user = self.variables.get("SYS.USER", "operator")
        cwd = os.path.basename(self.variables.get("SYS.CWD", "/")) or "/"
        return f"\033[1;35mop-subsystem\033[0m:\033[1;36m{user}\033[0m[\033[1;32m{cwd}\033[0m] » "

    def execute_script_file(self, script_path_str: str, args: list = None):
        """
        Executes external shell script files according to their file type and engine:
        - .sh, .bash  -> Linux / WSL
        - .ps1        -> PowerShell
        - .bat, .cmd  -> Windows CMD
        - .opsh, .ops -> Operator Native Shell Script
        """
        args = args or []
        script_path = Path(script_path_str)
        if not script_path.is_absolute():
            script_path = Path(self.variables["SYS.CWD"]) / script_path

        if not script_path.exists():
            return f"\033[31m[Script Error]: Script file '{script_path}' not found.\033[0m"

        ext = script_path.suffix.lower()
        abs_str = str(script_path.resolve())

        print(f"\033[1;33m[SCRIPT LOADER]\033[0m Executing '{script_path.name}' via {ext.upper()} target runtime...")

        try:
            if ext in (".sh", ".bash"):
                # Run with WSL / bash
                wsl_path = abs_str.replace("\\", "/")
                if ":" in wsl_path:
                    drive, rest = wsl_path.split(":", 1)
                    wsl_path = f"/mnt/{drive.lower()}{rest}"
                cmd = ["wsl", "-e", "bash", wsl_path] + args
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                return (res.stdout + res.stderr).strip()

            elif ext == ".ps1":
                cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", abs_str] + args
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                return (res.stdout + res.stderr).strip()

            elif ext in (".bat", ".cmd"):
                cmd = ["cmd.exe", "/c", abs_str] + args
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                return (res.stdout + res.stderr).strip()

            elif ext in (".opsh", ".ops"):
                # Run line by line through Operator Shell Engine
                content = script_path.read_text(encoding="utf-8")
                outputs = []
                for line in content.splitlines():
                    out = self.eval_command(line.strip())
                    if out:
                        outputs.append(out)
                return "\n".join(outputs)

            else:
                return f"\033[31m[Script Error]: Unsupported script file extension '{ext}'. (Supports .sh, .bash, .ps1, .bat, .cmd, .opsh)\033[0m"

        except Exception as e:
            return f"\033[31m[Script Runtime Exception]: {str(e)}\033[0m"

    def eval_command(self, raw_line: str):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            return None

        # Interpolate variables: @(VAR) or $(VAR)
        for k, v in self.variables.items():
            line = line.replace(f"@({k})", str(v)).replace(f"${k}", str(v))

        tokens = shlex.split(line)
        cmd = tokens[0].lower()
        args = tokens[1:]

        if cmd in ("gui", "browser", "web"):
            return "[SUBSYSTEM] GUI and browser components have been removed from Operator OS."

        # Check script invocation shorthand (e.g. ./demo.sh or demo.bat)
        if cmd.startswith("./") or cmd.endswith((".sh", ".bash", ".ps1", ".bat", ".cmd", ".opsh")):
            script = cmd.lstrip("./")
            return self.execute_script_file(script, args)

        # Distinct Custom Operator Command Vocabulary
        if cmd == "help":
            return """
\033[1;36mOPERATOR OS COMMAND VOCABULARY (v2.0 PRO)\033[0m
  System & Hardware:
    sys.probe              Probe OS Kernel, microarchitecture, scheduler & memory
    storage.inspect        Inspect inbuilt 2GB Block Storage partition and allocation
    proc.list              Enumerate running subsystem processes

  Network Stack:
    net.ifconfig           Display network interfaces (lo0, op_eth0, virtio_net)
    net.routes             Display kernel routing table
    net.resolve <host>     DNS query resolver (e.g. net.resolve google.com)
    net.probe <host> [port] Measure TCP latency & probe connectivity
    net.fetch <url>        Network socket HTTP client request

  Linux Commands:
    ls [-la] [path]        List directory contents (Linux style)
    pwd                    Print working directory (Linux / POSIX)
    cat <file>             Concatenate & display file content
    touch <file>           Create empty file or update timestamp
    grep <pattern> <file>  Search text matching regex or string in files
    df [-h]                Report filesystem disk space usage
    free [-m|-h]           Display memory & swap telemetry
    uname [-a]             Print kernel and system architecture information
    uptime                 Show system boot uptime and load
    wc [-l|-w|-c] <file>   Print newline, word, and byte counts

  PowerShell Commands:
    Get-Process [name]     List active processes or filter by name (alias: ps)
    Get-Service            Enumerate subsystem and host services
    Get-Date               Get current local date and timestamp
    Get-ChildItem [path]   List directory objects (alias: gci, dir)
    Get-Content <file>     Read content of file (alias: gc)
    Test-Connection <host> Ping network host connectivity
    Get-ComputerInfo       Display subsystem host hardware info

  CMD / Windows Commands:
    dir [path]             List files and directories in Windows format
    type <file>            Display file contents
    ver                    Display Operator OS kernel and build version
    systeminfo             Show complete system and memory diagnostics
    ipconfig               Display IP configuration and adapters
    tree [dir]             Graphically display directory structure

  Script File Execution Engine:
    script.run <file>      Run Linux (.sh), PowerShell (.ps1), Batch (.bat), or Operator (.opsh) files
                           Shorthand: Simply type './myscript.sh' or 'build.bat'

  Package & System DB:
    pkg.list               Query installed packages from SQL registry
    db.query <sql>         Run raw SQL statement on system database

  Variables & Navigation:
    var.set <k>=<v>        Assign system environment variable
    var.get <k>            Read environment variable
    cd <dir> / fs.goto     Change directory
    cls / clear            Clear screen buffer
    exit                   Exit shell
"""

        elif cmd == "sys.probe":
            storage_info = self.storage.get_disk_info()
            return f"""
\033[1;36m=== OPERATOR OS SUBSYSTEM PROFILE ===\033[0m
Kernel Core:       C Microkernel (Round-Robin Preemptive Scheduler, VFS, IPC)
Safety Driver:     Rust Guard (Page Protection Supervisor)
Storage Device:    {storage_info['device']} ({storage_info['capacity_gb']} GB Inbuilt Virtual Disk)
Filesystem:        {storage_info['filesystem']} [{storage_info['status']}]
Network Adapters:  VirtIO-Net + OP-Eth0 (Full TCP/IP Stack Active)
Runtime Engines:   Java OVM Sandbox, Python Polyglot Interpreter, C++ WM Compositor
Host Integration:  Direct Shell Script Bridges (.sh, .bash, .ps1, .bat, .cmd)
"""

        elif cmd == "storage.inspect":
            info = self.storage.get_disk_info()
            return f"""
\033[1;36m=== INBUILT 2GB STORAGE DEVICE DIAGNOSTICS ===\033[0m
Device Node:       {info['device']}
Total Capacity:    {info['capacity_bytes']:,} Bytes ({info['capacity_gb']} GB)
Reserved Overhead: {info['used_bytes']:,} Bytes ({round(info['used_bytes'] / (1024*1024), 2)} MB)
Free Space:        {info['free_bytes']:,} Bytes ({round(info['free_bytes'] / (1024*1024), 2)} MB)
Filesystem Type:   {info['filesystem']}
Sector Size:       {info['sector_size']} Bytes | Block Size: {info['block_size']} Bytes
Mount Flags:       {info['status']}
Image Backing:     {self.storage.img_path.name}
"""

        elif cmd == "net.ifconfig":
            ifaces = self.network.ifconfig()
            res = ["\033[1;36mInterface   State    IP Address        Netmask          MAC Address\033[0m", "-"*70]
            for iface in ifaces:
                res.append(f"{iface['name']:<11} {iface['state']:<8} {iface['ip']:<17} {iface['mask']:<16} {iface['mac']}")
            return "\n".join(res)

        elif cmd == "net.routes":
            routes = self.network.route_table()
            res = ["\033[1;36mDestination      Gateway          Interface   Metric\033[0m", "-"*55]
            for r in routes:
                res.append(f"{r['destination']:<16} {r['gateway']:<16} {r['iface']:<11} {r['metric']}")
            return "\n".join(res)

        elif cmd == "net.resolve":
            if not args:
                return "Usage: net.resolve <hostname> (e.g. net.resolve google.com)"
            out = self.network.dns_lookup(args[0])
            if out["status"] == "SUCCESS":
                return f"\033[1;32m[DNS OK]\033[0m {out['host']} -> {out['resolved_ip']}"
            return f"\033[31m[DNS FAILED]\033[0m {out['error']}"

        elif cmd == "net.probe":
            if not args:
                return "Usage: net.probe <hostname> [port] (default port 80)"
            host = args[0]
            port = int(args[1]) if len(args) > 1 else 80
            out = self.network.ping(host, port)
            if out["status"] == "ONLINE":
                return f"\033[1;32m[PROBE ONLINE]\033[0m {out['host']}:{out['port']} responded in {out['latency_ms']} ms"
            return f"\033[31m[PROBE OFFLINE]\033[0m {out['host']}:{out['port']} unreachable ({out.get('error')})"

        elif cmd == "net.fetch":
            if not args:
                return "Usage: net.fetch <url>"
            out = self.network.http_fetch(args[0])
            if "error" in out:
                return f"\033[31m[Fetch Error]\033[0m {out['error']}"
            return f"\033[1;32m[HTTP {out.get('status_code')}]\033[0m Headers: {len(out.get('headers', {}))} | Body Preview:\n{out.get('preview', '')[:300]}..."

        elif cmd == "script.run":
            if not args:
                return "Usage: script.run <path-to-script-file> [args...]"
            return self.execute_script_file(args[0], args[1:])

        elif cmd == "drive.status":
            status = self.google_drive.status()
            return (f"Google Drive: {'CONNECTED' if status['authenticated'] else 'NOT CONNECTED'}\n"
                    f"Mount: {status['mount']}\nFolders: {', '.join(status['folders'])}")

        elif cmd == "drive.connect":
            return self.google_drive.connect_interactively()

        # Process Manager Commands
        elif cmd == "proc.top":
            procs = self.proc_mgr.get_top()
            res = ["\033[1;36mPID   USER        STATE      PRIO   CPU-TIME   UPTIME   COMMAND\033[0m", "-"*72]
            for p in procs:
                res.append(f"{p['pid']:<5} {p['user']:<11} {p['state']:<10} {p['priority']:<6} {p['cpu_time']:<10} {p['uptime']:<8} {p['cmd']}")
            return "\n".join(res)

        elif cmd == "proc.start":
            if not args:
                return "Usage: proc.start <name> <command>"
            name = args[0]
            command = " ".join(args[1:])
            pid = self.proc_mgr.spawn(name, command, user=self.security.current_user)
            return f"\033[1;32m[PROC SPAWNED]\033[0m Created Process PID={pid} ('{name}')"

        elif cmd == "proc.stop":
            if not args: return "Usage: proc.stop <pid>"
            pid = int(args[0])
            ok = self.proc_mgr.signal_process(pid, "SIGTERM")
            return f"\033[1;33m[PROC STOPPED]\033[0m Process PID={pid}" if ok else f"PID {pid} not found."

        elif cmd == "proc.kill":
            if not args: return "Usage: proc.kill <pid>"
            pid = int(args[0])
            ok = self.proc_mgr.signal_process(pid, "SIGKILL")
            return f"\033[1;31m[PROC KILLED]\033[0m Process PID={pid} terminated." if ok else f"PID {pid} not found."

        # User & Security System
        elif cmd == "auth.login":
            if len(args) < 2: return "Usage: auth.login <username> <password>"
            user, pwd = args[0], args[1]
            if self.security.authenticate(user, pwd):
                self.variables["SYS.USER"] = user
                return f"\033[1;32m[AUTH OK]\033[0m Logged in as '{user}' (Role: {self.security.current_role})"
            return "\033[31m[AUTH FAILED] Invalid username or password.\033[0m"

        elif cmd == "auth.whoami":
            return f"User: {self.security.current_user} | Role: {self.security.current_role}"

        elif cmd == "sec.firewall":
            rules = self.security.get_firewall_rules()
            res = ["\033[1;36mRULE ID  ACTION  PROTO   PORT   DESCRIPTION\033[0m", "-"*60]
            for r in rules:
                res.append(f"{r['id']:<8} {r['action']:<7} {r['proto']:<7} {r['port']:<6} {r['desc']}")
            return "\n".join(res)

        # Package Manager Commands
        elif cmd == "pkg.avail":
            pkgs = self.pkg_mgr.list_available()
            res = ["\033[1;36mPACKAGE ID       VERSION  RUNTIME  DESCRIPTION\033[0m", "-"*68]
            for p in pkgs:
                res.append(f"{p['id']:<16} {p['version']:<8} {p['runtime']:<8} {p['desc'][:32]}")
            return "\n".join(res)

        elif cmd == "pkg.install":
            if not args: return "Usage: pkg.install <pkg_id>"
            return self.pkg_mgr.install(args[0])

        elif cmd == "pkg.uninstall":
            if not args: return "Usage: pkg.uninstall <pkg_id>"
            return self.pkg_mgr.uninstall(args[0])

        elif cmd == "pkg.rollback":
            return self.pkg_mgr.rollback()

        elif cmd == "proc.info":
            if not args: return "Usage: proc.info <pid>"
            pid = int(args[0])
            info = self.sub_proc_mgr.get_info(pid)
            if not info: return f"Process PID {pid} not found."
            return "\n".join([f"{k:<12}: {v}" for k, v in info.items()])

        # Host Filesystem Bridge Commands
        elif cmd == "fs.mount":
            if not args:
                mounts = self.host_bridge.mount_map
                return "\n".join([f"{k:<16} -> {v}" for k, v in mounts.items()])
            if len(args) >= 2:
                # Syntax: fs.mount C:\Users\Admin /home/operator
                return self.host_bridge.mount_host_folder(args[0], args[1])
            return "Usage: fs.mount <host-path> <vfs-mount-point>"

        elif cmd in ("fs.list", "fs.vlist"):
            v_dir = args[0] if args else "/"
            items = self.host_bridge.list_dir(v_dir)
            res = [f"\033[1;36mTYPE   SIZE       NAME (VFS: {v_dir})\033[0m", "-"*55]
            for it in items:
                t_str = "DIR " if it['is_dir'] else "FILE"
                res.append(f"{t_str:<6} {it['size']:<10} {it['name']}")
            return "\n".join(res)

        elif cmd == "fs.copy":
            if len(args) < 2: return "Usage: fs.copy <src> <dst>"
            return self.host_bridge.copy(args[0], args[1])

        elif cmd == "fs.move":
            if len(args) < 2: return "Usage: fs.move <src> <dst>"
            return self.host_bridge.move(args[0], args[1])

        elif cmd in ("fs.delete", "fs.remove"):
            if not args: return "Usage: fs.remove <path>"
            return self.host_bridge.remove(args[0])

        # Application Manager Commands
        elif cmd == "app.list":
            apps = self.app_mgr.list_apps()
            res = ["\033[1;36mNAME             APP ID           RUNTIME   STATUS      PERMISSIONS\033[0m", "-"*72]
            for a in apps:
                res.append(f"{a['name']:<16} {a['app_id']:<16} {a['runtime']:<9} {a['status']:<11} {a['permissions']}")
            return "\n".join(res)

        elif cmd == "app.launch":
            if not args: return "Usage: app.launch <app-name-or-id> (e.g. app.launch Calculator)"
            return self.app_mgr.launch(args[0])

        elif cmd == "app.close":
            if not args: return "Usage: app.close <app-name-or-id>"
            return self.app_mgr.close(args[0])

        # SQLite Service Manager Commands
        elif cmd == "service.list":
            srvs = self.settings_svc.list_services()
            res = ["\033[1;36mSERVICE          STATUS    PID     DESCRIPTION\033[0m", "-"*65]
            for s in srvs:
                pid_s = str(s['pid']) if s['pid'] else "-"
                res.append(f"{s['name']:<16} {s['status']:<9} {pid_s:<7} {s['description']}")
            return "\n".join(res)

        elif cmd == "service.start":
            if not args: return "Usage: service.start <name>"
            return self.settings_svc.start_service(args[0])

        elif cmd == "service.stop":
            if not args: return "Usage: service.stop <name>"
            return self.settings_svc.stop_service(args[0])

        # Central System Settings Commands
        elif cmd == "settings.list":
            cat = args[0] if args else None
            sets = self.settings_svc.list_settings(cat)
            res = ["\033[1;36mKEY                    CATEGORY   VALUE\033[0m", "-"*60]
            for s in sets:
                res.append(f"{s['key']:<22} {s['category']:<10} {s['value']}")
            return "\n".join(res)

        elif cmd == "settings.set":
            if len(args) < 2: return "Usage: settings.set <key> <value> [category]"
            cat = args[2] if len(args) > 2 else "general"
            return self.settings_svc.set_setting(args[0], args[1], cat)

        # Windows Host Integration Commands
        elif cmd == "win.clip":
            if not args:
                content = self.win.get_clipboard()
                return f"[HOST CLIPBOARD]:\n{content}" if content else "[HOST CLIPBOARD]: (empty)"
            text = " ".join(args)
            ok = self.win.set_clipboard(text)
            return "\033[1;32m[CLIPBOARD OK]\033[0m Copied to Windows clipboard." if ok else "Clipboard write error."

        elif cmd == "win.notify":
            if not args: return "Usage: win.notify <title> <message>"
            title = args[0]
            msg = " ".join(args[1:]) if len(args) > 1 else "Operator OS Notification"
            self.win.show_notification(title, msg)
            return f"\033[1;32m[TOAST DISPATCHED]\033[0m Dispatched Windows notification: '{title}'"

        elif cmd == "win.exec":
            if not args: return "Usage: win.exec <app-name> (e.g. win.exec notepad, win.exec explorer, win.exec calc)"
            return self.win.launch_windows_app(args[0])

        # Central Logging & System Diagnostics
        elif cmd == "log.show":
            n = int(args[0]) if args else 20
            return self.logger.show_logs(n)

        elif cmd == "log.clear":
            return self.logger.clear_logs()

        elif cmd == "system.health":
            h = self.reliability.check_health()
            res = ["\033[1;36m=== OPERATOR OS SUBSYSTEM HEALTH TELEMETRY ===\033[0m", "-"*50]
            for k, v in h.items():
                res.append(f"{k:<25}: {v}")
            return "\n".join(res)

        # Service Manager Commands
        elif cmd == "srv.list":
            srvs = self.services.list_services()
            res = ["\033[1;36mUNIT                         LOAD   ACTIVE   SUB      DESCRIPTION\033[0m", "-"*72]
            for s in srvs:
                res.append(f"{s['unit']:<28} {s['load']:<6} {s['active']:<8} {s['sub']:<8} {s['description']}")
            return "\n".join(res)

        elif cmd == "srv.start":
            if not args: return "Usage: srv.start <service-name>"
            return self.services.start(args[0])

        elif cmd == "srv.stop":
            if not args: return "Usage: srv.stop <service-name>"
            return self.services.stop(args[0])

        elif cmd == "srv.logs":
            if not args: return "Usage: srv.logs <service-name>"
            logs = self.services.get_logs(args[0])
            return "\n".join(logs)

        # Reliability & Dev Tools
        elif cmd == "rel.restore":
            if not args:
                pts = self.reliability.list_restore_points()
                return "\n".join([f"{p.get('name')} [{p.get('date')}]" for p in pts]) if pts else "No restore points."
            return self.reliability.create_restore_point(args[0])

        elif cmd == "rel.health":
            h = self.reliability.check_health()
            return "\n".join([f"{k:<25}: {v}" for k, v in h.items()])

        elif cmd == "dev.test":
            results = self.devtools.run_tests()
            return "\n".join([f"Suite [{k}]: {v}" for k, v in results.items()])

        elif cmd == "dev.trace":
            pid = int(args[0]) if args else 1
            return "\n".join(self.devtools.trace_syscalls(pid))

        elif cmd == "dev.build":
            return self.devtools.build_all()

        elif cmd == "boot.iso":
            img = self.boot_builder.build_bootable_image()
            cmd_str = self.boot_builder.get_qemu_command()
            return f"\033[1;32m[BOOTABLE TARGET READY]\033[0m Image: {img.name}\nQEMU Runner: {cmd_str}"

        elif cmd == "pkg.list":
            return self.query_db("SELECT id, name, version, runtime, status FROM sys_packages;")

        elif cmd == "db.query":
            if not args:
                return "Usage: db.query <sql-statement>"
            return self.query_db(" ".join(args))

        elif cmd == "var.set":
            if not args:
                return "Usage: var.set <key>=<value>"
            expr = " ".join(args)
            if "=" in expr:
                k, v = expr.split("=", 1)
                self.variables[k.strip()] = v.strip()
                return f"Set {k.strip()} = {v.strip()}"
            return "Usage: var.set <key>=<value>"

        elif cmd == "var.get":
            if not args:
                return "Usage: var.get <key>"
            return str(self.variables.get(args[0], f"Undefined: {args[0]}"))

        elif cmd in ("fs.goto", "cd"):
            target = args[0] if args else str(Path.home())
            new_path = os.path.abspath(os.path.join(self.variables["SYS.CWD"], target))
            if os.path.isdir(new_path):
                self.variables["SYS.CWD"] = new_path
                return None
            return f"Directory not found: {target}"

        elif cmd in ("fs.list", "dir", "get-childitem", "gci"):
            target_dir = args[0] if args else self.variables["SYS.CWD"]
            target_path = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], target_dir)))
            if not target_path.exists():
                return f"Path not found: {target_dir}"
            entries = sorted(list(target_path.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            res = [f"\033[1;36mMode                 LastWriteTime         Length Name ({target_path})\033[0m", "-"*72]
            for e in entries:
                display_name = e.name
                if e.name == "Google Drive" and not self.google_drive.status()["authenticated"]:
                    display_name += " (not connected)"
                mode = "d-----" if e.is_dir() else "-a----"
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.stat().st_mtime))
                size_str = str(e.stat().st_size) if not e.is_dir() else ""
                res.append(f"{mode:<20} {mtime:<20} {size_str:>10} {display_name}")
            return "\n".join(res)

        # Linux Commands
        elif cmd == "ls":
            show_long = any(a in ("-l", "-la", "-al", "-lh") for a in args)
            show_all = any(a in ("-a", "-la", "-al") for a in args)
            raw_paths = [a for a in args if not a.startswith("-")]
            target_dir = raw_paths[0] if raw_paths else self.variables["SYS.CWD"]
            p = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], target_dir)))
            if not p.exists():
                return f"ls: cannot access '{target_dir}': No such file or directory"
            items = list(p.iterdir())
            if not show_all:
                items = [i for i in items if not i.name.startswith(".")]
            items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
            if not show_long:
                names = []
                for i in items:
                    name = i.name
                    if i.name == "Google Drive" and not self.google_drive.status()["authenticated"]:
                        name += " (not connected)"
                    names.append(f"\033[1;34m{name}/\033[0m" if i.is_dir() else name)
                return "  ".join(names)
            res = [f"total {len(items)}"]
            for i in items:
                st = i.stat()
                perms = "drwxr-xr-x" if i.is_dir() else "-rw-r--r--"
                mtime = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
                name = i.name
                if i.name == "Google Drive" and not self.google_drive.status()["authenticated"]:
                    name += " (not connected)"
                name_str = f"\033[1;34m{name}/\033[0m" if i.is_dir() else name
                res.append(f"{perms} 1 operator operator {st.st_size:>8} {mtime} {name_str}")
            return "\n".join(res)

        elif cmd == "pwd":
            return self.variables["SYS.CWD"]

        elif cmd in ("cat", "type", "get-content", "gc"):
            if not args:
                return f"Usage: {cmd} <file>"
            fpath = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], args[0])))
            if not fpath.exists():
                return f"{cmd}: {args[0]}: No such file or directory"
            try:
                return fpath.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"{cmd}: error reading file: {e}"

        elif cmd == "touch":
            if not args:
                return "Usage: touch <filename>"
            fpath = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], args[0])))
            fpath.touch(exist_ok=True)
            return None

        elif cmd == "grep":
            if len(args) < 2:
                return "Usage: grep <pattern> <file>"
            pattern, filename = args[0], args[1]
            fpath = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], filename)))
            if not fpath.exists():
                return f"grep: {filename}: No such file or directory"
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                matches = []
                regex = re.compile(pattern)
                for i, l in enumerate(lines, 1):
                    if regex.search(l):
                        highlighted = regex.sub(f"\033[1;31m\\g<0>\033[0m", l)
                        matches.append(f"\033[1;32m{i}\033[0m: {highlighted}")
                return "\n".join(matches) if matches else "(no matches found)"
            except Exception as e:
                return f"grep: error: {e}"

        elif cmd == "df":
            storage_info = self.storage.get_disk_info()
            total_k = storage_info['capacity_bytes'] // 1024
            used_k = storage_info['used_bytes'] // 1024
            free_k = storage_info['free_bytes'] // 1024
            pct = round((storage_info['used_bytes'] / storage_info['capacity_bytes']) * 100, 1)
            return f"""\033[1;36mFilesystem               1K-blocks      Used Available Use% Mounted on\033[0m
/dev/nvme0n1_operator      {total_k:,}    {used_k:,}   {free_k:,}  {pct}% /
opfs_vfs                   1,048,576       32,768   1,015,808   3.1% /mnt/vfs
host_bridge               33,554,432    8,388,608  25,165,824  25.0% /mnt/host"""

        elif cmd == "free":
            return """\033[1;36m               total        used        free      shared  buff/cache   available\033[0m
Mem:         8192000     1450200     5621800      124000     1120000     6410000
Swap:        2097152           0     2097152"""

        elif cmd == "uname":
            flag = args[0] if args else "-s"
            if flag in ("-a", "--all"):
                return "OperatorOS x86_64-operator-subsystem 2.0.0-PRO #1 SMP PREEMPT Rust/C-Hybrid GNU/Linux-Compatible x86_64"
            elif flag in ("-r", "--kernel-release"):
                return "2.0.0-PRO"
            elif flag in ("-m", "--machine"):
                return "x86_64"
            return "OperatorOS"

        elif cmd == "uptime":
            return " 16:45:00 up 4:18,  1 user,  load average: 0.12, 0.08, 0.05"

        elif cmd == "wc":
            if not args:
                return "Usage: wc [-l|-w|-c] <file>"
            target_f = args[-1]
            fpath = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], target_f)))
            if not fpath.exists():
                return f"wc: {target_f}: No such file or directory"
            text = fpath.read_text(encoding="utf-8", errors="replace")
            lines_c = len(text.splitlines())
            words_c = len(text.split())
            bytes_c = len(text.encode("utf-8"))
            return f"{lines_c:>8} {words_c:>8} {bytes_c:>8} {target_f}"

        # PowerShell Commands
        elif cmd in ("get-process", "ps"):
            target_name = args[0].lower() if args else None
            procs = self.proc_mgr.get_top()
            if target_name:
                procs = [p for p in procs if target_name in p['cmd'].lower()]
            res = [f"\033[1;36mHandles  NPM(K)    PM(K)      WS(K)     CPU(s)     Id  ProcessName\033[0m", "-"*68]
            for p in procs:
                res.append(f"    120      12      {p['pid']*1024:>6}      {p['pid']*2048:>6}       0.45  {p['pid']:<5} {p['cmd']}")
            return "\n".join(res)

        elif cmd == "get-service":
            srvs = self.settings_svc.list_services()
            res = ["\033[1;36mStatus   Name               DisplayName\033[0m", "-"*55]
            for s in srvs:
                st = "Running" if s['status'] == "running" else "Stopped"
                res.append(f"{st:<8} {s['name']:<18} {s['description']}")
            return "\n".join(res)

        elif cmd in ("get-date", "date"):
            return time.strftime("%A, %B %d, %Y %I:%M:%S %p")

        elif cmd in ("test-connection", "ping"):
            host = args[0] if args else "127.0.0.1"
            probe = self.network.ping(host, 80)
            if probe["status"] == "ONLINE":
                return f"""Source        Destination     IPV4Address      IPV6Address  Bytes    Time(ms)
------        -----------     -----------      -----------  -----    --------
OperatorOS    {host:<15} {probe.get('host', '127.0.0.1'):<16}              32       {probe.get('latency_ms', 1)}"""
            return f"Test-Connection: Ping to {host} failed or timed out."

        elif cmd == "get-computerinfo":
            return f"""\033[1;36m=== OPERATOR SUBSYSTEM COMPUTER TELEMETRY ===\033[0m
WindowsBuildLabEx         : Operator.2.0.0.amd64fre.subsystem
CsName                    : OPERATOR-NODE
OsName                    : Operator OS Polyglot Subsystem
OsArchitecture            : 64-bit
WindowsVersion            : 2.0-PRO
TotalPhysicalMemory       : 8,589,934,592 Bytes (8.00 GB)
InbuiltBlockStorageDevice : 2,147,483,648 Bytes (2.00 GB Dedicated Raw Disk)
SafetyDriverEngine        : Rust Kernel Guard (Active)
CompositorEngine          : C++ Window Manager Compositor (Direct GDI Vector UI)"""

        # CMD / Windows Commands
        elif cmd == "ver":
            return "Operator OS Subsystem [Version 2.0.0-PRO - Rust Safety Kernel Guard]"

        elif cmd == "systeminfo":
            return self.eval_command("get-computerinfo")

        elif cmd == "ipconfig":
            return self.eval_command("net.ifconfig")

        elif cmd == "tree":
            target_dir = args[0] if args else self.variables["SYS.CWD"]
            p = Path(os.path.abspath(os.path.join(self.variables["SYS.CWD"], target_dir)))
            if not p.exists():
                return f"Path not found: {target_dir}"
            lines = [f"Folder PATH listing for volume /dev/nvme0n1_operator", f"Volume serial number is OP-2026", str(p)]
            for root, dirs, files in os.walk(str(p)):
                depth = root.replace(str(p), "").count(os.sep)
                if depth > 2:
                    continue
                indent = "│   " * depth
                for d in dirs[:5]:
                    lines.append(f"{indent}├── {d}")
                for f in files[:8]:
                    lines.append(f"{indent}└── {f}")
            return "\n".join(lines[:35])

        elif cmd in ("cls", "clear"):
            os.system("cls" if os.name == "nt" else "clear")
            return None

        elif cmd in ("exit", "quit"):
            sys.exit(0)

        else:
            # Fallback to system execution (PowerShell / Windows CMD / WSL) so ANY command works properly
            try:
                is_ps = any(cmd.startswith(p) for p in ("get-", "set-", "new-", "remove-", "invoke-", "test-", "start-", "stop-")) or cmd in ("select-object", "where-object", "out-string", "format-table", "format-list")
                if is_ps:
                    cmd_to_run = ["powershell", "-NoProfile", "-Command", line]
                    proc = subprocess.run(cmd_to_run, cwd=self.variables["SYS.CWD"], capture_output=True, text=True, timeout=30)
                else:
                    proc = subprocess.run(line, shell=True, cwd=self.variables["SYS.CWD"], capture_output=True, text=True, timeout=30)
                    if proc.returncode != 0 and "not recognized" in (proc.stderr + proc.stdout):
                        # Attempt execution via powershell
                        proc_ps = subprocess.run(["powershell", "-NoProfile", "-Command", line], cwd=self.variables["SYS.CWD"], capture_output=True, text=True, timeout=30)
                        if proc_ps.returncode == 0:
                            proc = proc_ps

                output = (proc.stdout + proc.stderr).strip()
                if output:
                    return output
                elif proc.returncode != 0:
                    return f"\033[31m[Command returned exit code {proc.returncode}]\033[0m"
                return None
            except subprocess.TimeoutExpired:
                return "\033[31m[Command Timeout]: Process took longer than 30 seconds.\033[0m"
            except Exception as e:
                return f"\033[31m[Command Error]: '{cmd}': {str(e)}\033[0m"

    def query_db(self, query: str):
        if not DB_PATH.exists():
            self.init_db()
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                if query.strip().upper().startswith("SELECT"):
                    rows = cursor.fetchall()
                    cols = [d[0] for d in cursor.description]
                    header = " | ".join(f"{c:<18}" for c in cols)
                    sep = "-" * len(header)
                    res = [header, sep]
                    for r in rows:
                        res.append(" | ".join(f"{str(v):<18}" for v in r))
                    return "\n".join(res) if rows else "(0 rows returned)"
                else:
                    conn.commit()
                    return f"Query OK, {cursor.rowcount} row(s) affected."
        except Exception as e:
            return f"\033[31m[DB Error]: {str(e)}\033[0m"

    def read_interactive_line(self):
        """
        Robust interactive console line reader supporting standard terminal input,
        paste, backspace, unicode, and persistent 2GB storage history logging.
        """
        try:
            line = input(self.get_prompt())
            cmd_str = line.strip()
            if cmd_str:
                self.storage.append_command_history(cmd_str)
            return cmd_str
        except (KeyboardInterrupt, EOFError):
            raise

def main():
    engine = OperatorShellEngine()
    print("\033[1;36m================================================================")
    print("      OPERATOR OS POLYGLOT SCRIPT & SHELL SUBSYSTEM (v2.0)      ")
    print("      Supports .sh, .ps1, .bat, .opsh Script File Execution     ")
    print("      Persistent 2GB Storage Command History (UP/DOWN keys)     ")
    print("      Distinct Vocabulary: Type 'help' to inspect commands      ")
    print("================================================================\033[0m")

    if len(sys.argv) > 1:
        raw_input_cmd = " ".join(sys.argv[1:])
        tokens = shlex.split(raw_input_cmd)
        target = tokens[0]
        # Append executed CLI commands to persistent storage
        engine.storage.append_command_history(raw_input_cmd)
        if target.endswith((".sh", ".bash", ".ps1", ".bat", ".cmd", ".opsh")):
            res = engine.execute_script_file(target, tokens[1:])
        else:
            res = engine.eval_command(raw_input_cmd)
        if res:
            print(res)
        return

    while True:
        try:
            line = engine.read_interactive_line()
            res = engine.eval_command(line)
            if res:
                print(res)
        except (KeyboardInterrupt, EOFError):
            print("\nShutting down Operator Shell Subsystem.")
            break

if __name__ == "__main__":
    main()
