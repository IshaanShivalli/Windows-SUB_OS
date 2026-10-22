# Atlas OS v3 — Implemented Architecture

Atlas OS v3 is a host-run CLI subsystem prototype, not an implementation of WSL, Mach, L4, or a bare-metal operating system. Its Python shell and services execute as host processes. The C and Rust components are educational/native demonstrations; they do not boot the computer, provide a real kernel boundary, or replace host drivers. This is the final project release, with no further feature releases planned.

Hardware telemetry is host-backed: on Windows, GPU inventory and driver health come from Windows CIM/WMI (and NVIDIA telemetry is queried from `nvidia-smi` when available); physical RAM is read from the host memory API and page-file usage from Windows CIM. `device.list` reads present USB, display/monitor, and audio devices plus their installed host driver information from Windows Plug and Play. This reports audio/display adapters and endpoints, not guaranteed physical jack/cable insertion state. Atlas OS does not install or replace host kernel drivers. Host telemetry coverage varies by operating system and hardware.

## Subsystem Architecture Overview

```
 ┌──────────────────────────────────────────────────────────────┐
 │                       Atlas OS v3 Subsystem                   │
 ├──────────────────────────────────────────────────────────────┤
 │  [App Runtime Layer]     Java Operator Virtual Machine (OVM) │
 │  [Shell Language Layer]  Python Polyglot Shell (Multi-Bridge)│
 │  [Settings & Packages]   SQL System Registry & Package Repo  │
 ├──────────────────────────────────────────────────────────────┤
 ├──────────────────────────────────────────────────────────────┤
 │  [Native Demonstrations] C and Rust example components      │
 │                          - Scheduler and memory examples     │
 │                          - Simulated device/driver registry  │
 │                          - Not a bootable host kernel        │
 └──────────────────────────────────────────────────────────────┘
```

## Implemented Components

1. **Native demonstrations (`/kernel`) - C & Rust**:
   - `core_kernel.c` / `operator_syscall.h`: Demonstration process control blocks (PCB), syscall-style dispatcher, priority-aware aging round-robin scheduler, process-owned memory pools, VFS nodes, and IPC. These are not host-kernel syscalls or a booted kernel.
   - `kernel_guard/src/main.rs`: Rust page-allocation and simulated device-registry demonstration. It does not manage physical host memory or install host drivers.
2. **Custom Multi-Shell (`/shell`) - Python**:
   - Custom grammar & interpreter (`OperatorScript`) featuring native execution, seamless pass-through and pipes into Linux Bash/WSL, PowerShell, and Command Prompt (cmd.exe).
   - `apps/nano.py` provides the terminal code editor; installed `editor.lang.*` packages provide opt-in, file-extension-matched completion lists. Completion generation is on-demand and redraw scheduling is configured for immediate shortcut feedback.
   - `core/services/time_service.py` reports local time and samples NTP servers in the background; it applies the measured offset to Operator's display only and never adjusts the host clock.
   - `core/process/app_manager.py` runs manifest app commands without a shell, inherits console output, and reports completed or failed launches instead of leaving stale running states.
   - `games.list` enumerates game executables in the active user's virtual `home/Games` directory.
   - `core/process/game_manager.py` stages missing LÖVE runtime libraries from the local game distributions, launches selected games in their install directory, and requests Windows' per-application high-performance GPU preference through the current user's graphics-preference registry key.
   - `editor.lang.vyn` adds `.vyn` syntax highlighting and completion to the terminal editor; `vyn.run` executes files using the configured local Vyn interpreter.
   - `powcurl/` contains a Rust media-script parser/runtime and a C Win32 process/control backend. FFplay decodes and renders in its own window, using Windows-selected hardware decoding when available with an explicit CPU fallback.
   - `integrations/rclone_drive.py` uses the user's isolated rclone configuration for Google Drive authentication and file transfers, mounts each selected remote under its user's `Google Drive` directory, and keeps automatic local uploads behind a three-hour passphrase session.
   - `network/ssh_service.py` provides an Atlas-only SSH server with Ed25519 key authentication and an explicit command allowlist; its default listener is loopback-only, while the `ssh` client bridges to the host OpenSSH executable.
   - `core/services/service_runtime.cpp` implements native Windows process supervision (restart policy, TCP health probes, persistent logs) and the interval scheduler; persisted services start with the runtime, and `core/services/service_manager.py` is the narrow shell/FFI adapter. Scheduled Atlas actions are allowlisted and run through the authenticated user's shell context.
   - The portable installer excludes game executables. The Windows development checkout may include fused LÖVE2D games and license notices in the default user's virtual `home/Games` directory.
3. **App Runtime (`/runtime_java`) - Java**:
   - `OperatorApp` lifecycle manager and sandbox loader for Operator OS `.opk` / `.class` app execution.
4. **Database (`/db`) - SQL / SQLite**:
   - Unified schema for system configuration, environment variables, installed packages, user profiles, and permission ACLs.
