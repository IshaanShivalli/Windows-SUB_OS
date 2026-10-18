# Operator OS

Operator OS is an experimental, Windows/WSL-style operating-system subsystem prototype. It combines a small native kernel demo with a Python control plane, a polyglot shell, a Java application runtime, a C++ window manager, a virtual storage device, networking utilities, and a SQLite system registry.

This repository is a development prototype, not yet a bootable standalone operating-system image. The native components currently run as host processes and the networking/storage layers provide simulated or host-assisted services.

## Features

- Python bootstrap sequence in [`boot.py`](boot.py)
- C kernel demonstration in [`kernel/core_kernel.c`](kernel/core_kernel.c)
- Rust kernel safety/guard component in [`kernel/kernel_guard`](kernel/kernel_guard)
- Polyglot shell for `.opsh`, Bash, PowerShell, and CMD scripts in [`shell/opshell.py`](shell/opshell.py)
- Simulated 2 GB sparse EXT-OPFS storage image in [`storage`](storage)
- Host-assisted DNS, TCP probing, routing, and HTTP fetching in [`network/net_stack.py`](network/net_stack.py)
- Java Operator Virtual Machine examples in [`runtime_java`](runtime_java)
- C++ window manager sources in [`gui`](gui)
- SQLite system registry and package catalog in [`db`](db)
- Browser surface in [`browser`](browser)

## Requirements

See [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for the complete list. The minimum runtime is Python 3.10+. The bootstrapper also expects the prebuilt native binaries and Java runtime to be available.

Rust 1.85+ is required because the Cargo project uses Rust edition 2024. Java requires a JDK 17+ installation with both `java` and `javac` available.

## Quick start

From the repository root on Windows:

```powershell
python boot.py
```

The bootstrapper initializes the SQLite registry and storage image, checks the network layer, starts the native and Java demonstrations, and launches the Operator shell.

To use the shell by itself:

```powershell
python shell/opshell.py
```

Build the Rust browser host and copy it into `bin`:

```powershell
.\build.ps1 -Release
```

Useful commands include `help`, `sys.probe`, `storage.inspect`, `net.ifconfig`, `pkg.list`, and `proc.list`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — subsystem design and module responsibilities
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — runtime, build, and platform requirements
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — recommended additions and implementation order
- [`docs/UI.md`](docs/UI.md) — desktop startup, controls, file manager, and Google Drive behavior

## Development notes

Generated files such as the SQLite database, sparse storage image, command journal, Python caches, Java class files, and native build output should not be committed. The repository `.gitignore` reflects this policy.

## Safety and scope

The shell can invoke host shells and network operations. Run it in a development environment and review scripts before executing them. The current storage image is a simulation and should not be treated as a production filesystem.

## License

No license has been selected yet. Add a `LICENSE` file before distributing the project.
