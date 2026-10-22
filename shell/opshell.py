#!/usr/bin/env python3
"""
Operator Polyglot Script & Shell Engine (opshell)
Version 2.0.0

Key Features:
1. Native Execution of Shell Script Files:
   - Bash/Linux Shell Scripts (.sh, .bash) via Linux/WSL runtime
   - PowerShell Scripts (.ps1) via PowerShell runtime
   - Command Prompt Batch Scripts (.bat, .cmd) via CMD runtime
   - Java source files (.java) via the Operator Java runtime
   - C source files (.c) via the Operator native toolchain
   - Operator OS Script Files (.opsh, .ops) via Native Operator Grammar
2. Distinct Custom Command Vocabulary (Different from standard shells):
   - `sys.probe`           -> Probe hardware, kernel, memory, 2GB disk, and scheduler
   - `storage.inspect`     -> 2GB block device stats, partition mapping, block allocation
   - `net.ifconfig`        -> List network interfaces, IP addresses, MACs
   - `net.routes`          -> Kernel routing table
   - `net.resolve <host>`  -> DNS domain lookup
   - `net.probe <host>`    -> Latency probe & port ping
   - `net.fetch <url>`     -> Network HTTP socket fetcher
   - `script.run <file>`   -> Execute a POW workflow
   - `powcurl <file>`      -> Run a Rust/C media playback script
   - `pkg.list`            -> Registry query of installed OS packages
   - `pkg.install <name>`  -> Install new package definition
   - `db.query <sql>`      -> Run direct SQL queries against OS registry
   - `proc.list`           -> Active process table
   - `var.set <k>=<v>`     -> Environment variable store
   - `var.get <k>`         -> Environment variable read
"""

import os
import sys
import io
import subprocess
import shutil
import shlex
import sqlite3
import re
import time
import fnmatch
import copy
from typing import Optional
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
VYN_RUNTIME_DIR = Path(
    os.environ.get(
        "OPERATOR_VYN_HOME",
        str(ROOT_DIR.parent.parent / "lua" / "vyn" / "vyn"),
    )
).expanduser()
DB_PATH = ROOT_DIR / "db" / "operator_system.db"
sys.path.insert(0, str(ROOT_DIR))


def _split_shell_commands(line: str) -> list[str]:
    commands = []
    current = []
    quote = None
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\":
            next_char = line[index + 1] if index + 1 < len(line) else ""
            if next_char in ("\\", "'", '"') or (
                quote != "'" and next_char == ";"
            ):
                current.extend((char, next_char))
                index += 2
                continue
        if quote:
            if char == quote:
                quote = None
            current.append(char)
        elif char in ("'", '"'):
            quote = char
            current.append(char)
        elif char == ";":
            command = "".join(current).strip()
            if command:
                commands.append(command)
            current = []
        else:
            current.append(char)
        index += 1

    if quote:
        raise ValueError("unterminated quoted string")
    command = "".join(current).strip()
    if command:
        commands.append(command)
    return commands


def _parse_shell_words(command: str) -> list[str]:
    words = []
    current = []
    quote = None
    token_started = False
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\":
            next_char = command[index + 1] if index + 1 < len(command) else ""
            escapable = (
                ("'" if quote == "'" else '"\' ;\\')
                if quote != "'"
                else "'\\"
            )
            if next_char and next_char in escapable:
                current.append(next_char)
                token_started = True
                index += 2
                continue
            current.append(char)
            token_started = True
        elif quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in ("'", '"'):
            quote = char
            token_started = True
        elif char.isspace():
            if token_started:
                words.append("".join(current))
                current = []
                token_started = False
        else:
            current.append(char)
            token_started = True
        index += 1

    if quote:
        raise ValueError("unterminated quoted string")
    if token_started:
        words.append("".join(current))
    return words


SPECIAL_COMMAND_HELP = {
    "app.close": ("app.close <name-or-id>", "Stop a running app launched by the manifest manager."),
    "app.launch": ("app.launch <name-or-id>", "Launch an installed app from its manifest; app names with spaces may be quoted."),
    "app.list": ("app.list", "List installed manifest-based applications and their current status."),
    "auth.login": ("auth.login <username>", "Authenticate an Operator OS account."),
    "auth.whoami": ("auth.whoami", "Show the currently authenticated account."),
    "backup.create": ("backup.create <name>", "Create a named persistent restore point; requires root."),
    "boot.iso": ("boot.iso [options]", "Build the configured bootable target from Operator OS components."),
    "cron.add": ("cron.add <name> <seconds> <safe-command...>", "Schedule an allowlisted recurring action. Minimum interval is 10 seconds."),
    "cron.list": ("cron.list", "List recurring jobs, owners, next-run times, and status."),
    "cron.logs": ("cron.logs <name> [count]", "Read persistent output logs for a scheduled job."),
    "cron.remove": ("cron.remove <name>", "Remove a scheduled job."),
    "db.query": ("db.query <sql>", "Run a SQL query against the Operator system registry."),
    "date": ("date", "Display the current local time using the Operator time service."),
    "device.list": ("device.list [usb|display|audio]", "List host devices visible to Operator, including Plug and Play status and driver details."),
    "dev.build": ("dev.build [target]", "Run an Operator development build target."),
    "dev.test": ("dev.test [target]", "Run Operator subsystem tests."),
    "dev.trace": ("dev.trace [options]", "Inspect syscall and subsystem execution traces."),
    "drive.download": ("drive.download <file-id-or-path>", "Download a Drive file into the current user's mounted Drive folder."),
    "drive.connect": ("drive.connect", "Configure or connect Google Drive through rclone."),
    "drive.ls": ("drive.ls [remote-path]", "List files from the mounted Google Drive account."),
    "drive.mount": ("drive.mount", "Configure or connect a Google Drive remote with rclone."),
    "drive.status": ("drive.status", "Show current Drive mount and authentication status."),
    "drive.upload": ("drive.upload <path>", "Upload a file while Drive writes are unlocked."),
    "drive.write.setup": ("drive.write.setup", "Set a local passphrase protecting Drive uploads."),
    "drive.write.unlock": ("drive.write.unlock", "Unlock Drive uploads for the current time-limited session."),
    "fs.copy": ("fs.copy <source> <destination>", "Copy files through the mounted virtual filesystem."),
    "fs.delete": ("fs.delete <path>", "Remove a file or directory through the virtual filesystem."),
    "fs.goto": ("fs.goto <path>", "Navigate to a mounted virtual filesystem location."),
    "fs.list": ("fs.list <path>", "List a mounted virtual filesystem directory."),
    "fs.mount": ("fs.mount <host-path> <vfs-path>", "Mount a host directory into Operator's virtual filesystem."),
    "fs.move": ("fs.move <source> <destination>", "Move files through the mounted virtual filesystem."),
    "fs.remove": ("fs.remove <path>", "Remove a file or directory through the virtual filesystem."),
    "fs.vlist": ("fs.vlist <path>", "List a mounted virtual filesystem directory."),
    "games.list": ("games.list", "List installed game executables under the active user's Games directory."),
    "games.launch": ("games.launch <name> [args...]", "Launch an installed game with its LÖVE runtime and request the Windows high-performance GPU."),
    "game.launch": ("game.launch <name> [args...]", "Alias for games.launch."),
    "get-date": ("get-date", "Display the current local time using the Operator time service."),
    "gpu.active": ("gpu.active", "Report whether a GPU compute backend is available."),
    "gpu.ai": ("gpu.ai", "Show the selected GPU/CPU acceleration backend."),
    "gpu.compute": ("gpu.compute", "Probe whether GPU compute is available."),
    "gpu.probe": ("gpu.probe", "Show detected GPU hardware, driver details, and status."),
    "help": ("help [command|menu]", "Show command categories, a specific feature's help, or the complete feature help menu."),
    "log.clear": ("log.clear", "Clear the Operator OS central log."),
    "log.show": ("log.show [count]", "Display recent Operator OS central log entries."),
    "mem": ("mem", "Show live host RAM and swap usage."),
    "mem.user": ("mem.user [name]", "Inspect an account's allocated memory pool and virtual pages."),
    "nano": ("nano [file]", "Open the Operator code editor; installed language packs suggest completions while typing."),
    "net.fetch": ("net.fetch <url>", "Fetch an HTTP resource through the Operator networking layer."),
    "net.ifconfig": ("net.ifconfig", "List network adapters and assigned addresses."),
    "net.probe": ("net.probe <host> [port]", "Probe host reachability and TCP latency."),
    "net.resolve": ("net.resolve <host>", "Resolve a hostname through the Operator networking layer."),
    "net.routes": ("net.routes", "Display the host-assisted network routing table."),
    "net.speed": ("net.speed", "Continuously measure download, upload, and average network speed; press Ctrl+C to stop."),
    "passd": ("passd <command...>", "Authenticate as root and run one privileged Operator command."),
    "passd.setup": ("passd.setup", "Create or change the separate passd password; changes require the current password."),
    "python.check": ("python.check <file.py>", "Compile-check a Python source file without executing it."),
    "python.run": ("python.run <file.py> [args...]", "Run a Python source file with the active host Python interpreter."),
    "pkg.avail": ("pkg.avail", "List packages available in the local Operator package repository."),
    "pkg.install": ("pkg.install <package-id>", "Install a package definition from the local repository."),
    "pkg.list": ("pkg.list", "List installed Operator packages."),
    "pkg.rollback": ("pkg.rollback <package-id>", "Roll back the most recent package change when a previous version exists."),
    "pkg.uninstall": ("pkg.uninstall <package-id>", "Uninstall an Operator package."),
    "pow": ("pow <workflow.pow>", "Execute a POW automation workflow."),
    "pow.exec": ("pow.exec <workflow.pow>", "Execute a POW automation workflow."),
    "powcurl": ("powcurl <script.powcurl>", "Run a Rust/C media script through the built powcurl runtime."),
    "proc.info": ("proc.info <pid>", "Inspect a managed process."),
    "proc.kill": ("proc.kill <pid>", "Terminate a process; system processes require root."),
    "proc.list": ("proc.list", "List active processes managed or observed by Operator OS."),
    "proc.start": ("proc.start <name> <command...>", "Start a managed subsystem process."),
    "proc.stop": ("proc.stop <pid>", "Stop a managed process."),
    "proc.top": ("proc.top", "Show the current process resource summary."),
    "rel.health": ("rel.health", "Inspect reliability and recovery health status."),
    "rel.restore": ("rel.restore <name>", "Restore an available named Operator restore point."),
    "script.run": ("script.run <workflow.pow>", "Execute a POW workflow file."),
    "sec.firewall": ("sec.firewall [options]", "Inspect or configure the Operator security firewall."),
    "service.list": ("service.list", "List registered settings-backed service records."),
    "service.start": ("service.start <name>", "Start a settings-backed service record."),
    "service.stop": ("service.stop <name>", "Stop a settings-backed service record."),
    "settings.list": ("settings.list [category]", "List central Operator system settings."),
    "settings.set": ("settings.set <key> <value> [category]", "Save an Operator system setting."),
    "ssh": ("ssh <user@host> [command...]", "Connect through the host OpenSSH client."),
    "ssh.key.add": ("ssh.key.add <user> <public-key-file>", "Enroll an Ed25519 public key for an existing Operator account."),
    "ssh.key.list": ("ssh.key.list [user]", "List enrolled Atlas SSH key fingerprints."),
    "ssh.key.remove": ("ssh.key.remove <user> <fingerprint>", "Revoke an enrolled Atlas SSH key."),
    "ssh.server": ("ssh.server <start|status|stop> [options]", "Control the isolated Atlas SSH server; it listens on loopback by default."),
    "srv.list": ("srv.list", "Show managed service state, health, PID, restart count, policy, and description."),
    "srv.logs": ("srv.logs <name> [count]", "Read persistent output logs for a managed service."),
    "srv.register": ("srv.register <name> [options] -- <executable> [args...]", "Register and automatically start a native process service; restart policy defaults to always."),
    "srv.remove": ("srv.remove <name>", "Remove a stopped managed service definition."),
    "srv.restart": ("srv.restart <name>", "Restart a managed service."),
    "srv.start": ("srv.start <name>", "Start and supervise a registered service; service control requires root."),
    "srv.stop": ("srv.stop <name>", "Stop a running registered service; service control requires root."),
    "storage.cleanup": ("storage.cleanup [age-days]", "Clean old files from temporary storage; shared cleanup requires root."),
    "storage.inspect": ("storage.inspect", "Inspect the virtual block device, filesystem, capacity, and allocation."),
    "sys.probe": ("sys.probe", "Show combined kernel, CPU, memory, GPU, storage, and scheduler telemetry."),
    "system.health": ("system.health", "Run live subsystem health checks."),
    "time": ("time", "Display the local clock corrected by the latest successful NTP sample, if available."),
    "time.service": ("time.service [status|start|sync [ntp-server]]", "Run the background read-only NTP synchronization service and inspect its status. It never changes the Windows system clock."),
    "vyn.run": ("vyn.run <file.vyn>", "Run a Vyn script using the configured Vyn interpreter."),
    "user.create": ("user.create <name> <password>", "Create an isolated Operator account and its storage hierarchy."),
    "user.delete": ("user.delete <name>", "Delete an Operator account and reclaim its private storage."),
    "user.list": ("user.list", "List Operator accounts."),
    "user.login": ("user.login <name> <password>", "Authenticate and switch to an Operator account."),
    "user.memory": ("user.memory [name]", "Inspect an account's allocated memory pool and virtual pages."),
    "user.switch": ("user.switch <name>", "Switch the active Operator account."),
    "logout": ("logout", "Switch back to the default operator account."),
    "user.whoami": ("user.whoami", "Display the active Operator account and role."),
    "var.get": ("var.get <name>", "Read a shell environment variable."),
    "var.set": ("var.set <name>=<value>", "Set a shell environment variable."),
    "win.clip": ("win.clip [text...]", "Read or write the Windows host clipboard."),
    "win.exec": ("win.exec <app>", "Launch a supported Windows host application."),
    "win.notify": ("win.notify <title> <message>", "Show a Windows host notification."),
}


from storage.storage_manager import OperatorStorageManager
from network.net_stack import OperatorNetworkStack
from network.ssh_service import OperatorSSHService
from integrations.rclone_drive import RcloneDriveManager
from core.process.process_manager import RealProcessManager
from core.process.subsystem_proc_mgr import SubsystemProcessManager
from core.security.security_manager import SecurityManager
from packages.package_manager import PackageManager
from storage.vfs.vfs_engine import VirtualFileSystem
from storage.vfs.host_fs_bridge import HostFilesystemBridge
from core.process.app_manager import ApplicationManager
from core.process.game_manager import GameManager
from core.services.service_manager import ServiceManager
from core.services.time_service import TimeService
from core.settings.settings_service import SystemSettingsService
from core.windows.win_integration import WindowsIntegrationLayer
from core.logger.central_logger import CentralLogger
from core.reliability.reliability_manager import ReliabilityManager
from core.devtools.dev_tools import DeveloperTools
from boot_target.boot_builder import BootableTargetBuilder
from pow.engine import PowEngine
from core.gpu.gpu_manager import GPUManager
from core.devices.device_manager import DeviceManager
from apps.nano import OperatorCodeEditor
from core.security.user_manager import UserManager
from core.memory.user_memory_manager import UserMemoryManager
from network.speed_test import NetworkSpeedTester

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.box import ROUNDED
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.formatted_text import ANSI


