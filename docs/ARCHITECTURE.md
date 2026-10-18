# Operator OS Architecture Specification (WSL-Style Subsystem)

Operator OS is a multi-tier operating system architecture operating on host virtualization/subsystem abstractions (analogous to WSL/Mach/L4 microkernel architectures), orchestrating high-performance native kernels with cross-language userland components.

## Subsystem Architecture Overview

```
 ┌──────────────────────────────────────────────────────────────┐
 │                      Operator OS Ecosystem                   │
 ├──────────────────────────────────────────────────────────────┤
 │  [Browser Layer]         HTML5/CSS3 + PHP Backend Engine     │
 │  [App Runtime Layer]     Java Operator Virtual Machine (OVM) │
 │  [Shell Language Layer]  Python Polyglot Shell (Multi-Bridge)│
 │  [Settings & Packages]   SQL System Registry & Package Repo  │
 ├──────────────────────────────────────────────────────────────┤
 │  [GUI Toolkit & WM]      C++ / Win32 / Direct Display WM     │
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
   - `core_kernel.c`: Process control blocks (PCB), memory pools, round-robin scheduler ticks, system call dispatcher (`SYS_SPAWN`, `SYS_ALLOC`, `SYS_IPC_SEND`, `SYS_VFS_READ`, `SYS_VFS_WRITE`).
   - `scheduler.rs` / `vfs.rs`: Rust memory safety layer and memory manager providing crash-resilient driver abstraction and safe virtual filesystem mount tables.
2. **GUI & Window Manager (`/gui`) - C++**:
   - Native double-buffered window manager with custom widget toolkit (desktop panels, process monitor, command launch dock, window frames, taskbar).
3. **Custom Multi-Shell (`/shell`) - Python**:
   - Custom grammar & interpreter (`OperatorScript`) featuring native execution, seamless pass-through and pipes into Linux Bash/WSL, PowerShell, and Command Prompt (cmd.exe).
4. **App Runtime (`/runtime_java`) - Java**:
   - `OperatorApp` lifecycle manager and sandbox loader for Operator OS `.opk` / `.class` app execution.
5. **Database (`/db`) - SQL / SQLite**:
   - Unified schema for system configuration, environment variables, installed packages, user profiles, and permission ACLs.
6. **Online Web Browser (`/browser`) - PHP & HTML**:
   - Fast embedded browser server rendering modern HTML/CSS UI with PHP handling URL resolution, DOM caching, and proxy rendering.
