# Operator OS Roadmap

The project already has a strong subsystem demo. The following additions would make it more useful, safer, and closer to an operating system.

## Highest priority

1. **Reproducible build system** — add a PowerShell build script and CI workflow that compile C, C++, Rust, and Java components into a clean `build/` directory.
2. **Tests** — add Python unit tests for storage, networking, shell parsing, database initialization, and boot failure handling.
3. **Configuration and logging** — replace hard-coded interfaces, paths, commands, and version values with a typed config file and structured logs.
4. **Process manager** — implement process IDs, lifecycle states, signals, exit codes, resource limits, and a real process table shared by the shell and GUI.
5. **Permission model** — enforce users, roles, ACLs, and sandbox boundaries instead of only storing them in SQLite.

## Desktop UI follow-ups

- Replace the remaining compatibility compositor code with the modular `gui/ui/` implementation
- Add true per-application resize handles and snap layouts
- Replace GUI shell output redirection with a persistent shell service and IPC stream
- Add clickable File Manager navigation and safe copy/move/delete operations
- Add Google Drive sync status, conflict handling, and offline placeholders

## Core OS capabilities

- Real syscall boundary between user programs and the kernel
- Virtual memory, page permissions, and memory accounting
- IPC primitives and service discovery
- VFS abstraction with mounts, file descriptors, permissions, and recovery
- Device abstraction and driver loading
- Scheduler priorities, timers, sleep, and synchronization primitives
- Crash reports, watchdogs, and safe-mode boot

## User experience

- Persistent shell history search, completion, aliases, and pipelines
- Package manager with signed manifests, dependency resolution, uninstall, and rollback
- Settings service and a consistent system event bus
- Notifications, clipboard, audio, input, display scaling, and accessibility support
- Application manifest format with versioning, permissions, icons, and update channels

## Networking and security

- Replace simulated interfaces/routes with an explicit host adapter backend
- TLS certificate validation, URL allowlists, and request size limits
- Firewall policy and per-process network permissions
- Secrets/key store and encrypted user data
- Signed releases and reproducible artifact checksums

## Later milestones

- Virtual machine or emulator boot target
- Installer and recovery image
- Snapshot/restore support for the virtual disk
- Remote administration API with authentication and audit logs
- Performance benchmarks and tracing dashboard