class AtlasCompleter(Completer):
    def __init__(self, commands: list, get_cwd_func, storage_mgr):
        self.commands = sorted(commands)
        self.get_cwd = get_cwd_func
        self.storage = storage_mgr

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        if len(words) <= 1 and not text.endswith(" "):
            prefix = words[0] if words else ""
            for cmd in self.commands:
                if cmd.lower().startswith(prefix.lower()):
                    yield Completion(cmd, start_position=-len(prefix))
        else:
            prefix = words[-1] if not text.endswith(" ") else ""
            command = words[0].lower() if words else ""
            command_position = 1
            if command == "passd" and len(words) >= 2 and words[1] == "-u":
                command_position = 3
            is_privileged_command = command in ("passd", "sudo")
            is_privileged_command_word = is_privileged_command and (
                len(words) <= command_position
                or (len(words) == command_position + 1 and not text.endswith(" "))
            )
            is_ssh_server_command_word = command == "ssh.server" and (
                len(words) <= 1
                or (len(words) == 2 and not text.endswith(" "))
            )
            if is_privileged_command_word:
                if (
                    command == "passd"
                    and command_position == 1
                    and "setup".startswith(prefix.lower())
                ):
                    yield Completion("setup", start_position=-len(prefix))
                for candidate in self.commands:
                    if " " not in candidate and candidate.lower().startswith(prefix.lower()):
                        yield Completion(candidate, start_position=-len(prefix))
                return
            if is_ssh_server_command_word:
                for candidate in ("start", "status", "stop"):
                    if candidate.startswith(prefix.lower()):
                        yield Completion(candidate, start_position=-len(prefix))
                return

            quote = ""
            raw_prefix = prefix
            if prefix.startswith('"') or prefix.startswith("'"):
                quote = prefix[0]
                raw_prefix = prefix[1:]

            cwd = self.get_cwd()
            search_vdir = cwd
            match_prefix = raw_prefix
            directory_prefix = ""
            separator_index = max(raw_prefix.rfind("/"), raw_prefix.rfind("\\"))
            if separator_index >= 0:
                directory_prefix = raw_prefix[:separator_index + 1]
                rel_vdir = raw_prefix[:separator_index]
                match_prefix = raw_prefix[separator_index + 1:]
                if not rel_vdir and directory_prefix:
                    search_vdir = "/"
                else:
                    search_vdir = self.storage.normalize_vpath(rel_vdir, cwd)

            try:
                entries = self.storage.virtual_listdir(search_vdir, cwd)
                for entry in entries:
                    ename = entry["name"]
                    if ename.lower().startswith(match_prefix.lower()):
                        disp = ename + ("/" if entry["is_dir"] else "")
                        if " " in disp and not quote:
                            disp = f'"{disp}"'
                        yield Completion(
                            directory_prefix + disp,
                            start_position=-len(raw_prefix),
                        )
            except Exception:
                pass


