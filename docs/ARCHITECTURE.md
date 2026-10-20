# Operator OS Architecture Specification (WSL-Style Subsystem)

Operator OS is a multi-tier operating system architecture operating on host virtualization/subsystem abstractions (analogous to WSL/Mach/L4 microkernel architectures), orchestrating high-performance native kernels with cross-language userland components.

Hardware telemetry is host-backed: on Windows, GPU inventory and driver health come from Windows CIM/WMI (and NVIDIA compute telemetry is queried from `nvidia-smi` when available); physical RAM is read from the host memory API and page-file usage from Windows CIM. Operator OS is not a bare-metal OS and does not install or replace the host's GPU driver.

## Subsystem Architecture Overview

```
 ┌──────────────────────────────────────────────────────────────┐
 │                      Operator OS Ecosystem                   │
 ├──────────────────────────────────────────────────────────────┤
 │  [App Runtime Layer]     Java Operator Virtual Machine (OVM) │
 │  [Shell Language Layer]  Python Polyglot Shell (Multi-Bridge)│
 │  [Settings & Packages]   SQL System Registry & Package Repo  │
 ├──────────────────────────────────────────────────────────────┤
 ├──────────────────────────────────────────────────────────────┤
 │  [Microkernel Core]      C & Rust Subsystem Engine           │
 │                          - Memory Manager (Buddy / Slab)     │
 │                          - Preemptive Round-Robin Scheduler  │
 │                          - Virtual Filesystem (VFS) & Mounts │
 │                          - IPC Driver Bus (Named Pipes/Pty)  │
 └──────────────────────────────────────────────────────────────┘
```

## Language Roles & Module Mapping

1. **Kernel (`/kernel`) - C & Rust**:
   - `core_kernel.c` / `operator_syscall.h`: Process control blocks (PCB), validated syscall dispatcher, priority-aware aging round-robin scheduler, process-owned memory pools, VFS nodes, and IPC.
   - `kernel_guard/src/main.rs`: Rust page supervisor with bounded allocation/release and a stateful driver bus that validates registrations and rejects I/O to inactive devices.
2. **Custom Multi-Shell (`/shell`) - Python**:
   - Custom grammar & interpreter (`OperatorScript`) featuring native execution, seamless pass-through and pipes into Linux Bash/WSL, PowerShell, and Command Prompt (cmd.exe).
   - `apps/nano.py` provides the terminal code editor; installed `editor.lang.*` packages provide opt-in, file-extension-matched completion lists.
   - `powcurl/` contains a Rust media-script parser/runtime and a C Win32 process/control backend. FFplay decodes and renders in its own window, using Windows-selected hardware decoding when available with an explicit CPU fallback.
   - `integrations/google_drive.py` uses PKCE OAuth, routes token exchange/refresh through `OperatorNetworkStack`, mounts each authenticated account under its user's `Google Drive` directory, and keeps auto-upload behind a three-hour local passphrase session.
   - `network/ssh_service.py` provides an Atlas-only SSH server with Ed25519 key authentication and an explicit command allowlist; its default listener is loopback-only, while the `ssh` client bridges to the host OpenSSH executable.
   - Fused LÖVE2D game executables are installed in the default user's virtual `home/Games` directory; game data and LÖVE license notices are kept alongside in `Games/licenses`.
3. **App Runtime (`/runtime_java`) - Java**:
   - `OperatorApp` lifecycle manager and sandbox loader for Operator OS `.opk` / `.class` app execution.
4. **Database (`/db`) - SQL / SQLite**:
   - Unified schema for system configuration, environment variables, installed packages, user profiles, and permission ACLs.