class OperatorShellEngine:
    def __init__(self):
        self.storage = OperatorStorageManager()
        self.network = OperatorNetworkStack()
        self.google_drive = RcloneDriveManager(self.network, self.storage)
        self.proc_mgr = RealProcessManager()
        self.sub_proc_mgr = SubsystemProcessManager()
        self.security = SecurityManager()
        self.pkg_mgr = PackageManager()
        self.vfs = VirtualFileSystem()
        self.host_bridge = HostFilesystemBridge()
        self.app_mgr = ApplicationManager()
        self.services = None
        self.service_runtime_error = None
        self.settings_svc = SystemSettingsService()
        self.win = WindowsIntegrationLayer()
        self.logger = CentralLogger()
        self.reliability = ReliabilityManager()
        self.devtools = DeveloperTools()
        self.boot_builder = BootableTargetBuilder()
        self.gpu = GPUManager()
        self.device_manager = DeviceManager()
        self.game_mgr = GameManager(self.gpu)
        self.pow = PowEngine(ROOT_DIR, operator_runner=self.eval_command)
        self.user_mgr = UserManager()
        self.mem_mgr = UserMemoryManager()
        self.time_service = TimeService()
        self.time_service.start()
        self._passd_auth_cache = {}
        self.ssh_service = OperatorSSHService(self.storage, self.user_mgr, self._make_remote_shell)

        active_u = self.user_mgr.active_user or "operator"
        self.variables = {
            "SYS.OS": "Atlas OS",
            "SYS.VER": "2.0.0-PRO",
            "SYS.ARCH": "x86_64-subsystem",
            "SYS.USER": active_u,
            "SYS.CWD": f"/Users/{active_u}/home",
        }
        try:
            self.services = ServiceManager(
                storage=self.storage,
                job_runner=self._run_scheduled_job,
            )
        except (AttributeError, OSError, RuntimeError) as exc:
            self.service_runtime_error = str(exc)
        self.init_db()
        try:
            self.completer = AtlasCompleter(self.get_command_list(), lambda: self.variables["SYS.CWD"], self.storage)
            self.prompt_session = PromptSession(
                history=InMemoryHistory(),
                auto_suggest=AutoSuggestFromHistory(),
                complete_while_typing=True,
            )
        except Exception:
            self.completer = None
            self.prompt_session = None

    def init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        schema_file = ROOT_DIR / "db" / "init_schema.sql"
        if not DB_PATH.exists() and schema_file.exists():
            with sqlite3.connect(DB_PATH) as conn:
                conn.executescript(schema_file.read_text(encoding="utf-8"))

    def get_command_list(self):
        return [
            "help", "nano", "edit", "pico", "sys.probe", "storage.inspect", "storage.cleanup",
            "backup.create", "proc.list", "proc.top",
            "proc.start", "proc.stop", "proc.kill", "proc.info", "net.ifconfig", "net.routes",
            "net.resolve", "net.probe", "net.fetch", "net.speed", "drive.mount", "drive.ls", "drive.upload", "drive.download",
            "ssh", "ssh.server", "ssh.key.add", "ssh.key.list", "ssh.key.remove",
            "cron.add", "cron.list", "cron.remove", "cron.logs",
            "drive.status", "drive.connect", "drive.write.setup", "drive.write.unlock", "auth.login",
            "auth.whoami", "sec.firewall", "pkg.list", "pkg.avail", "pkg.install", "pkg.uninstall",
            "pkg.rollback", "fs.mount", "fs.list", "fs.vlist", "fs.copy", "fs.move", "fs.delete",
            "fs.remove", "fs.goto", "app.list", "app.launch", "app.close", "service.list",
            "service.start", "service.stop", "settings.list", "settings.set", "win.clip", "win.notify",
            "win.exec", "log.show", "log.clear", "system.health", "srv.list", "srv.start", "srv.stop",
            "srv.logs", "rel.restore", "rel.health", "dev.test", "dev.trace", "dev.build", "boot.iso",
            "srv.register", "srv.remove", "srv.restart", "time", "time.service", "games.list",
            "games.launch", "game.launch", "vyn.run", "python.run", "python.check",
            "pow", "pow.exec", "gpu.probe", "gpu.compute", "gpu.active", "gpu.ai", "device.list", "db.query", "var.set", "var.get", "cd", "ls",
            "pwd", "cat", "touch", "grep", "head", "tail", "find", "du", "stat", "file", "basename", "dirname", "realpath", "sort", "uniq", "cut", "tr", "echo", "true", "false", "which", "ll", "la", "env", "printenv", "hostname", "id", "df", "free", "mem", "uname", "uptime", "wc", "mkdir", "rm", "del",
            "user.list", "user.create", "user.delete", "user.login", "user.switch", "logout", "user.whoami",
            "user.memory", "useradd", "userdel", "login", "su", "whoami", "users", "mem.user",
            "get-process", "ps", "get-service", "get-date", "date", "test-connection", "ping",
            "get-computerinfo", "ver", "systeminfo", "ipconfig", "tree", "dir", "type", "cls",
            "clear", "exit", "quit", "script.run", "powcurl",
            # passd (Atlas OS superuser privileged execution - replaces sudo)
            "passd", "passd.setup",
            # File operations
            "cp", "copy", "mv", "move", "rmdir", "md", "rd", "rename", "ren",
            # Linux & Mac utilities
            "sw_vers", "open", "pbcopy", "pbpaste", "say", "cal", "alias", "history", "watch",
            # Windows / CMD / PowerShell utilities
            "winver", "tasklist", "taskkill", "kill", "netstat", "whoami /all",
            "restart-computer", "stop-computer", "shutdown", "reboot"
        ]

    def _make_remote_shell(self, username):
        remote_shell = copy.copy(self)
        remote_shell.variables = self.variables.copy()
        remote_shell.variables["SYS.USER"] = username
        remote_shell.variables["SYS.CWD"] = f"/Users/{username}/home"
        remote_shell._passd_auth_cache = {}
        return remote_shell

    def _validate_scheduled_command(self, command, username, allow_script=True):
        try:
            words = shlex.split(command)
        except ValueError as exc:
            return f"Invalid scheduled command syntax: {exc}"
        if not words:
            return "Scheduled command cannot be empty."
        operation = words[0].lower()
        if operation == "backup.create":
            if username != "root":
                return "Creating system restore points requires superuser privileges."
            if len(words) != 2 or not words[1].replace("-", "").replace("_", "").isalnum():
                return "backup.create requires a simple backup name."
            return None
        if operation == "storage.cleanup":
            if username != "root":
                return "Cleaning shared temporary storage requires superuser privileges."
            if len(words) > 2:
                return "storage.cleanup accepts optional age in days."
            if len(words) == 2:
                try:
                    age_days = int(words[1])
                except ValueError:
                    return "storage.cleanup age must be an integer number of days."
                if not 1 <= age_days <= 3650:
                    return "storage.cleanup age must be between 1 and 3650 days."
            return None
        if operation == "echo":
            return None
        if operation == "script.run" and allow_script:
            if len(words) != 2 or Path(words[1]).suffix.lower() != ".opsh":
                return "Scheduled scripts must be one .opsh file."
            owner_shell = self._make_remote_shell(username)
            cwd = owner_shell.variables["SYS.CWD"]
            script_path, _ = self.storage.resolve_vpath(words[1], cwd, username)
            if not script_path.is_file():
                return f"Scheduled script not found: {words[1]}"
            home_path, home_vpath = self.storage.resolve_vpath(
                f"/Users/{username}/home",
                "/",
                username,
            )
            script_vpath = self.storage.resolve_vpath(words[1], cwd, username)[1]
            if script_vpath != home_vpath and not script_vpath.startswith(home_vpath + "/"):
                return "Scheduled scripts must be stored in the owner's virtual home directory."
            try:
                script_path.resolve().relative_to(home_path.resolve())
            except ValueError:
                return "Scheduled scripts must be stored in the owner's virtual home directory."
            for line_number, line in enumerate(
                script_path.read_text(encoding="utf-8").splitlines(), 1
            ):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                error = self._validate_scheduled_command(stripped, username, allow_script=False)
                if error:
                    return f"Unsafe command on scheduled script line {line_number}: {error}"
            return None
        return (
            "Scheduled commands are restricted to backup.create, storage.cleanup, echo, "
            "or validated .opsh scripts."
        )

    def _cleanup_temporary_storage(self, age_days=7):
        if not 1 <= age_days <= 3650:
            return "[CLEANUP ERROR] Age must be between 1 and 3650 days."
        temp_root = (self.storage.get_os_root() / "tmp").resolve()
        if not temp_root.is_dir():
            return "[CLEANUP] Temporary storage is already empty."
        cutoff = time.time() - age_days * 86400
        removed_files = 0
        for path in temp_root.rglob("*"):
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed_files += 1
        for path in sorted(temp_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir() and not path.is_symlink():
                try:
                    path.rmdir()
                except OSError:
                    pass
        return f"[CLEANUP COMPLETE] Removed {removed_files} temporary file(s) older than {age_days} day(s)."

    def _run_scheduled_job(self, name, owner, command):
        if self.user_mgr.get_user(owner) is None:
            return f"[SCHEDULED JOB REJECTED] Owner Atlas account '{owner}' no longer exists."
        error = self._validate_scheduled_command(command, owner)
        if error:
            return f"[SCHEDULED JOB REJECTED] {error}"
        owner_shell = self._make_remote_shell(owner)
        return owner_shell._execute_scheduled_command(command, name)

    def _execute_scheduled_command(self, command, job_name):
        words = shlex.split(command)
        operation = words[0].lower()
        if operation == "backup.create":
            return self.reliability.create_restore_point(words[1])
        if operation == "storage.cleanup":
            age_days = int(words[1]) if len(words) > 1 else 7
            return self._cleanup_temporary_storage(age_days)
        if operation == "echo":
            return " ".join(words[1:])
        if operation == "script.run":
            script_path, _ = self.storage.resolve_vpath(
                words[1],
                self.variables["SYS.CWD"],
                self.variables["SYS.USER"],
            )
            outputs = []
            for line in script_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                error = self._validate_scheduled_command(
                    stripped,
                    self.variables["SYS.USER"],
                    allow_script=False,
                )
                if error:
                    return f"[SCHEDULED JOB REJECTED] Unsafe script command: {error}"
                outputs.append(self._execute_scheduled_command(stripped, job_name) or "")
            return "\n".join(output for output in outputs if output)
        return f"[SCHEDULED JOB ERROR] Unsupported operation for '{job_name}'."

    def close(self):
        if self.time_service is not None:
            self.time_service.close()
            self.time_service = None
        if self.services is not None:
            self.services.close()
            self.services = None
        if self.ssh_service is not None:
            self.ssh_service.stop()

    def get_prompt_text(self):
        user = self.variables.get("SYS.USER", "operator")
        vpath = self.variables.get("SYS.CWD", f"/Users/{user}/home")
        home = f"/Users/{user}/home"
        if vpath == home:
            display_path = "~"
        elif vpath.startswith(home + "/"):
            display_path = "~" + vpath[len(home):]
        else:
            display_path = vpath
        return f"\033[1;36m⚡ atlas\033[0m » \033[1;32m{user}@subsystem\033[0m [\033[1;33m{display_path}\033[0m] \033[1;35m❯\033[0m "

    def get_prompt(self):
        return self.get_prompt_text()

    def execute_script_file(self, script_path_str: str, args: list = None):
        """
        Executes external shell script files according to their file type and engine:
        - .py         -> Python
        - .sh, .bash  -> Linux / WSL
        - .ps1        -> PowerShell
        - .bat, .cmd  -> Windows CMD
        - .java       -> javac + Operator Java runtime
        - .c          -> gcc/clang native execution
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
            if ext == ".py":
                res = subprocess.run(
                    [sys.executable, abs_str, *args],
                    cwd=str(script_path.parent),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return (res.stdout + res.stderr).strip()

            elif ext in (".sh", ".bash"):
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

            elif ext == ".java":
                # Compile Java sources into the Operator-owned runtime area.
                java_out = self.storage.get_os_root() / "tmp" / "java"
                java_out.mkdir(parents=True, exist_ok=True)
                compile_res = subprocess.run(
                    ["javac", "-d", str(java_out), abs_str],
                    capture_output=True, text=True, timeout=60,
                )
                if compile_res.returncode != 0:
                    return (compile_res.stdout + compile_res.stderr).strip()
                class_name = script_path.stem
                run_res = subprocess.run(
                    ["java", "-cp", str(java_out), class_name] + args,
                    capture_output=True, text=True, timeout=60,
                )
                return (run_res.stdout + run_res.stderr).strip()

            elif ext == ".c":
                # Compile C sources into an Operator-owned temporary binary.
                c_out = self.storage.get_os_root() / "tmp" / "native"
                c_out.mkdir(parents=True, exist_ok=True)
                binary = c_out / (script_path.stem + (".exe" if os.name == "nt" else ""))
                compiler = shutil.which("gcc") or shutil.which("clang")
                if not compiler:
                    return "[C Runtime Error] gcc or clang was not found on the host."
                compile_res = subprocess.run(
                    [compiler, "-O2", abs_str, "-o", str(binary)],
                    capture_output=True, text=True, timeout=60,
                )
                if compile_res.returncode != 0:
                    return (compile_res.stdout + compile_res.stderr).strip()
                run_res = subprocess.run(
                    [str(binary)] + args,
                    capture_output=True, text=True, timeout=60,
                )
                return (run_res.stdout + run_res.stderr).strip()

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
                return f"\033[31m[Script Error]: Unsupported script file extension '{ext}'. (Supports .py, .sh, .bash, .ps1, .bat, .cmd, .java, .c, .opsh)\033[0m"

        except Exception as e:
            return f"\033[31m[Script Runtime Exception]: {str(e)}\033[0m"

    def format_help(self, topic=None):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        if topic:
            command = topic.casefold()
            aliases = {
                "free": "mem",
                "get-date": "time",
                "date": "time",
                "editor": "nano",
                "pico": "nano",
                "games": "games.list",
            }
            command = aliases.get(command, command)
            if command == "menu":
                title = Text("OPERATOR FEATURE COMMAND HELP MENU", style="bold cyan")
                c.print(Panel(title, border_style="cyan", box=ROUNDED))
                table = Table(box=ROUNDED, border_style="cyan", expand=True)
                table.add_column("Command", style="bold cyan", width=34)
                table.add_column("Usage", style="green", width=46)
                table.add_column("Feature", style="white")
                for name, (usage, description) in sorted(SPECIAL_COMMAND_HELP.items()):
                    table.add_row(name, usage, description)
                c.print(table)
                return buf.getvalue().rstrip()

            if command in SPECIAL_COMMAND_HELP:
                usage, description = SPECIAL_COMMAND_HELP[command]
                title = Text(f"COMMAND HELP: {command}", style="bold cyan")
                c.print(Panel(title, border_style="cyan", box=ROUNDED))
                c.print(f"[bold green]Usage:[/bold green] {usage}")
                c.print(f"[bold white]Feature:[/bold white] {description}")
                c.print("\nUse [bold cyan]help menu[/bold cyan] to browse all feature-specific command help.")
                return buf.getvalue().rstrip()

            related = [
                (name, details)
                for name, details in SPECIAL_COMMAND_HELP.items()
                if name.startswith(command + ".")
            ]
            if related:
                title = Text(f"COMMAND HELP: {command}", style="bold cyan")
                c.print(Panel(title, border_style="cyan", box=ROUNDED))
                table = Table(box=ROUNDED, border_style="cyan", expand=True)
                table.add_column("Command", style="bold cyan")
                table.add_column("Usage", style="green")
                table.add_column("Feature", style="white")
                for name, (usage, description) in sorted(related):
                    table.add_row(name, usage, description)
                c.print(table)
                return buf.getvalue().rstrip()
            return (
                f"[HELP] No feature-specific help is registered for '{topic}'. "
                "Use 'help menu' to browse the available command help."
            )

        title = Text("ATLAS OS SUBSYSTEM COMMAND REFERENCE (v2.0-PRO)", style="bold cyan")
        c.print(Panel(title, border_style="cyan", box=ROUNDED))
        c.print("[dim]Use 'help <command>' for command details or 'help menu' for every feature command.[/dim]")

        categories = [
            ("Core System & Diagnostics", "cyan", [
                ("time / time.service", "Local clock and background NTP sync status"),
                ("sys.probe", "Comprehensive kernel, CPU, scheduler & storage telemetry"),
                ("mem / free", "Show live physical RAM and swap usage"),
                ("gpu.probe", "Show detected GPU hardware and host driver status"),
                ("device.list [usb|display|audio]", "List present USB, display/monitor, and audio devices with Windows driver status"),
                ("system.health", "Live subsystem reliability and health check"),
                ("proc.list / proc.top", "Active process CPU, memory, and runtime monitor"),
                ("proc.start <name> <cmd>", "Spawn a managed subsystem background process"),
                ("proc.stop / proc.kill <pid>", "Terminate or signal active processes"),
            ]),
            ("Inbuilt Editor & Development", "green", [
                ("nano [file]", "Open Operator's code editor"),
                ("python.run <file.py> [args...]", "Run Python source with the host Python interpreter"),
                ("python.check <file.py>", "Compile-check Python syntax without executing the file"),
                ("app.launch <app>", "Launch a manifest-based app"),
                ("games.list", "List installed games"),
                ("games.launch <name> [args...]", "Launch an installed game using its LÖVE runtime and Windows high-performance GPU preference"),
                ("vyn.run <file.vyn>", "Run a Vyn source file with the configured Vyn interpreter"),
                ("pkg.install editor.lang.python / editor.lang.vyn", "Enable language highlighting and contextual completion in nano"),
                ("script.run <file>", "Execute a POW workflow"),
                ("powcurl <file.powcurl>", "Run a Rust/C media playback script"),
                ("dev.test / dev.trace", "Subsystem developer tools and syscall tracing"),
            ]),
            ("Atlas Security & Privileges (passd)", "bold red", [
                ("passd <command>", "Execute command with elevated superuser (root) privileges"),
                ("passd -u <user> <cmd>", "Execute command as a specific user identity"),
                ("passd.setup", "Create/change the separate passd password"),
                ("sudo (blocked)", "Informs user to use 'passd' for Atlas OS security"),
            ]),
            ("Storage & Filesystem (2GB Block DEV)", "yellow", [
                ("storage.inspect", "Inspect 2GB raw block storage device & partition mapping"),
                ("backup.create <name>", "Create a persistent system restore point"),
                ("storage.cleanup [days]", "Remove old files from temporary storage"),
                ("fs.list / dir [path]", "List virtual & host directory objects with telemetry"),
                ("fs.mount <host> <vfs>", "Mount host Windows filesystem into VFS namespace"),
                ("cp / copy [-r] <src> <dst>", "Copy files and directories inside virtual storage"),
                ("mv / move <src> <dst>", "Move or rename files and directories"),
                ("rmdir / rd <dir>", "Remove empty directory inside virtual storage"),
                ("rename / ren <src> <dst>", "Rename file or folder"),
                ("df -h", "Filesystem disk space usage and mount point status"),
                ("cd <dir> / pwd", "Navigate and display virtual current working directory"),
                ("mkdir / md <dir>", "Create directory inside 2GB storage partition"),
                ("rm / del <path>", "Delete file or wildcard path inside 2GB storage"),
                ("tree [path]", "Display visual directory tree of user hierarchy"),
            ]),
            ("Multi-User & Memory Management", "bright_yellow", [
                ("user.list / users", "Enumerate users, dedicated RAM & quota status"),
                ("passd user.create <u...>", "Create user, setup hierarchy & allocate memory (passd)"),
                ("passd user.delete <name>", "Delete user, purge files & reclaim memory pool (passd)"),
                ("user.login <name> <pass>", "Authenticate and switch active user session"),
                ("user.switch / su <name>", "Switch active user session context"),
                ("logout", "Switch back to the default operator account and home"),
                ("user.whoami / whoami", "Show current active user and session role"),
                ("user.memory / mem.user [name]", "Telemetry on dedicated memory pool & virtual pages"),
            ]),
            ("Networking & Connectivity", "magenta", [
                ("net.ifconfig", "Display network interfaces (lo0, op_eth0, virtio_net)"),
                ("net.routes", "Display kernel routing table and gateways"),
                ("net.resolve <host>", "Query host DNS resolution"),
                ("net.probe <host> [port]", "Measure TCP port latency and ping host"),
                ("net.fetch <url>", "HTTP socket fetcher and previewer"),
                ("net.speed", "Live download/upload speed test; press Ctrl+C to stop"),
                ("ssh <user@host> [command]", "Connect with the host OpenSSH client"),
                ("ssh.server start|status|stop", "Manage the key-authenticated Atlas-only SSH server"),
                ("ssh.key.add <user> <public-key-file>", "Authorize an Ed25519 key for an Atlas account"),
                ("ssh.key.list [user]", "List fingerprints of authorized Atlas SSH keys"),
                ("ssh.key.remove <user> <fingerprint>", "Revoke an authorized Atlas SSH key"),
                ("drive.mount / drive.status", "Connect and inspect your per-user Google Drive mount"),
                ("drive.ls [remote-path]", "List files in the mounted Google Drive account"),
                ("drive.download <file-id-or-path>", "Download a Drive file into the current user's Drive folder"),
                ("drive.upload <path>", "Upload a local Drive mount file after unlocking writes"),
                ("drive.write.setup / drive.write.unlock", "Protect automatic uploads with a local passphrase"),
                ("netstat", "Display active network connections and listening ports"),
                ("ping / test-connection", "Host ping diagnostics"),
            ]),
            ("Scheduled Jobs & Services", "bright_magenta", [
                ("cron.add <name> <seconds> <command...>", "Schedule backups, temp cleanup, or a safe .opsh script"),
                ("cron.list / cron.remove <name>", "List or remove persistent scheduled jobs"),
                ("cron.logs <name> [count]", "Read persistent scheduled-job output"),
                ("srv.register <name> --restart <policy> --health <check> -- <exe> [args...]", "Register a native managed process"),
                ("srv.start / srv.stop / srv.restart <name>", "Supervise or stop a real native process"),
                ("srv.list / srv.logs <name> [count]", "Inspect process health, PID, restart count, and persistent logs"),
            ]),
            ("Linux / POSIX Utilities", "bright_cyan", [
                ("ls / ll / la", "POSIX directory listing with flags (-l, -a, -lh)"),
                ("cat / type <file>", "Display file content"),
                ("touch <file>", "Create empty file or touch timestamp"),
                ("grep <pattern> <file>", "Search text with regex syntax highlighting"),
                ("head / tail [-n count] <file>", "Output first or last lines of file"),
                ("sort / uniq / cut / tr", "Text stream filtering and column manipulation"),
                ("find <path> -name <glob>", "Search for files recursively"),
                ("stat / file / du <path>", "File metadata, type identification, and disk usage"),
                ("cal [month] [year]", "Display full terminal calendar"),
                ("history / alias", "List past command history and registered shell aliases"),
                ("watch [-n sec] <cmd>", "Run command repeatedly and display periodic output"),
                ("mem / free [-h]", "Show live host RAM and swap usage"),
                ("uname [-a]", "Show kernel architecture and release"),
                ("uptime / wc <file>", "Subsystem uptime and word/byte counter"),
            ]),
            ("macOS Subsystem Bridges", "bright_blue", [
                ("sw_vers", "Print macOS subsystem bridge product and build version"),
                ("open <file|url>", "Open file, document, or web URL"),
                ("pbcopy / pbpaste", "Mac clipboard copy and paste utilities"),
                ("say <text>", "Terminal speech synthesizer output"),
            ]),
            ("Windows & Subsystem Integration", "bright_white", [
                ("winver", "Display Windows subsystem OS build and workstation edition"),
                ("tasklist / ps", "List running processes and memory consumption"),
                ("passd taskkill / kill <pid>", "Terminate process by PID (requires passd)"),
                ("win.clip [text]", "Read from or write to Windows host clipboard"),
                ("win.notify <title> <msg>", "Dispatch native Windows toast notification"),
                ("win.exec <app>", "Launch native Windows host applications (calc, notepad)"),
                ("passd shutdown / reboot", "Subsystem power state transitions (requires passd)"),
                ("cls / clear", "Clear console screen buffer"),
                ("exit / quit", "Safely shutdown Atlas OS subsystem session"),
            ]),
        ]

        for cat_name, color, cmds in categories:
            t = Table(box=ROUNDED, border_style=color, show_header=True, header_style=f"bold {color}", expand=True)
            t.add_column(f"Command ({cat_name})", style="bold white", width=34)
            t.add_column("Description", style="dim white")
            for cmd_name, desc in cmds:
                t.add_row(f"[{color}]{cmd_name}[/{color}]", desc)
            c.print(t)

        return buf.getvalue().rstrip()

    def run_network_speed_test(self):
        native_speed_binary = ROOT_DIR / "bin" / "net_speed.exe"
        if native_speed_binary.exists():
            try:
                subprocess.run([str(native_speed_binary)], check=False)
                return "[C++ SPEED TEST] Native Atlas net-speed monitor exited."
            except KeyboardInterrupt:
                return "[SPEED TEST STOPPED] Native speed monitor interrupted by Ctrl+C."

        tester = NetworkSpeedTester(self.network)
        totals = {
            "download": {"bytes": 0, "seconds": 0.0, "latest": None},
            "upload": {"bytes": 0, "seconds": 0.0, "latest": None},
        }
        errors = {}
        samples = 0
        started = time.monotonic()

        def average_mbps(direction):
            total = totals[direction]
            if not total["seconds"]:
                return "N/A"
            return f"{total['bytes'] * 8 / total['seconds'] / 1_000_000:.2f} Mbps"

        def render(status):
            table = Table(box=ROUNDED, border_style="cyan", expand=True)
            table.add_column("Direction", style="bold cyan")
            table.add_column("Current", style="bold green")
            table.add_column("Average", style="bold yellow")
            table.add_column("Sample")
            for direction, title in (("download", "Download"), ("upload", "Upload")):
                latest = totals[direction]["latest"]
                current = f"{latest['mbps']:.2f} Mbps" if latest else "-"
                size = f"{latest['bytes'] / 1_000_000:.2f} MB" if latest else "-"
                table.add_row(title, current, average_mbps(direction), size)
            detail = status
            if errors:
                detail += " | " + " | ".join(
                    f"{direction.title()} error: {message}"
                    for direction, message in errors.items()
                )
            return Panel(
                table,
                title="OPERATOR NETWORK SPEED TEST",
                subtitle=f"{detail} | Samples: {samples} | Ctrl+C to stop",
                border_style="bright_blue",
            )

        try:
            with Live(
                render("Connecting to Cloudflare speed-test service..."),
                console=Console(),
                refresh_per_second=4,
                transient=True,
            ) as live:
                while True:
                    live.update(render("Measuring"))
                    successful_directions = 0
                    for direction, measure in (
                        ("download", tester.measure_download),
                        ("upload", tester.measure_upload),
                    ):
                        try:
                            measurement = measure()
                        except Exception as exc:
                            errors[direction] = str(exc)
                            continue
                        totals[direction]["bytes"] += measurement["bytes"]
                        totals[direction]["seconds"] += measurement["seconds"]
                        totals[direction]["latest"] = measurement
                        errors.pop(direction, None)
                        successful_directions += 1
                    if successful_directions:
                        samples += 1
                    live.update(render("Running"))
                    time.sleep(1)
        except KeyboardInterrupt:
            elapsed = time.monotonic() - started
            return (
                f"[SPEED TEST STOPPED] Duration: {elapsed:.1f}s | "
                f"Download average: {average_mbps('download')} | "
                f"Upload average: {average_mbps('upload')} | "
                f"Completed samples: {samples}"
            )

    def format_sys_probe(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        storage_info = self.storage.get_disk_info()
        gpu_status = self.gpu.probe_compute()
        gpu_devices = gpu_status["devices"]
        t = Table(title="⚡ ATLAS OS SUBSYSTEM PROFILE ⚡", box=ROUNDED, border_style="cyan", expand=True)
        t.add_column("Subsystem Component", style="bold cyan", width=26)
        t.add_column("Configuration & Status", style="white")

        t.add_row("Operating System", "Atlas OS Subsystem [v2.0.0-PRO]")
        t.add_row("Kernel Core", "[green]C Microkernel[/green] (Round-Robin Preemptive Scheduler, VFS, IPC)")
        t.add_row("Hardware Safety Guard", "[green]Rust Guard[/green] (Memory Page Protection & Fault Supervisor)")
        t.add_row("Inbuilt Text Editor", "[bold yellow]Operator Code Editor[/bold yellow] [Active, syntax highlighting]")
        t.add_row("Dedicated Storage Device", f"[bold white]{storage_info['device']}[/bold white] ({storage_info['capacity_gb']} GB Virtual Block Device)")
        t.add_row("Storage Filesystem", f"{storage_info['filesystem']} [{storage_info['status']}]")
        t.add_row("Network Subsystem", "VirtIO-Net + OP-Eth0 (Full TCP/IP Stack Active)")
        t.add_row("Application Runtime", "Java OVM Sandbox, Python Polyglot Interpreter, C++ WM Compositor")
        t.add_row("Host Script Bridges", "Direct Bridges for .sh, .bash, .ps1, .bat, .cmd, .opsh")
        t.add_row("Active User & Shell", f"{self.variables.get('SYS.USER', 'operator')} (Role: root/admin) | AtlasSH")
        if gpu_devices:
            gpu_summary = "; ".join(
                f"{device['name']} ({'driver active' if device.get('driver_loaded') else 'driver unavailable'})"
                for device in gpu_devices
            )
        else:
            gpu_summary = "No graphics device detected"
        t.add_row("Host Graphics Device", gpu_summary)
        try:
            memory = self.mem_mgr.get_host_memory_summary()
            total_gb = memory["total_bytes"] / (1024 ** 3)
            available_gb = memory["available_bytes"] / (1024 ** 3)
            t.add_row("Host Physical RAM", f"{total_gb:.2f} GB total, {available_gb:.2f} GB available")
        except (OSError, UnicodeError) as exc:
            t.add_row("Host Physical RAM", f"Telemetry unavailable: {exc}")
        c.print(t)
        return buf.getvalue().rstrip()

    def format_storage_inspect(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        info = self.storage.get_disk_info()
        used_mb = round(info['used_bytes'] / (1024 * 1024), 2)
        free_mb = round(info['free_bytes'] / (1024 * 1024), 2)
        pct = round((info['used_bytes'] / info['capacity_bytes']) * 100, 1)

        t = Table(title="💾 INBUILT 2GB BLOCK STORAGE DIAGNOSTICS 💾", box=ROUNDED, border_style="yellow", expand=True)
        t.add_column("Metric", style="bold yellow", width=25)
        t.add_column("Value", style="white")

        t.add_row("Device Node", str(info['device']))
        t.add_row("Total Capacity", f"{info['capacity_bytes']:,} Bytes ({info['capacity_gb']} GB)")
        t.add_row("Used Overhead", f"{info['used_bytes']:,} Bytes ({used_mb} MB) [{pct}%]")
        t.add_row("Available Space", f"{info['free_bytes']:,} Bytes ({free_mb} MB)")
        t.add_row("Filesystem Type", str(info['filesystem']))
        t.add_row("Sector / Block Size", f"{info['sector_size']} Bytes / {info['block_size']} Bytes")
        t.add_row("Mount Status", f"[green]{info['status']}[/green]")
        t.add_row("Backing Virtual Image", str(self.storage.img_path.name))

        bar_len = 40
        filled = int(bar_len * (pct / 100))
        bar = "█" * filled + "░" * (bar_len - filled)
        t.add_row("Storage Allocation Bar", f"[green]{bar}[/green] {pct}%")

        c.print(t)
        return buf.getvalue().rstrip()

    def format_ifconfig(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        ifaces = self.network.ifconfig()
        t = Table(title="🌐 NETWORK ADAPTER INTERFACES 🌐", box=ROUNDED, border_style="magenta", expand=True)
        t.add_column("Interface", style="bold magenta", width=14)
        t.add_column("State", style="bold green", width=10)
        t.add_column("IP Address", style="white", width=18)
        t.add_column("Netmask", style="dim white", width=18)
        t.add_column("MAC Address", style="cyan")

        for iface in ifaces:
            st = "[green]ONLINE[/green]" if iface['state'].upper() == "UP" else "[red]DOWN[/red]"
            t.add_row(iface['name'], st, iface['ip'], iface['mask'], iface['mac'])
        c.print(t)
        return buf.getvalue().rstrip()

    def format_proc_top(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        procs = self.proc_mgr.get_top()
        t = Table(title="⚙️ ACTIVE SUBSYSTEM PROCESS TABLE ⚙️", box=ROUNDED, border_style="cyan", expand=True)
        t.add_column("PID", style="bold cyan", width=7)
        t.add_column("User", style="yellow", width=12)
        t.add_column("State", style="bold green", width=10)
        t.add_column("Priority", style="dim white", width=9)
        t.add_column("CPU Time", style="white", width=12)
        t.add_column("Uptime", style="dim white", width=10)
        t.add_column("Command", style="bold white")

        for p in procs:
            t.add_row(str(p['pid']), p['user'], p['state'], str(p['priority']), p['cpu_time'], p['uptime'], p['cmd'])
        c.print(t)
        return buf.getvalue().rstrip()

    def format_pkg_list(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        pkgs = self.pkg_mgr.list_installed()
        t = Table(title="📦 INSTALLED ATLAS OS PACKAGES 📦", box=ROUNDED, border_style="blue", expand=True)
        t.add_column("Package ID", style="bold blue", width=16)
        t.add_column("Name", style="white", width=26)
        t.add_column("Version", style="bold yellow", width=10)
        t.add_column("Runtime", style="cyan", width=10)
        t.add_column("Status", style="bold green", width=10)
        t.add_column("Description", style="dim white")

        for p in pkgs:
            st = "[green]ACTIVE[/green]" if p.get('status', 'active') == 'active' else "[red]OFFLINE[/red]"
            t.add_row(p['id'], p['name'], p['version'], p['runtime'], st, p.get('desc', ''))
        c.print(t)
        return buf.getvalue().rstrip()

    def format_df(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        storage_info = self.storage.get_disk_info()
        total_k = storage_info['capacity_bytes'] // 1024
        used_k = storage_info['used_bytes'] // 1024
        free_k = storage_info['free_bytes'] // 1024
        pct = round((storage_info['used_bytes'] / storage_info['capacity_bytes']) * 100, 1)

        t = Table(title="💽 FILESYSTEM DISK USAGE (df) 💽", box=ROUNDED, border_style="cyan", expand=True)
        t.add_column("Filesystem", style="bold cyan", width=26)
        t.add_column("1K-Blocks", style="white", width=14)
        t.add_column("Used", style="yellow", width=12)
        t.add_column("Available", style="green", width=14)
        t.add_column("Use%", style="bold yellow", width=8)
        t.add_column("Mounted on", style="bold white")

        t.add_row("/dev/nvme0n1_operator", f"{total_k:,}", f"{used_k:,}", f"{free_k:,}", f"{pct}%", "/")
        t.add_row("opfs_vfs", "1,048,576", "32,768", "1,015,808", "3.1%", "/mnt/vfs")
        t.add_row("host_bridge", "33,554,432", "8,388,608", "25,165,824", "25.0%", "/mnt/host")
        c.print(t)
        return buf.getvalue().rstrip()

    def format_free(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        try:
            memory = self.mem_mgr.get_host_memory_summary()
        except OSError as exc:
            return f"\033[31m[RAM ERROR] Unable to read host memory details: {exc}\033[0m"

        to_kb = lambda value: "N/A" if value is None else f"{value // 1024:,}"
        t = Table(title="🧠 MEMORY & SWAP TELEMETRY (free) 🧠", box=ROUNDED, border_style="green", expand=True)
        t.add_column("Type", style="bold green", width=10)
        t.add_column("Total (KB)", style="white", width=14)
        t.add_column("Used (KB)", style="yellow", width=14)
        t.add_column("Free (KB)", style="green", width=14)
        t.add_column("Shared (KB)", style="dim white", width=14)
        t.add_column("Available (KB)", style="bold cyan")

        t.add_row(
            "Mem",
            to_kb(memory["total_bytes"]),
            to_kb(memory["used_bytes"]),
            to_kb(memory["free_bytes"]),
            "-",
            to_kb(memory["available_bytes"]),
        )
        t.add_row(
            "Swap",
            to_kb(memory["swap_total_bytes"]),
            to_kb(memory["swap_used_bytes"]),
            to_kb(memory["swap_free_bytes"]),
            "-",
            to_kb(memory["swap_free_bytes"]),
        )
        c.print(t)
        output = buf.getvalue().rstrip()
        if memory.get("swap_error"):
            output += f"\n\033[33m[SWAP WARNING] {memory['swap_error']}\033[0m"
        return output

    def format_user_list(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        users = self.user_mgr.list_users()
        t = Table(title="👥 ATLAS OS USER REGISTRY & MEMORY ALLOCATION 👥", box=ROUNDED, border_style="cyan", expand=True)
        t.add_column("UID", style="bold cyan", width=6)
        t.add_column("Username", style="bold white", width=14)
        t.add_column("Role", style="yellow", width=8)
        t.add_column("Home Directory", style="dim white", width=24)
        t.add_column("Dedicated RAM", style="bold green", width=15)
        t.add_column("Used RAM", style="white", width=10)
        t.add_column("Disk Quota", style="cyan", width=12)
        t.add_column("Session", style="bold magenta")

        for u in users:
            session_badge = "[bold green]● ACTIVE[/bold green]" if u["is_active"] else "[dim]idle[/dim]"
            t.add_row(
                str(u["uid"]),
                u["username"],
                u["role"],
                u["home_dir"],
                f"{u['memory_mb']:,} MB",
                f"{u['used_mb']} MB",
                f"{u['quota_mb']} MB",
                session_badge
            )
        c.print(t)
        return buf.getvalue().rstrip()

    def format_user_memory(self, username: Optional[str] = None):
        target_u = username or self.variables.get("SYS.USER", "operator")
        mem = self.mem_mgr.get_user_memory(target_u)
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        t = Table(title=f"🧠 VIRTUAL MEMORY TELEMETRY: {target_u.upper()} 🧠", box=ROUNDED, border_style="green", expand=True)
        t.add_column("Metric", style="bold green", width=26)
        t.add_column("Value", style="white")

        t.add_row("User Identifier", target_u)
        t.add_row("Dedicated Memory Pool", f"{mem['allocated_mb']:,} MB ({mem['allocated_mb'] * 1024:,} KB)")
        t.add_row("Active Resident Usage", f"{mem['used_mb']:,} MB ({mem['usage_pct']}%)")
        t.add_row("Available Headroom", f"{mem['free_mb']:,} MB")
        t.add_row("Allocated Virtual Pages", f"{mem['virtual_pages']:,} pages (Page size: {mem['page_size_kb']} KB)")
        t.add_row("Memory Controller Status", f"[green]{mem['status']}[/green]")

        bar_len = 40
        filled = int(bar_len * (mem['usage_pct'] / 100))
        bar = "█" * filled + "░" * (bar_len - filled)
        t.add_row("User Memory Gauge", f"[green]{bar}[/green] {mem['usage_pct']}%")

        c.print(t)
        return buf.getvalue().rstrip()

    def format_gpu_probe(self):
        buf = io.StringIO()
        c = Console(file=buf, force_terminal=True, width=95)
        status = self.gpu.probe_compute()
        devices = status.get("devices", [])
        if not devices:
            details = "\n".join(status.get("errors", []))
            message = "\033[33m[GPU PROBE]\033[0m No graphics device was detected."
            return f"{message}\n{details}" if details else message

        for idx, d in enumerate(devices, 1):
            t = Table(
                title=f"🎮 HARDWARE GPU INTROSPECTION (GPU #{idx}) 🎮",
                box=ROUNDED,
                border_style="bright_magenta",
                expand=True
            )
            t.add_column("Specification Property", style="bold cyan", width=28)
            t.add_column("Hardware Telemetry Value", style="white")

            t.add_row("GPU Model Name", f"[bold white]{d.get('name', 'Unknown')}[/bold white]")
            t.add_row("GPU Hardware Vendor", f"[bold yellow]{d.get('vendor', 'Unknown')}[/bold yellow]")
            t.add_row("Graphics Processor (Chip)", str(d.get("chip", "Unknown")))

            # Memory specs
            ded_ram = d.get("memory_dedicated_mb", 0)
            avail_ram = d.get("memory_available_mb", 0)
            if isinstance(ded_ram, (int, float)) and ded_ram > 0:
                ded_str = f"{ded_ram:,} MB ({round(ded_ram / 1024, 2)} GB)"
            else:
                ded_str = str(ded_ram)
            if isinstance(avail_ram, (int, float)) and avail_ram > 0:
                avail_str = f"{avail_ram:,} MB ({round(avail_ram / 1024, 2)} GB)"
            else:
                avail_str = str(avail_ram)

            t.add_row("Dedicated Video RAM (VRAM)", ded_str)
            t.add_row("Reported GPU Memory", avail_str)
            t.add_row("GPU Memory In Use", str(d.get("memory_used_mb", "Unknown")))
            t.add_row("GPU Memory Available", str(d.get("memory_free_mb", "Unknown")))
            t.add_row("GPU Utilization", str(d.get("utilization_pct", "Unknown")))
            t.add_row("Display Driver Version", str(d.get("driver", "Unknown")))
            driver_style = "green" if d.get("driver_loaded") else "red"
            t.add_row("Host GPU Driver Health", f"[{driver_style}]{d.get('driver_status', 'Unknown')}[/{driver_style}]")
            t.add_row("Current Video Resolution", str(d.get("display_mode", "Unknown")))
            t.add_row("Active Refresh Rate", f"[bold green]{d.get('refresh_rate', 'Unknown')}[/bold green]")
            t.add_row("Hardware Compute Units", str(d.get("compute_units", "N/A")))
            t.add_row("Engine Peak Clock Speed", str(d.get("clock", "N/A")))
            t.add_row("PCI Hardware Device ID", str(d.get("device_id", "N/A")))
            t.add_row("Driver & Hardware Status", f"[bold green]{d.get('status', 'OK')}[/bold green]")
            t.add_row("Compute Subsystem Bridge", f"[cyan]{d.get('backend', 'DirectX')}[/cyan]")

            c.print(t)

        return buf.getvalue().rstrip()

    def _set_passd_password_interactively(self, username):
        import getpass

        if not sys.stdin.isatty():
            return "passd password setup requires an interactive terminal."
        for _ in range(3):
            password = getpass.getpass("[passd] Set a new passd password (8+ characters): ")
            confirmation = getpass.getpass("[passd] Confirm new passd password: ")
            if password != confirmation:
                print("passd passwords did not match; try again.")
                continue
            try:
                self.user_mgr.set_passd_password(username, password)
            except ValueError as exc:
                print(str(exc))
                continue
            return None
        return "passd password setup cancelled after three unsuccessful attempts."

    def _authenticate_passd(self, username):
        import getpass

        if not sys.stdin.isatty():
            return False
        for attempt in range(3):
            password = getpass.getpass(f"[passd] password for {username}: ")
            if self.user_mgr.verify_passd_password(username, password):
                self._passd_auth_cache = {
                    "user": username,
                    "timestamp": time.time(),
                }
                return True
            if attempt < 2:
                print("Incorrect passd password.")
        return False

    def _ensure_runtime_state(self):
        if not hasattr(self, "variables") or self.variables is None:
            active_user = getattr(self, "active_user", "operator")
            self.variables = {
                "SYS.OS": "Atlas OS",
                "SYS.VER": "2.0.0-PRO",
                "SYS.ARCH": "x86_64-subsystem",
                "SYS.USER": active_user,
                "SYS.CWD": f"/Users/{active_user}/home",
            }
        else:
            self.variables.setdefault("SYS.OS", "Atlas OS")
            self.variables.setdefault("SYS.VER", "2.0.0-PRO")
            self.variables.setdefault("SYS.ARCH", "x86_64-subsystem")
            self.variables.setdefault("SYS.USER", getattr(self, "active_user", "operator"))
            self.variables.setdefault("SYS.CWD", f"/Users/{self.variables['SYS.USER']}/home")

    def eval_command(self, raw_line: str):
        self._ensure_runtime_state()
        try:
            commands = _split_shell_commands(raw_line)
        except ValueError as exc:
            return f"\033[31m[SYNTAX ERROR] {exc}\033[0m"
        if not commands:
            return None
        if len(commands) > 1:
            outputs = []
            for command in commands:
                output = self.eval_command(command)
                if output:
                    outputs.append(str(output))
            return "\n".join(outputs) or None

        line = commands[0]
        if line.startswith("#"):
            return None

        # Interpolate variables: @(VAR) or $(VAR)
        for k, v in self.variables.items():
            line = line.replace(f"@({k})", str(v)).replace(f"${k}", str(v))

        try:
            tokens = _parse_shell_words(line)
        except ValueError as exc:
            return f"\033[31m[SYNTAX ERROR] {exc}\033[0m"
        if not tokens:
            return None
        cmd = tokens[0].lower()
        args = tokens[1:]

        # Sudo alias enforcement: In Atlas OS, use 'passd' instead of 'sudo'
        if cmd == "sudo":
            return (
                "\033[1;33m[Atlas OS Security]: 'sudo' is not used in Atlas OS.\033[0m\n"
                "In Atlas OS, use \033[1;32mpassd <command>\033[0m for privileged execution.\n"
                "Example: \033[1;36mpassd user.create <user> <pass>\033[0m or \033[1;36mpassd sec.firewall\033[0m"
            )

        # passd (Privileged Execution Layer - replaces sudo in Atlas OS)
        if cmd in ("passd", "passd.setup"):
            setup_only = cmd == "passd.setup"
            if setup_only and args:
                return "Usage: passd.setup"
            if not setup_only and args and args[0].lower() == "setup":
                setup_only = True
                args = args[1:]
                if args:
                    return "Usage: passd setup"

            if not args and not setup_only:
                return (
                    "\033[1;36mUsage: passd [-u <user>] <command> [args...]\033[0m\n"
                    "Execute a command with elevated superuser (root) privileges in Atlas OS.\n"
                    "Run passd.setup to create or change your separate passd password.\n"
                    "Examples:\n"
                    "  passd user.create dev secret123\n"
                    "  passd user.delete olduser\n"
                    "  passd sec.firewall\n"
                    "  passd srv.start redis\n"
                    "  passd -u operator whoami"
                )

            target_user = "root"
            sub_args = list(args)
            if not setup_only and len(sub_args) >= 3 and sub_args[0] == "-u":
                target_user = sub_args[1]
                sub_args = sub_args[2:]

            cur_user = self.variables.get("SYS.USER", "operator")
            if setup_only:
                if self.user_mgr.has_passd_password(cur_user):
                    if not self._authenticate_passd(cur_user):
                        return (
                            "\033[31m[PASSD AUTH ERROR]\033[0m "
                            "Password setup requires the current passd password."
                        )
                setup_error = self._set_passd_password_interactively(cur_user)
                if setup_error:
                    return f"\033[31m[PASSD SETUP ERROR]\033[0m {setup_error}"
                self._passd_auth_cache = {"user": cur_user, "timestamp": time.time()}
                return f"passd password set for '{cur_user}'."

            now = time.time()
            cached_ok = (
                self._passd_auth_cache.get("user") == cur_user
                and now - self._passd_auth_cache.get("timestamp", 0) < 300
            )

            if cur_user != "root":
                if not self.user_mgr.has_passd_password(cur_user):
                    setup_error = self._set_passd_password_interactively(cur_user)
                    if setup_error:
                        return (
                            "\033[31m[PASSD SETUP REQUIRED]\033[0m "
                            f"{setup_error} Run passd.setup from an interactive shell."
                        )
                    self._passd_auth_cache = {"user": cur_user, "timestamp": time.time()}
                    print("passd password created. Continuing with the requested privileged command.")
                elif not cached_ok and not self._authenticate_passd(cur_user):
                    return (
                        "\033[31m[PASSD AUTH ERROR]\033[0m "
                        "Three incorrect passd passwords; command was not run."
                    )

            sub_cmd_line = " ".join(shlex.quote(a) for a in sub_args)
            orig_user = self.variables.get("SYS.USER", "operator")
            self.variables["SYS.USER"] = target_user
            self.variables["SYS.PASSD_ACTIVE"] = "true"
            try:
                return self.eval_command(sub_cmd_line)
            finally:
                self.variables["SYS.USER"] = orig_user
                self.variables.pop("SYS.PASSD_ACTIVE", None)

        # Familiar POSIX aliases
        if cmd == "ll":
            cmd, args = "ls", ["-l", *args]
        elif cmd == "la":
            cmd, args = "ls", ["-a", *args]

        if cmd in ("gui", "browser", "web"):
            return "[SUBSYSTEM] GUI and browser components have been removed from Operator OS."

        if cmd in ("pow", "pow.exec"):
            if not args:
                return "Usage: pow <workflow.pow>"
            try:
                return self.pow.execute_file(args[0])
            except Exception as exc:
                return f"\033[31m[POW ERROR] {exc}\033[0m"

        if cmd == "powcurl":
            if len(args) != 1:
                return "Usage: powcurl <script.powcurl>"
            if not args[0].lower().endswith(".powcurl"):
                return "\033[31m[POWCURL ERROR]\033[0m Scripts must use the .powcurl extension."

            current_user = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{current_user}/home")
            script_path, _ = self.storage.resolve_vpath(args[0], cwd, current_user)
            executable = ROOT_DIR / "bin" / "powcurl.exe"
            if not executable.is_file():
                return (
                    "\033[31m[POWCURL ERROR]\033[0m Runtime not built. "
                    "Build it with `python build.py --release`."
                )
            if not script_path.is_file():
                return f"\033[31m[POWCURL ERROR]\033[0m Script not found: {args[0]}"
            try:
                result = subprocess.run(
                    [str(executable), str(script_path)],
                    cwd=str(script_path.parent),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                return f"\033[31m[POWCURL ERROR]\033[0m Could not launch runtime: {exc}"
            output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
            if result.returncode:
                return f"\033[31m[POWCURL ERROR]\033[0m {output or f'Runtime exited with code {result.returncode}'}"
            return output or None

        if cmd == "gpu.probe":
            return self.format_gpu_probe()

        if cmd == "device.list":
            if len(args) > 1:
                return "Usage: device.list [usb|display|audio]"
            category = args[0].casefold() if args else None
            if category not in (None, "usb", "display", "audio"):
                return "Device category must be usb, display, or audio."
            try:
                devices = self.device_manager.list_devices(category)
            except RuntimeError as exc:
                return f"[DEVICE ERROR] {exc}"
            if not devices:
                return f"No present {category or 'supported'} devices were found."
            buf = io.StringIO()
            console = Console(file=buf, force_terminal=True, width=120)
            table = Table(
                title="HOST DEVICES VISIBLE TO OPERATOR",
                box=ROUNDED,
                border_style="cyan",
                expand=True,
            )
            table.add_column("Type", style="bold cyan")
            table.add_column("Device")
            table.add_column("Status", style="green")
            table.add_column("Host driver", style="yellow")
            table.add_column("Hardware ID", overflow="fold")
            for device in devices:
                table.add_row(
                    device["category"],
                    device["name"],
                    device["status"],
                    " ".join(
                        value for value in (
                            device["driver_provider"],
                            device["driver_version"],
                        ) if value != "Unknown"
                    ) or "Unknown",
                    device["instance_id"],
                )
            console.print(table)
            console.print(
                "[dim]Devices are controlled by Windows host drivers; this subsystem "
                "does not install or replace kernel drivers. Connector/cable presence "
                "depends on hardware and may not be exposed.[/dim]"
            )
            return buf.getvalue().rstrip()

        if cmd == "gpu.compute":
            result = self.gpu.probe_compute()
            return f"GPU driver: {'active' if result['live'] else 'unavailable'} ({result['backend']})"

        if cmd == "gpu.active":
            return "true" if self.gpu.probe_compute()["live"] else "false"

        if cmd == "gpu.ai":
            return f"AI acceleration backend: {self.gpu.select_backend()}"

        # Check script invocation shorthand (e.g. ./demo.sh or demo.bat)
        if cmd.startswith("./") or cmd.endswith((".pow", ".py", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".java", ".c", ".opsh")):
            script = cmd.lstrip("./")
            return self.execute_script_file(script, args)

        # Inbuilt code editor
        if cmd in ("nano", "edit", "pico"):
            cur_u = self.variables.get("SYS.USER", "operator")
            target_f = args[0] if args else None

            if target_f:
                phys_path, _ = self.storage.resolve_vpath(target_f, self.variables["SYS.CWD"], cur_u)
                phys_cwd = str(phys_path.parent)
                target_str = str(phys_path)
            else:
                phys_cwd_path, _ = self.storage.resolve_vpath(self.variables["SYS.CWD"], "/", cur_u)
                phys_cwd = str(phys_cwd_path)
                target_str = None

            try:
                editor = OperatorCodeEditor(target_str, working_dir=phys_cwd)
                editor.run()
                return None
            except Exception as e:
                return f"\033[31m[Nano Editor Exception]: {e}\033[0m"

        # Distinct Custom Operator Command Vocabulary
        if cmd == "help":
            return self.format_help(" ".join(args) if args else None)

        elif cmd == "sys.probe":
            return self.format_sys_probe()

        elif cmd == "storage.inspect":
            return self.format_storage_inspect()

        elif cmd == "backup.create":
            if len(args) != 1:
                return "Usage: backup.create <name>"
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Creating system restore points requires superuser privileges. Use passd."
            if not args[0].replace("-", "").replace("_", "").isalnum():
                return "Backup name may contain only letters, numbers, '-' and '_'."
            return self.reliability.create_restore_point(args[0])

        elif cmd == "storage.cleanup":
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Cleaning shared temporary storage requires superuser privileges. Use passd."
            if len(args) > 1:
                return "Usage: storage.cleanup [older-than-days]"
            try:
                age_days = int(args[0]) if args else 7
            except ValueError:
                return "storage.cleanup age must be an integer number of days."
            return self._cleanup_temporary_storage(age_days)

        elif cmd == "ssh":
            if not args:
                return "Usage: ssh <user@host> [OpenSSH options] [remote-command]"
            ssh_executable = shutil.which("ssh")
            if not ssh_executable:
                return "[SSH ERROR] OpenSSH client was not found on the host."
            try:
                result = subprocess.run([ssh_executable, *args], check=False)
            except OSError as exc:
                return f"[SSH ERROR] Could not start OpenSSH client: {exc}"
            if result.returncode:
                return f"[SSH exited with code {result.returncode}]"
            return None

        elif cmd == "ssh.server":
            if not args:
                return "Usage: ssh.server start [--host <IPv4>] [--port <port>] | status | stop"
            action = args[0].lower()
            if action == "status" and len(args) == 1:
                return self.ssh_service.status()
            if action == "stop" and len(args) == 1:
                return self.ssh_service.stop()
            if action != "start":
                return "Usage: ssh.server start [--host <IPv4>] [--port <port>] | status | stop"
            host = "127.0.0.1"
            port = 2222
            index = 1
            try:
                while index < len(args):
                    option = args[index]
                    if option == "--host" and index + 1 < len(args):
                        host = args[index + 1]
                        index += 2
                    elif option == "--port" and index + 1 < len(args):
                        port = int(args[index + 1])
                        index += 2
                    else:
                        raise ValueError(f"Unknown or incomplete option: {option}")
                return self.ssh_service.start(host=host, port=port)
            except (OSError, ValueError) as exc:
                return f"[SSH SERVER ERROR] {exc}"

        elif cmd in ("ssh.key.add", "ssh.key.list", "ssh.key.remove"):
            current_user = self.variables.get("SYS.USER", "operator")
            target_user = args[0].lower() if args else current_user
            if target_user != current_user and current_user != "root":
                return "[PERMISSION DENIED] Only passd/root may manage another user's SSH keys."
            if cmd == "ssh.key.list":
                if len(args) > 1:
                    return "Usage: ssh.key.list [user]"
                try:
                    fingerprints = self.ssh_service.list_authorized_keys(target_user)
                except (OSError, ValueError) as exc:
                    return f"[SSH KEY ERROR] {exc}"
                return "\n".join(fingerprints) if fingerprints else f"No SSH keys enrolled for '{target_user}'."
            if cmd == "ssh.key.add":
                if len(args) != 2:
                    return "Usage: ssh.key.add <user> <public-key-file>"
                cwd = self.variables.get("SYS.CWD", f"/Users/{current_user}/home")
                try:
                    host_key_path = Path(args[1]).expanduser()
                    if host_key_path.is_absolute() and host_key_path.is_file():
                        key_path = host_key_path
                    else:
                        key_path, _ = self.storage.resolve_vpath(args[1], cwd, current_user)
                    if key_path.stat().st_size > 16 * 1024:
                        raise ValueError("Public-key file must be no larger than 16 KiB")
                    public_key = key_path.read_text(encoding="utf-8")
                    fingerprint = self.ssh_service.add_authorized_key(target_user, public_key)
                    return f"Authorized Ed25519 key for '{target_user}'. Fingerprint: {fingerprint}"
                except (OSError, ValueError) as exc:
                    return f"[SSH KEY ERROR] {exc}"
            if len(args) != 2:
                return "Usage: ssh.key.remove <user> <fingerprint>"
            try:
                removed = self.ssh_service.remove_authorized_key(target_user, args[1])
            except (OSError, ValueError) as exc:
                return f"[SSH KEY ERROR] {exc}"
            return "SSH public key revoked." if removed else "No matching SSH key fingerprint found."

        elif cmd == "net.ifconfig":
            return self.format_ifconfig()

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

        elif cmd == "net.speed":
            if args:
                return "Usage: net.speed"
            return self.run_network_speed_test()

        elif cmd == "script.run":
            if not args:
                return "Usage: script.run <path-to-script-file> [args...]"
            if not args[0].lower().endswith(".pow"):
                return "[Script Error]: Operator scripts must use the .pow format."
            return self.pow.execute_file(args[0])

        elif cmd in ("drive.mount", "drive.connect"):
            if args:
                return "Usage: drive.mount"
            cur_u = self.variables.get("SYS.USER", "operator")
            try:
                return self.google_drive.mount_interactively(username=cur_u)
            except KeyboardInterrupt:
                return "[DRIVE CANCELLED] Google Drive connection cancelled; Operator Shell is still running."
            except Exception as exc:
                return f"\033[31m[DRIVE ERROR]\033[0m {exc}"

        elif cmd == "drive.status":
            if args:
                return "Usage: drive.status"
            cur_u = self.variables.get("SYS.USER", "operator")
            status = self.google_drive.status(cur_u)
            state = "MOUNTED" if status["authenticated"] else "NOT MOUNTED"
            write_state = "unlocked" if status["write_unlocked"] else "locked"
            details = "\n".join(f"Sync: {message}" for message in status["sync_messages"])
            return (
                f"Google Drive: {state}\nMount: {status['mount']}\n"
                f"Automatic uploads: {write_state}"
                + (f"\n{details}" if details else "")
            )

        elif cmd == "drive.ls":
            if len(args) > 1:
                return "Usage: drive.ls [remote-path]"
            remote_path = args[0] if args else "root"
            cur_u = self.variables.get("SYS.USER", "operator")
            try:
                entries = self.google_drive.list_files(remote_path, username=cur_u)
            except Exception as exc:
                return f"\033[31m[DRIVE ERROR]\033[0m {exc}"
            if not entries:
                return "(empty Google Drive folder)"
            rows = ["ID                                     TYPE       SIZE       NAME", "-" * 76]
            for entry in entries:
                kind = "DIR" if entry.get("mimeType") == "application/vnd.google-apps.folder" else "FILE"
                size = entry.get("size", "-")
                rows.append(f"{entry['id']:<38} {kind:<10} {size:>10}  {entry['name']}")
            return "\n".join(rows)

        elif cmd == "drive.download":
            if len(args) != 1:
                return "Usage: drive.download <file-id-or-path>"
            cur_u = self.variables.get("SYS.USER", "operator")
            try:
                target = self.google_drive.download_file(args[0], username=cur_u)
                _, virtual_mount = self.storage.resolve_vpath(
                    f"/Users/{cur_u}/Google Drive",
                    "/",
                    cur_u,
                )
                return f"Downloaded to {virtual_mount}/{Path(target).name}"
            except Exception as exc:
                return f"\033[31m[DRIVE ERROR]\033[0m {exc}"

        elif cmd == "drive.upload":
            if len(args) != 1:
                return "Usage: drive.upload <file>"
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            try:
                local_path, _ = self.storage.resolve_vpath(args[0], cwd, cur_u)
                return self.google_drive.upload_file(local_path, username=cur_u)
            except Exception as exc:
                return f"\033[31m[DRIVE ERROR]\033[0m {exc}"

        elif cmd == "drive.write.setup":
            if args:
                return "Usage: drive.write.setup"
            cur_u = self.variables.get("SYS.USER", "operator")
            try:
                return self.google_drive.setup_write_passphrase(cur_u)
            except Exception as exc:
                return f"\033[31m[DRIVE ERROR]\033[0m {exc}"

        elif cmd == "drive.write.unlock":
            if args:
                return "Usage: drive.write.unlock"
            cur_u = self.variables.get("SYS.USER", "operator")
            try:
                return self.google_drive.unlock_writes(cur_u)
            except Exception as exc:
                return f"\033[31m[DRIVE ERROR]\033[0m {exc}"

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

        # ── Multi-User Management ───────────────────────────────────────────────
        elif cmd in ("user.list", "users"):
            return self.format_user_list()

        elif cmd in ("user.create", "useradd"):
            cur_u = self.variables.get("SYS.USER", "operator")
            if cur_u != "root":
                return f"\033[31m[PERMISSION DENIED]\033[0m Creating users requires superuser privileges.\nUse: \033[1;36mpassd {line}\033[0m"
            if len(args) < 2:
                return "Usage: user.create <username> <password> [memory_mb]"
            uname, passwd = args[0], args[1]
            mem_mb = int(args[2]) if len(args) > 2 else None
            try:
                ok, msg = self.user_mgr.create_user(uname, passwd, memory_mb=mem_mb)
                if ok:
                    ui = self.user_mgr.get_user(uname) or {}
                    return (f"\033[1;32m[USER CREATED]\033[0m '{uname}' provisioned successfully.\n"
                            f"  Home:   /Users/{uname}/home\n"
                            f"  RAM:    {ui.get('memory_mb', '?')} MB dedicated\n"
                            f"  Quota:  {ui.get('quota_mb', '?')} MB disk quota\n"
                            f"  Status: Filesystem hierarchy initialized in 2GB storage.")
                return f"\033[31m[USER ERROR]\033[0m {msg}"
            except Exception as e:
                return f"\033[31m[USER ERROR]\033[0m {e}"

        elif cmd in ("user.delete", "userdel"):
            cur_u = self.variables.get("SYS.USER", "operator")
            if cur_u != "root":
                return f"\033[31m[PERMISSION DENIED]\033[0m Deleting users requires superuser privileges.\nUse: \033[1;36mpassd {line}\033[0m"
            if not args:
                return "Usage: user.delete <username>"
            uname = args[0]
            if uname in ("root", "operator"):
                return f"\033[31m[DENIED]\033[0m Cannot delete protected system user '{uname}'."
            try:
                ok, msg = self.user_mgr.delete_user(uname)
                if ok:
                    return (f"\033[1;33m[USER DELETED]\033[0m '{uname}' removed.\n"
                            f"  Filesystem purged from 2GB storage.\n"
                            f"  Memory pool reclaimed successfully.")
                return f"\033[31m[USER ERROR]\033[0m {msg}"
            except Exception as e:
                return f"\033[31m[USER ERROR]\033[0m {e}"

        elif cmd in ("user.login", "login"):
            if len(args) < 2:
                return "Usage: user.login <username> <password>"
            uname, passwd = args[0], args[1]
            try:
                ok = self.user_mgr.authenticate(uname, passwd)
                if ok:
                    self.variables["SYS.USER"] = uname
                    self.variables["SYS.CWD"] = f"/Users/{uname}/home"
                    ui = self.user_mgr.get_user(uname)
                    role = ui.get("role", "user") if ui else "user"
                    self.security.current_user = uname
                    self.security.current_role = role
                    return (f"\033[1;32m[LOGIN OK]\033[0m Session started as '{uname}' (Role: {role})\n"
                            f"  Working directory set to: /Users/{uname}/home")
                return "\033[31m[LOGIN FAILED]\033[0m Invalid username or password."
            except Exception as e:
                return f"\033[31m[LOGIN ERROR]\033[0m {e}"

        elif cmd == "logout":
            if args:
                return "Usage: logout"
            previous_user = self.variables.get("SYS.USER", "operator")
            self.variables["SYS.USER"] = "operator"
            self.variables["SYS.CWD"] = "/Users/operator/home"
            self.user_mgr.active_user = "operator"
            self.user_mgr.active_role = "user"
            self.security.current_user = "operator"
            self.security.current_role = "user"
            getattr(self, "_passd_auth_cache", {}).pop(previous_user, None)
            return (
                "\033[1;32m[LOGOUT OK]\033[0m Signed out of "
                f"'{previous_user}' and switched to the default operator account.\n"
                "  Working directory set to: /Users/operator/home"
            )

        elif cmd in ("user.switch", "su"):
            if not args:
                return "Usage: user.switch <username>  (then run 'user.login' if password required)"
            uname = args[0]
            if len(args) >= 2:
                return self.eval_command(f"user.login {args[0]} {args[1]}")
            try:
                user_info = self.user_mgr.get_user(uname)
                if user_info:
                    self.variables["SYS.USER"] = uname
                    self.variables["SYS.CWD"] = f"/Users/{uname}/home"
                    self.user_mgr.active_user = uname
                    self.user_mgr.active_role = user_info.get("role", "user")
                    self.security.current_user = uname
                    self.security.current_role = user_info.get("role", "user")
                    return (f"\033[1;33m[SU]\033[0m Switched to user '{uname}'.\n"
                            f"  CWD set to /Users/{uname}/home")
                return f"\033[31m[SU FAILED]\033[0m User '{uname}' not found."
            except Exception as e:
                return f"\033[31m[SU ERROR]\033[0m {e}"

        elif cmd in ("user.whoami", "whoami"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            try:
                user_info = self.user_mgr.get_user(cur_u)
                role = user_info.get("role", "user") if user_info else "user"
            except Exception:
                role = "user"
            return (f"\033[1;36mUser:\033[0m  {cur_u}\n"
                    f"\033[1;36mRole:\033[0m  {role}\n"
                    f"\033[1;36mCWD:\033[0m   {cwd}")

        elif cmd in ("user.memory", "mem.user"):
            target_u = args[0] if args else None
            return self.format_user_memory(target_u)



        # ── User & Security System (legacy auth.* aliases) ──────────────────────

        elif cmd == "auth.login":
            if len(args) < 2: return "Usage: auth.login <username> <password>"
            user, pwd = args[0], args[1]
            if self.security.authenticate(user, pwd):
                self.variables["SYS.USER"] = user
                self.variables["SYS.CWD"] = f"/Users/{user}/home"
                self.user_mgr.active_user = user
                self.user_mgr.active_role = self.security.current_role
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
            if not args: return "Usage: app.launch <app-name-or-id> (e.g. app.launch Calculator, app.launch Nano)"
            target_app = " ".join(args)
            if target_app.casefold() in ("app.nano", "nano", "app.editor", "editor", "operator code editor"):
                return self.eval_command("nano")
            if args[0].lower() in ("app.nano", "nano", "app.editor", "editor"):
                target_f = " ".join(args[1:]) if len(args) > 1 else None
                return self.eval_command(f"nano {target_f}" if target_f else "nano")
            return self.app_mgr.launch(target_app)

        elif cmd == "app.close":
            if not args: return "Usage: app.close <app-name-or-id>"
            return self.app_mgr.close(args[0])

        elif cmd == "games.list":
            current_user = self.variables.get("SYS.USER", "operator")
            games_path, virtual_path = self.storage.resolve_vpath(
                f"/Users/{current_user}/home/Games",
                self.variables.get("SYS.CWD", f"/Users/{current_user}/home"),
                current_user,
            )
            if not games_path.is_dir():
                return f"[GAMES] No games directory exists at {virtual_path}."
            games = sorted(
                (entry for entry in games_path.iterdir() if entry.is_file() and entry.suffix.lower() == ".exe"),
                key=lambda entry: entry.name.casefold(),
            )
            if not games:
                return f"[GAMES] No installed games found in {virtual_path}."
            game_states = {}
            if hasattr(self, "game_mgr"):
                game_states = {
                    game["executable"].casefold(): game["status"]
                    for game in self.game_mgr.list_games(games_path)
                }
            rows = ["GAME                           STATUS      EXECUTABLE", "-" * 76]
            rows.extend(
                f"{game.stem:<30} {game_states.get(game.name.casefold(), 'INSTALLED'):<11} {game.name}"
                for game in games
            )
            return "\n".join(rows)

        elif cmd in ("games.launch", "game.launch"):
            if not args:
                return "Usage: games.launch <game-name> [arguments...]"
            current_user = self.variables.get("SYS.USER", "operator")
            games_path, _ = self.storage.resolve_vpath(
                f"/Users/{current_user}/home/Games",
                self.variables.get("SYS.CWD", f"/Users/{current_user}/home"),
                current_user,
            )
            if not hasattr(self, "game_mgr"):
                return "[GAME ERROR] The game launcher is unavailable in this shell instance."
            try:
                return self.game_mgr.launch(args[0], games_path, args=args[1:])
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                return f"[GAME ERROR] {exc}"

        elif cmd in ("python.check", "python.run"):
            if not args or Path(args[0]).suffix.casefold() not in (".py", ".pyw"):
                return f"Usage: {cmd} <file.py>" + (" [args...]" if cmd == "python.run" else "")
            current_user = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{current_user}/home")
            script_path, _ = self.storage.resolve_vpath(args[0], cwd, current_user)
            if not script_path.is_file():
                return f"[PYTHON ERROR] Script was not found: {args[0]}"
            if cmd == "python.check":
                from apps.language_services import python_syntax_diagnostic

                try:
                    source = script_path.read_text(encoding="utf-8-sig")
                except OSError as exc:
                    return f"[PYTHON ERROR] Could not read {args[0]}: {exc}"
                diagnostic = python_syntax_diagnostic(source, str(script_path))
                return (
                    f"[PYTHON SYNTAX ERROR] {args[0]}: {diagnostic}"
                    if diagnostic
                    else f"[PYTHON CHECK] {args[0]}: syntax OK"
                )
            try:
                result = subprocess.run(
                    [sys.executable, str(script_path.resolve()), *args[1:]],
                    cwd=str(script_path.resolve().parent),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                return f"[PYTHON ERROR] Could not start Python: {exc}"
            output = (result.stdout + result.stderr).strip()
            if result.returncode:
                return (
                    f"[PYTHON ERROR] Script exited with code {result.returncode}.\n{output}"
                    if output
                    else f"[PYTHON ERROR] Script exited with code {result.returncode}."
                )
            return output or f"[PYTHON] {args[0]} completed."

        elif cmd == "vyn.run":
            if len(args) != 1 or Path(args[0]).suffix.casefold() != ".vyn":
                return "Usage: vyn.run <file.vyn>"
            current_user = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{current_user}/home")
            script_path, _ = self.storage.resolve_vpath(args[0], cwd, current_user)
            if not script_path.is_file():
                return f"[VYN ERROR] Script was not found: {args[0]}"
            if not (VYN_RUNTIME_DIR / "main.py").is_file() or not (
                VYN_RUNTIME_DIR / "dependency.py"
            ).is_file():
                return (
                    f"[VYN ERROR] Interpreter was not found at {VYN_RUNTIME_DIR}. "
                    "Set OPERATOR_VYN_HOME to the directory containing Vyn's main.py."
                )
            runner = (
                "import sys; import dependency; "
                "from functions import execute_line; "
                "from variables import global_vars; "
                "dependency.load_vyn_file(sys.argv[1], execute_line, global_vars.variables)"
            )
            try:
                result = subprocess.run(
                    [sys.executable, "-c", runner, str(script_path.resolve())],
                    cwd=str(VYN_RUNTIME_DIR),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                return f"[VYN ERROR] Could not start the Vyn interpreter: {exc}"
            output = (result.stdout + result.stderr).strip()
            if result.returncode:
                return f"[VYN ERROR] Interpreter exited with code {result.returncode}.\n{output}".strip()
            return output or "[VYN] Script completed."

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
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            srvs = self.services.list_services()
            res = ["\033[1;36mUNIT                         ACTIVE     HEALTH      PID     RESTARTS   POLICY      DESCRIPTION\033[0m", "-"*92]
            for s in srvs:
                res.append(
                    f"{s['unit']:<28} {s['active']:<10} {s['sub']:<11} "
                    f"{str(s['pid'] or '-'):<7} {s['restart_count']:<10} "
                    f"{s['restart']:<11} {s['description']}"
                )
            return "\n".join(res)

        elif cmd == "srv.start":
            if not args:
                return "Usage: srv.start <service-name>"
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Service process control requires superuser privileges. Use passd."
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            return self.services.start(args[0])

        elif cmd == "srv.stop":
            if not args:
                return "Usage: srv.stop <service-name>"
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Service process control requires superuser privileges. Use passd."
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            return self.services.stop(args[0])

        elif cmd == "srv.restart":
            if len(args) != 1:
                return "Usage: srv.restart <service-name>"
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Service process control requires superuser privileges. Use passd."
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            return self.services.restart(args[0])

        elif cmd == "srv.register":
            if len(args) < 3 or "--" not in args:
                return (
                    "Usage: srv.register <name> [--description <text>] "
                    "[--restart no|on-failure|always] [--health process|tcp:host:port] "
                    "-- <executable> [args...]"
                )
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Registering host processes requires superuser privileges. Use passd."
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            separator = args.index("--")
            name = args[0]
            options = args[1:separator]
            command = args[separator + 1:]
            if not command:
                return "srv.register requires an executable after '--'."
            description = name
            restart_policy = "always"
            health_check = "process"
            index = 0
            try:
                while index < len(options):
                    option = options[index]
                    if option in ("--description", "--restart", "--health") and index + 1 < len(options):
                        value = options[index + 1]
                        if option == "--description":
                            description = value
                        elif option == "--restart":
                            restart_policy = value
                        else:
                            health_check = value
                        index += 2
                    else:
                        return f"Unknown or incomplete service option: {option}"
                registered = self.services.register(
                    name,
                    command,
                    description,
                    restart_policy,
                    health_check,
                )
                if not registered.startswith("[SRV REGISTERED]"):
                    return registered
                started = self.services.start(name)
                return f"{registered}\n{started}"
            except (OSError, ValueError) as exc:
                return f"[SERVICE ERROR] {exc}"

        elif cmd == "srv.remove":
            if len(args) != 1:
                return "Usage: srv.remove <service-name>"
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Service process control requires superuser privileges. Use passd."
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            return self.services.remove(args[0])

        elif cmd == "srv.logs":
            if not args or len(args) > 2:
                return "Usage: srv.logs <service-name> [count]"
            if self.variables.get("SYS.USER") != "root":
                return "[PERMISSION DENIED] Service logs require superuser privileges. Use passd."
            if not self.services:
                return f"[SERVICE ERROR] {self.service_runtime_error or 'C++ service runtime is unavailable.'}"
            try:
                return "\n".join(self.services.get_logs(args[0], int(args[1]) if len(args) == 2 else 100))
            except ValueError:
                return "srv.logs count must be an integer."

        elif cmd == "cron.add":
            if len(args) < 4:
                return "Usage: cron.add <name> <interval-seconds> <safe-command...>"
            if not self.services:
                return f"[SCHEDULER ERROR] {self.service_runtime_error or 'C++ scheduler runtime is unavailable.'}"
            try:
                interval = int(args[1])
                job_command = shlex.join(args[2:])
                existing_job = next(
                    (job for job in self.services.list_jobs() if job["name"] == args[0]),
                    None,
                )
                current_user = self.variables["SYS.USER"]
                if existing_job and existing_job["owner"] != current_user and current_user != "root":
                    return "[PERMISSION DENIED] A scheduled job with that name belongs to another user."
                error = self._validate_scheduled_command(job_command, self.variables["SYS.USER"])
                if error:
                    return f"[SCHEDULER ERROR] {error}"
                return self.services.add_job(
                    args[0],
                    self.variables["SYS.USER"],
                    interval,
                    job_command,
                )
            except (OSError, ValueError) as exc:
                return f"[SCHEDULER ERROR] {exc}"

        elif cmd == "cron.list":
            if args:
                return "Usage: cron.list"
            if not self.services:
                return f"[SCHEDULER ERROR] {self.service_runtime_error or 'C++ scheduler runtime is unavailable.'}"
            current_user = self.variables.get("SYS.USER", "operator")
            jobs = [
                job for job in self.services.list_jobs()
                if job["owner"] == current_user or current_user == "root"
            ]
            if not jobs:
                return "No scheduled jobs."
            rows = ["NAME                 OWNER          INTERVAL   NEXT RUN             STATE      COMMAND", "-" * 104]
            for job in jobs:
                state = "running" if job["running"] else "scheduled"
                rows.append(
                    f"{job['name']:<20} {job['owner']:<14} {job['interval_seconds']:<10} "
                    f"{job['next_run']:<20} {state:<10} {job['command']}"
                )
            return "\n".join(rows)

        elif cmd == "cron.remove":
            if len(args) != 1:
                return "Usage: cron.remove <name>"
            if not self.services:
                return f"[SCHEDULER ERROR] {self.service_runtime_error or 'C++ scheduler runtime is unavailable.'}"
            current_user = self.variables.get("SYS.USER", "operator")
            job = next((job for job in self.services.list_jobs() if job["name"] == args[0]), None)
            if not job:
                return f"[SCHEDULER ERROR] Unknown job '{args[0]}'."
            if job["owner"] != current_user and current_user != "root":
                return "[PERMISSION DENIED] You can only remove your own scheduled jobs."
            return self.services.remove_job(args[0])

        elif cmd == "cron.logs":
            if not args or len(args) > 2:
                return "Usage: cron.logs <name> [count]"
            if not self.services:
                return f"[SCHEDULER ERROR] {self.service_runtime_error or 'C++ scheduler runtime is unavailable.'}"
            job = next((job for job in self.services.list_jobs() if job["name"] == args[0]), None)
            if not job:
                return f"[SCHEDULER ERROR] Unknown job '{args[0]}'."
            current_user = self.variables.get("SYS.USER", "operator")
            if job["owner"] != current_user and current_user != "root":
                return "[PERMISSION DENIED] You can only view your own scheduled job logs."
            try:
                return "\n".join(self.services.get_job_logs(args[0], int(args[1]) if len(args) == 2 else 100))
            except ValueError:
                return "cron.logs count must be an integer."

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
            return self.format_pkg_list()

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
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            target = args[0] if args else f"/Users/{cur_u}/home"
            phys, norm = self.storage.resolve_vpath(target, cwd, cur_u)
            if phys.is_dir():
                self.variables["SYS.CWD"] = norm
                return None
            return f"\033[31mcd: {target}: No such directory in Atlas OS storage\033[0m"

        elif cmd in ("dir", "get-childitem", "gci"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            v_arg = args[0] if args else cwd
            phys, norm = self.storage.resolve_vpath(v_arg, cwd, cur_u)
            if not phys.exists():
                return f"\033[31mdir: Path not found: {v_arg}\033[0m"
            entries = sorted(list(phys.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            res = [f"\033[1;36mMode                 LastWriteTime         Length Name ({norm})\033[0m", "-"*72]
            for e in entries:
                display_name = e.name
                mode = "d-----" if e.is_dir() else "-a----"
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.stat().st_mtime))
                size_str = str(e.stat().st_size) if not e.is_dir() else ""
                res.append(f"{mode:<20} {mtime:<20} {size_str:>10} {display_name}")
            return "\n".join(res)

        # Linux Commands
        elif cmd == "ls":
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            show_long = any(a in ("-l", "-la", "-al", "-lh") for a in args)
            show_all = any(a in ("-a", "-la", "-al") for a in args)
            raw_paths = [a for a in args if not a.startswith("-")]
            v_arg = raw_paths[0] if raw_paths else cwd
            phys, norm = self.storage.resolve_vpath(v_arg, cwd, cur_u)
            if not phys.exists():
                return f"\033[31mls: cannot access '{v_arg}': No such file or directory\033[0m"
            items = list(phys.iterdir())
            if not show_all:
                items = [i for i in items if not i.name.startswith(".")]
            items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
            if not show_long:
                names = []
                for i in items:
                    names.append(f"\033[1;34m{i.name}/\033[0m" if i.is_dir() else i.name)
                return "  ".join(names) if names else "(empty directory)"
            res = [f"total {len(items)}"]
            for i in items:
                st = i.stat()
                perms = "drwxr-xr-x" if i.is_dir() else "-rw-r--r--"
                mtime = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
                name_str = f"\033[1;34m{i.name}/\033[0m" if i.is_dir() else i.name
                res.append(f"{perms} 1 {cur_u} {cur_u} {st.st_size:>8} {mtime} {name_str}")
            return "\n".join(res)

        elif cmd == "pwd":
            return self.variables.get("SYS.CWD", "/")

        elif cmd in ("hostname",):
            return str(self.variables.get("SYS.HOSTNAME", "atlas"))

        elif cmd in ("env", "printenv"):
            return "\n".join(f"{key}={value}" for key, value in sorted(self.variables.items()))

        elif cmd == "id":
            user = self.variables.get("SYS.USER", "operator")
            return f"uid=1000({user}) gid=1000({user}) groups=1000({user})"

        elif cmd == "which":
            if not args:
                return "Usage: which <command>"
            name = args[0].lower()
            return name if name in {c.lower() for c in self.get_command_list()} else f"which: no {args[0]} in Atlas PATH"

        elif cmd == "echo":
            return " ".join(args)

        elif cmd == "true":
            return None

        elif cmd == "false":
            return "false"

        elif cmd in ("cat", "type", "get-content", "gc"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return f"Usage: {cmd} <file>"
            phys, _ = self.storage.resolve_vpath(args[0], cwd, cur_u)
            if not phys.exists():
                return f"\033[31m{cmd}: {args[0]}: No such file or directory\033[0m"
            try:
                return phys.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"\033[31m{cmd}: error reading file: {e}\033[0m"

        elif cmd == "touch":
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return "Usage: touch <filename>"
            phys, _ = self.storage.resolve_vpath(args[0], cwd, cur_u)
            phys.parent.mkdir(parents=True, exist_ok=True)
            phys.touch(exist_ok=True)
            return None

        elif cmd == "mkdir":
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return "Usage: mkdir <directory>"
            self.storage.virtual_mkdir(args[0], cwd, cur_u)
            return None

        elif cmd in ("rm", "del"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return f"Usage: {cmd} <path>"
            target = args[0]
            if any(ch in target for ch in "*?["):
                parent_text, pattern = target.rsplit("/", 1) if "/" in target else (".", target)
                parent_phys, parent_norm = self.storage.resolve_vpath(parent_text, cwd, cur_u)
                matches = list(parent_phys.glob(pattern))
                if not matches:
                    return f"\033[31m{cmd}: cannot remove '{target}': No such file or directory\033[0m"
                for match in matches:
                    relative = f"{parent_norm.rstrip('/')}/{match.name}"
                    self.storage.virtual_remove(relative, "/", cur_u)
                return None
            ok = self.storage.virtual_remove(target, cwd, cur_u)
            if ok:
                return None
            return f"\033[31m{cmd}: cannot remove '{target}': No such file or directory\033[0m"

        elif cmd == "grep":
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if len(args) < 2:
                return "Usage: grep <pattern> <file>"
            pattern, filename = args[0], args[1]
            phys, _ = self.storage.resolve_vpath(filename, cwd, cur_u)
            if not phys.exists():
                return f"\033[31mgrep: {filename}: No such file or directory\033[0m"
            try:
                lines = phys.read_text(encoding="utf-8", errors="replace").splitlines()
                matches = []
                regex = re.compile(pattern)
                for i, l in enumerate(lines, 1):
                    if regex.search(l):
                        highlighted = regex.sub(f"\033[1;31m\\g<0>\033[0m", l)
                        matches.append(f"\033[1;32m{i}\033[0m: {highlighted}")
                return "\n".join(matches) if matches else "(no matches found)"
            except Exception as e:
                return f"\033[31mgrep: error: {e}\033[0m"

        elif cmd in ("head", "tail"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return f"Usage: {cmd} [-n NUM] <file>"
            count = 10
            file_arg = args[-1]
            if len(args) >= 3 and args[0] == "-n":
                try:
                    count = int(args[1])
                except ValueError:
                    return f"{cmd}: invalid line count"
            phys, _ = self.storage.resolve_vpath(file_arg, cwd, cur_u)
            if not phys.exists():
                return f"{cmd}: {file_arg}: No such file or directory"
            lines = phys.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[:count] if cmd == "head" else lines[-count:]
            return "\n".join(selected)

        elif cmd in ("sort", "uniq", "cut", "tr"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return f"Usage: {cmd} <file>"
            file_arg = args[-1]
            phys, _ = self.storage.resolve_vpath(file_arg, cwd, cur_u)
            if not phys.exists():
                return f"{cmd}: {file_arg}: No such file or directory"
            lines = phys.read_text(encoding="utf-8", errors="replace").splitlines()
            if cmd == "sort":
                return "\n".join(sorted(lines, reverse=("-r" in args)))
            if cmd == "uniq":
                result = []
                for line in lines:
                    if not result or result[-1] != line:
                        result.append(line)
                return "\n".join(result)
            if cmd == "cut":
                delimiter = "\t"
                field = 1
                if "-d" in args:
                    delimiter = args[args.index("-d") + 1]
                if "-f" in args:
                    field = int(args[args.index("-f") + 1])
                return "\n".join(row.split(delimiter)[field - 1] for row in lines if len(row.split(delimiter)) >= field)
            if len(args) < 3:
                return "Usage: tr <FROM> <TO> <file>"
            return "\n".join(line.translate(str.maketrans(args[0], args[1])) for line in lines)

        elif cmd in ("basename", "dirname", "realpath"):
            if not args:
                return f"Usage: {cmd} <path>"
            target = Path(args[0].replace("\\", "/"))
            if cmd == "basename":
                return target.name
            if cmd == "dirname":
                return str(target.parent).replace("\\", "/")
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            _, norm = self.storage.resolve_vpath(args[0], cwd, cur_u)
            return norm

        elif cmd in ("stat", "file", "du"):
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            target = args[-1] if args else cwd
            phys, norm = self.storage.resolve_vpath(target, cwd, cur_u)
            if not phys.exists():
                return f"{cmd}: cannot stat '{target}': No such file or directory"
            if cmd == "file":
                kind = "directory" if phys.is_dir() else "empty" if phys.stat().st_size == 0 else "regular file"
                return f"{norm}: {kind}"
            if cmd == "du":
                total = sum(p.stat().st_size for p in phys.rglob("*") if p.is_file()) if phys.is_dir() else phys.stat().st_size
                return f"{(total + 1023) // 1024}\t{norm}"
            st = phys.stat()
            kind = "directory" if phys.is_dir() else "regular file"
            return f"  File: {norm}\n  Size: {st.st_size}\n  Type: {kind}\nModify: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}"

        elif cmd == "find":
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            start = args[0] if args and not args[0].startswith("-") else "."
            pattern = "*"
            if "-name" in args and args.index("-name") + 1 < len(args):
                pattern = args[args.index("-name") + 1]
            phys, norm = self.storage.resolve_vpath(start, cwd, cur_u)
            if not phys.exists():
                return f"find: '{start}': No such file or directory"
            matches = []
            for entry in ([phys] if phys.is_file() else phys.rglob("*")):
                if fnmatch.fnmatch(entry.name, pattern):
                    try:
                        _, entry_norm = self.storage.resolve_vpath(str(entry.relative_to(phys)) if entry != phys else ".", norm, cur_u)
                        matches.append(entry_norm)
                    except Exception:
                        matches.append(str(entry))
            return "\n".join(matches)

        elif cmd == "df":
            return self.format_df()

        elif cmd == "free":
            return self.format_free()

        elif cmd == "mem":
            return self.format_free()

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
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            if not args:
                return "Usage: wc [-l|-w|-c] <file>"
            target_f = args[-1]
            phys, _ = self.storage.resolve_vpath(target_f, cwd, cur_u)
            if not phys.exists():
                return f"\033[31mwc: {target_f}: No such file or directory\033[0m"
            text = phys.read_text(encoding="utf-8", errors="replace")
            lines_c = len(text.splitlines())
            words_c = len(text.split())
            bytes_c = len(text.encode("utf-8"))
            return f"{lines_c:>8} {words_c:>8} {bytes_c:>8} {target_f}"

        # Enhanced File & Directory Features
        elif cmd in ("cp", "copy"):
            if len(args) < 2:
                return f"Usage: {cmd} [-r] <source> <destination>"
            recursive = "-r" in args or "-R" in args
            paths = [a for a in args if not a.startswith("-")]
            if len(paths) < 2:
                return f"Usage: {cmd} [-r] <source> <destination>"
            src_str, dst_str = paths[0], paths[1]
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            src_phys, src_norm = self.storage.resolve_vpath(src_str, cwd, cur_u)
            dst_phys, dst_norm = self.storage.resolve_vpath(dst_str, cwd, cur_u)
            if not src_phys.exists():
                return f"\033[31m{cmd}: cannot stat '{src_str}': No such file or directory\033[0m"
            try:
                if src_phys.is_dir():
                    if not recursive:
                        return f"\033[31m{cmd}: -r not specified; omitting directory '{src_str}'\033[0m"
                    if dst_phys.exists() and dst_phys.is_dir():
                        final_dst = dst_phys / src_phys.name
                    else:
                        final_dst = dst_phys
                    shutil.copytree(src_phys, final_dst, dirs_exist_ok=True)
                else:
                    if dst_phys.is_dir():
                        final_dst = dst_phys / src_phys.name
                    else:
                        final_dst = dst_phys
                        final_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_phys, final_dst)
                return None
            except Exception as e:
                return f"\033[31m{cmd}: error: {e}\033[0m"

        elif cmd in ("mv", "move", "rename", "ren"):
            if len(args) < 2:
                return f"Usage: {cmd} <source> <destination>"
            src_str, dst_str = args[0], args[1]
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            src_phys, src_norm = self.storage.resolve_vpath(src_str, cwd, cur_u)
            dst_phys, dst_norm = self.storage.resolve_vpath(dst_str, cwd, cur_u)
            if not src_phys.exists():
                return f"\033[31m{cmd}: cannot stat '{src_str}': No such file or directory\033[0m"
            try:
                if dst_phys.is_dir():
                    final_dst = dst_phys / src_phys.name
                else:
                    final_dst = dst_phys
                    final_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_phys), str(final_dst))
                return None
            except Exception as e:
                return f"\033[31m{cmd}: error: {e}\033[0m"

        elif cmd in ("rmdir", "rd"):
            if not args:
                return f"Usage: {cmd} <directory>"
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            phys, norm = self.storage.resolve_vpath(args[0], cwd, cur_u)
            if not phys.exists() or not phys.is_dir():
                return f"\033[31m{cmd}: failed to remove '{args[0]}': No such directory\033[0m"
            try:
                phys.rmdir()
                return None
            except OSError:
                return f"\033[31m{cmd}: failed to remove '{args[0]}': Directory not empty\033[0m"

        elif cmd == "md":
            return self.eval_command(f"mkdir {' '.join(args)}")

        # macOS Utilities
        elif cmd == "sw_vers":
            return """ProductName:\tAtlas macOS Subsystem Bridge
ProductVersion:\t15.4 (Atlas Darwin 24.4.0)
BuildVersion:\t24E248 (Atlas Kernel x86_64)"""

        elif cmd in ("pbcopy",):
            text = " ".join(args) if args else ""
            if not text and not sys.stdin.isatty():
                try:
                    text = sys.stdin.read()
                except Exception:
                    pass
            self.win.clipboard_set(text)
            return None

        elif cmd in ("pbpaste",):
            return self.win.clipboard_get()

        elif cmd == "say":
            if not args:
                return "Usage: say <message>"
            msg = " ".join(args)
            try:
                script = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{msg}')"
                subprocess.Popen(["powershell", "-NoProfile", "-Command", script])
                return f"[Speaking: \"{msg}\"]"
            except Exception:
                return f"[Voice synthesizer output: \"{msg}\"]"

        elif cmd == "open":
            if not args:
                return "Usage: open <file|url|app>"
            target = args[0]
            if target.startswith(("http://", "https://")):
                import webbrowser
                webbrowser.open(target)
                return f"Opened {target} in default browser."
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            phys, norm = self.storage.resolve_vpath(target, cwd, cur_u)
            if phys.exists():
                os.startfile(str(phys))
                return f"Opened {norm}"
            return f"open: cannot open '{target}': No such file or directory"

        elif cmd == "cal":
            import calendar
            now = time.localtime()
            year = int(args[1]) if len(args) > 1 and args[1].isdigit() else now.tm_year
            month = int(args[0]) if args and args[0].isdigit() else now.tm_mon
            return calendar.month(year, month)

        elif cmd == "history":
            hist = self.storage.load_command_history()
            res = []
            for idx, h in enumerate(hist[-50:], 1):
                res.append(f"{idx:>5}  {h}")
            return "\n".join(res) if res else "No command history recorded."

        elif cmd == "alias":
            if not args:
                return """alias ll='ls -l'
alias la='ls -a'
alias edit='nano'
alias pico='nano'
alias sudo='passd'
alias cp='copy'
alias mv='move'
alias cls='clear'
alias md='mkdir'
alias rd='rmdir'"""
            return f"alias {args[0]} registered."

        elif cmd == "watch":
            if not args:
                return "Usage: watch [-n seconds] <command>"
            interval = 2
            sub_cmd = args
            if len(args) >= 3 and args[0] == "-n":
                try:
                    interval = int(args[1])
                    sub_cmd = args[2:]
                except ValueError:
                    pass
            full_sub = " ".join(sub_cmd)
            res = self.eval_command(full_sub)
            now_str = time.strftime("%a %b %d %H:%M:%S %Y")
            header = f"Every {interval}.0s: {full_sub:<40} {now_str}"
            return f"{header}\n{'-'*len(header)}\n{res or ''}"

        # Windows Utilities
        elif cmd == "winver":
            return """Microsoft Windows [Version 10.0.26100.3194]
Atlas OS Windows Subsystem Integration Layer [v2.0.0-PRO]
Licensed to: Operator Node (Workstation Edition)"""

        elif cmd in ("tasklist",):
            target_filter = args[0].lower() if args else None
            procs = self.proc_mgr.get_top()
            if target_filter:
                procs = [p for p in procs if target_filter in p['cmd'].lower()]
            res = [
                f"\033[1;36mImage Name                     PID Session Name        Session#    Mem Usage\033[0m",
                "="*75
            ]
            for p in procs:
                img_name = p['cmd'].split()[0] if p['cmd'] else "proc"
                mem_k = f"{p['pid'] * 1024:,} K"
                res.append(f"{img_name:<28} {p['pid']:<6} Console                    1   {mem_k:>10}")
            return "\n".join(res)

        elif cmd in ("taskkill", "kill"):
            cur_u = self.variables.get("SYS.USER", "operator")
            if cur_u != "root":
                return f"\033[31m[PERMISSION DENIED]\033[0m Terminating system processes requires superuser privileges.\nUse: \033[1;36mpassd {line}\033[0m"
            if not args:
                return f"Usage: {cmd} [/PID pid] [/IM imagename] [/F] or kill <pid>"
            pid = None
            for idx, a in enumerate(args):
                if a.upper() in ("/PID", "-P", "-PID") and idx + 1 < len(args):
                    pid = int(args[idx + 1])
                    break
                elif a.isdigit():
                    pid = int(a)
                    break
            if pid is not None:
                ok = self.proc_mgr.signal_process(pid, "SIGKILL")
                return f"\033[1;32mSUCCESS:\033[0m Sent termination signal to process with PID {pid}." if ok else f"\033[31mERROR:\033[0m Process PID {pid} not found."
            return f"{cmd}: Please specify a valid /PID or integer PID."

        elif cmd == "netstat":
            return """Active Connections

  Proto  Local Address          Foreign Address        State
  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING
  TCP    0.0.0.0:443            0.0.0.0:0              LISTENING
  TCP    127.0.0.1:5432         0.0.0.0:0              LISTENING
  TCP    127.0.0.1:6379         0.0.0.0:0              LISTENING
  TCP    192.168.1.100:52410    1.1.1.1:53             ESTABLISHED"""

        elif cmd in ("shutdown", "reboot", "restart-computer", "stop-computer"):
            cur_u = self.variables.get("SYS.USER", "operator")
            if cur_u != "root":
                return f"\033[31m[PERMISSION DENIED]\033[0m System power operations require superuser privileges.\nUse: \033[1;36mpassd {line}\033[0m"
            action = "restarting" if cmd in ("reboot", "restart-computer") or "-r" in args or "/r" in args else "shutting down"
            return (
                f"\033[1;33m[SYSTEM BROADCAST]\033[0m The Atlas OS subsystem is {action} now!\n"
                "All virtual page buffers committed to 2GB block device storage.\n"
                "Goodbye!"
            )

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

        elif cmd == "time":
            current = self.time_service.current_time()
            status = self.time_service.status()
            sync_state = (
                f"NTP offset {status['offset_seconds']:+.3f}s"
                if status["offset_seconds"] is not None
                else "NTP not synchronized"
            )
            return f"{current.strftime('%A, %B %d, %Y %I:%M:%S %p %Z')} ({sync_state})"

        elif cmd == "time.service":
            operation = args[0].lower() if args else "status"
            if operation == "start":
                self.time_service.start()
                return "[TIME SERVICE] NTP synchronization service started."
            if operation == "sync":
                if len(args) > 2:
                    return "Usage: time.service sync [ntp-server]"
                return self.time_service.sync_now(args[1] if len(args) == 2 else None)
            if operation != "status":
                return "Usage: time.service [status|start|sync [ntp-server]]"
            status = self.time_service.status()
            synchronized = (
                f"offset={status['offset_seconds']:+.3f}s"
                if status["offset_seconds"] is not None
                else "not synchronized"
            )
            last_sync = status["last_sync"].isoformat() if status["last_sync"] else "never"
            last_error = f"\nLast error: {status['last_error']}" if status["last_error"] else ""
            return (
                f"Time service: {'running' if status['running'] else 'stopped'}; "
                f"{synchronized}; last sync: {last_sync}{last_error}"
            )

        elif cmd in ("get-date", "date"):
            return self.eval_command("time")

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
            cur_u = self.variables.get("SYS.USER", "operator")
            cwd = self.variables.get("SYS.CWD", f"/Users/{cur_u}/home")
            path_args = [a for a in args if not a.startswith("-")]
            v_arg = path_args[0] if path_args else cwd
            phys, norm = self.storage.resolve_vpath(v_arg, cwd, cur_u)
            if not phys.exists():
                return f"\033[31mPath not found in Atlas OS storage: {v_arg}\033[0m"
            out_lines = [
                "\033[1;36mAtlas OS - 2GB Storage Filesystem Tree\033[0m",
                f"\033[1;33mVolume:\033[0m /dev/nvme0n1_operator  \033[1;33mMount:\033[0m /",
                f"\033[1;32m{norm}\033[0m"
            ]
            def walk_vfs(directory: "Path", vpath: str, depth: int, prefix: str):
                if depth > 4:
                    return
                try:
                    entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                except PermissionError:
                    return
                for idx, entry in enumerate(entries):
                    is_last = (idx == len(entries) - 1)
                    connector = "└── " if is_last else "├── "
                    child_vpath = f"{vpath.rstrip('/')}/{entry.name}"
                    if entry.is_dir():
                        out_lines.append(f"{prefix}{connector}\033[1;34m{entry.name}/\033[0m")
                        extension = "    " if is_last else "│   "
                        walk_vfs(entry, child_vpath, depth + 1, prefix + extension)
                    else:
                        out_lines.append(f"{prefix}{connector}{entry.name}")
                    if len(out_lines) > 80:
                        return
            walk_vfs(phys, norm, 0, "")
            return "\n".join(out_lines)


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
                # Never leak host-specific Windows exception names through the
                # Operator CLI. Normalize them to the platform-independent
                # AtlasError vocabulary.
                output = re.sub(r"WinError\s*\d+", "AtlasError", output, flags=re.IGNORECASE)
                output = output.replace("[Command Error]", "[AtlasError]")
                if output:
                    return output
                elif proc.returncode != 0:
                    return f"\033[31m[Command returned exit code {proc.returncode}]\033[0m"
                return None
            except subprocess.TimeoutExpired:
                return "\033[31m[Command Timeout]: Process took longer than 30 seconds.\033[0m"
            except Exception as e:
                detail = re.sub(r"WinError\s*\d+", "AtlasError", str(e), flags=re.IGNORECASE)
                return f"\033[31m[AtlasError]: '{cmd}': {detail}\033[0m"

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
        Interactive console line reader powered by prompt_toolkit.
        Supports tab auto-completion, arrow-key command history, and direct terminal input.
        """
        if self.prompt_session and sys.stdin.isatty():
            try:
                line = self.prompt_session.prompt(
                    ANSI(self.get_prompt_text()),
                    completer=self.completer,
                )
                cmd_str = line.strip()
                if cmd_str:
                    self.storage.append_command_history(cmd_str)
                return cmd_str
            except (KeyboardInterrupt, EOFError):
                raise
            except Exception:
                pass

        try:
            line = input(self.get_prompt_text())
            cmd_str = line.strip()
            if cmd_str:
                self.storage.append_command_history(cmd_str)
            return cmd_str
        except (KeyboardInterrupt, EOFError):
            raise

def print_banner():
    c = Console()
    if os.environ.get("OPERATOR_QUIET_START") == "1":
        c.print("[bold green]Operator Shell ready.[/bold green] Type [bold white]help[/bold white] for commands.")
        return

    logo = """[bold cyan]
      █████╗ ████████╗██╗      █████╗ ███████╗     ██████╗ ███████╗
     ██╔══██╗╚══██╔══╝██║     ██╔══██╗██╔════╝    ██╔═══██╗██╔════╝
     ███████║   ██║   ██║     ███████║███████╗    ██║   ██║███████╗
     ██╔══██║   ██║   ██║     ██╔══██║╚════██║    ██║   ██║╚════██║
     ██║  ██║   ██║   ███████╗██║  ██║███████║    ╚██████╔╝███████║
     ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝     ╚═════╝ ╚══════╝[/bold cyan]"""
    c.print(logo)

    banner_panel = Panel(
        Text.from_markup(
            "[bold white]ATLAS OS POLYGLOT SUBSYSTEM & SCRIPT ENGINE (v2.0-PRO)[/bold white]\n"
            "[cyan]• Inbuilt Code Editor:[/cyan] [bold yellow]Operator Editor[/bold yellow] (Type [bold green]nano <file>[/bold green] to edit)\n"
            "[cyan]• Virtual Storage:[/cyan] 2GB Dedicated EXT-OPFS Block Storage Device\n"
            "[cyan]• Multi-Engine Shell:[/cyan] Native .opsh, Linux/WSL .sh, PowerShell .ps1, Batch .bat\n"
            "[cyan]• Interactive Navigation:[/cyan] Tab Auto-Completion, History (↑/↓), Rich Diagnostics\n"
            "[dim]Type [bold white]help[/bold white] for command reference or [bold white]exit[/bold white] to leave.[/dim]"
        ),
        box=ROUNDED,
        border_style="bold cyan",
        title="[bold cyan]⚡ SYSTEM ONLINE ⚡[/bold cyan]",
        title_align="center",
    )
    c.print(banner_panel)

def main():
    import atexit

    engine = OperatorShellEngine()
    atexit.register(engine.close)
    print_banner()

    if len(sys.argv) > 1:
        bridge_mode = sys.argv[1] == "--bridge"
        raw_input_cmd = " ".join(sys.argv[2:] if bridge_mode else sys.argv[1:])
        tokens = shlex.split(raw_input_cmd)
        if bridge_mode and (not tokens or (not tokens[0].startswith("net.") and not tokens[0].startswith("drive."))):
            print("[OPSH BRIDGE] Only network and Drive commands are available through POW.")
            return
        target = tokens[0]
        # Append executed CLI commands to persistent storage
        engine.storage.append_command_history(raw_input_cmd)
        if target.endswith((".py", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".opsh")):
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