# Operator OS

Operator OS is an experimental, Windows/WSL-style operating-system subsystem prototype. It combines a small native kernel demo with a Python control plane, a polyglot shell, a Java application runtime, a C++ window manager, a virtual storage device, networking utilities, and a SQLite system registry.

This repository is a development prototype, not yet a bootable standalone operating-system image. The native components currently run as host processes and the networking/storage layers provide simulated or host-assisted services.

## Features

- Python bootstrap sequence in [`boot.py`](boot.py)
- C kernel demonstration in [`kernel/core_kernel.c`](kernel/core_kernel.c), with a public syscall dispatcher, priority-aware aging round-robin scheduling, and owner-checked memory allocation/release
- Rust kernel safety/guard component in [`kernel/kernel_guard`](kernel/kernel_guard), with bounded page allocation and a stateful driver/device registry
- Rust/C `powcurl` media-script runtime in [`powcurl`](powcurl), using FFplay for a separate playback window and Windows-selected hardware decoding when supported
- Polyglot shell for `.opsh`, Bash, PowerShell, and CMD scripts in [`shell/opshell.py`](shell/opshell.py)
- Terminal code editor in [`apps/nano.py`](apps/nano.py), with syntax highlighting and optional per-language autocomplete extensions installable through `pkg.install`
- Simulated 2 GB sparse EXT-OPFS storage image in [`storage`](storage)
- Host-assisted DNS, TCP probing, routing, and HTTP fetching in [`network/net_stack.py`](network/net_stack.py)
- Java Operator Virtual Machine examples in [`runtime_java`](runtime_java)
- SQLite system registry and package catalog in [`db`](db)

## Requirements

See [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for the complete list. The minimum runtime is Python 3.10+. The bootstrapper also expects the prebuilt native binaries and Java runtime to be available.

Rust 1.85+ is required because the Cargo project uses Rust edition 2024. Java requires a JDK 17+ installation with both `java` and `javac` available.

## Quick start

From the repository root on Windows:

```powershell
python boot.py
```

The bootstrapper initializes the SQLite registry and storage image, checks the network layer, starts the native and Java demonstrations, and launches the Operator shell.
Boot output is concise by default. Pass `--verbose` to `boot.py` to show diagnostics from the kernel and runtime startup components. The `atlas.cmd` launcher keeps its terminal open after shell exit or startup failure so the message remains visible.

To use the shell by itself:

```powershell
python shell/opshell.py
```

Build the Rust kernel guard and powcurl runtime into `bin`:

```powershell
.\build.ps1 -Release
```

Useful commands include `help`, `sys.probe`, `gpu.probe`, `mem`, `storage.inspect`, `net.ifconfig`, `pkg.list`, and `proc.list`. `gpu.probe` reads the host's GPU and driver status; `mem` reports live host RAM and swap statistics.

The shell suggests command names as you type, completes privileged subcommands after multiple words (for example, `passd sh`), and completes virtual-storage paths in command arguments. Previously entered full commands are also suggested from the current session's history.

The first `passd <command>` use for a non-root account prompts you to create and confirm a separate passd password, then runs the command. You can instead initialize it with `passd.setup`; use that command again to change the passd password after authenticating with the existing one. Passwords must be at least eight characters, are stored only as salted PBKDF2 hashes, and a successful authentication is cached for five minutes. This is separate from your Operator account password.

SSH client connections use the host's OpenSSH `ssh` executable: `ssh <user@host>`. Atlas's SSH server is separate from Windows `sshd`; it accepts Ed25519 public keys for existing Atlas users and exposes a restricted Atlas command set without host PowerShell/CMD access. File commands are confined to the authenticated user's virtual home directory. Generate an Ed25519 key with `ssh-keygen -t ed25519`, then enroll its `.pub` file with `ssh.key.add <user> <public-key-file>`; the file may be in Atlas virtual storage or supplied by its absolute host path. Use `ssh.key.list [user]` and `ssh.key.remove <user> <fingerprint>` to manage enrolled keys. Start, inspect, and stop the server with `ssh.server start`, `ssh.server status`, and `ssh.server stop`. It listens on `127.0.0.1:2222` by default; explicitly use `ssh.server start --host <IPv4> --port <port>` to listen on another interface. For example, connect locally with `ssh -p 2222 operator@127.0.0.1`. Only expose it on a trusted network, since host firewall and network policy still apply. Atlas generates its server host key and stores it with SSH key data under private Operator OS storage. The server remains active only while the Atlas shell process is running.

Open the code editor with `nano <file>`. Completion suggestions are enabled only for a matching installed language extension; for example, install Python completion with `pkg.install editor.lang.python`. Other available extensions include `editor.lang.javascript`, `editor.lang.typescript`, `editor.lang.rust`, `editor.lang.c`, `editor.lang.cpp`, `editor.lang.java`, `editor.lang.powershell`, `editor.lang.batch` (`.bat` and `.cmd`), and `editor.lang.powcurl` (`.powcurl`). Install the extensions you need with `pkg.install <package-id>`. Without a matching extension, the editor still edits and syntax-highlights the file but does not suggest language keywords.

Powcurl runs `.powcurl` media scripts through the Rust/C runtime. Install a Windows FFmpeg build that includes `ffplay.exe`, then build Operator OS with `.\build.ps1 -Release`. `powcurl <script.powcurl>` opens a separate player window for MP3, WAV, MP4, AVI, and animated GIF files supported by the installed FFmpeg codecs. Windows chooses the GPU for the player; hardware decoding is used when the FFplay build supports it, otherwise powcurl reports CPU fallback. Seeking uses 10-second steps. A script can use `open "file.mp4"`, `volume 70`, `play`, `pause`, `resume`, `seek -10`, `wait`, and `stop`; relative media paths are resolved beside the script. Set `OPERATOR_FFPLAY` if `ffplay.exe` is not on `PATH`.

Connect Google Drive with `drive.mount`. Operator OS asks for an OAuth Client ID, opens Google's sign-in page, and sends token requests through the Operator networking layer. Create a Desktop OAuth client ID in Google Cloud and enable the Google Drive API first; Operator OS never asks for or stores your Google account password. The account is mounted at `/Users/<user>/Google Drive`. `drive.ls [folder-id]` lists cloud files; `drive.download <file-id>` downloads one file on demand. Writes are locked by default: run `drive.write.setup` to set a separate local passphrase, or `drive.write.unlock` to unlock an existing one. While unlocked, new and modified files in the local Drive folder upload automatically; the write unlock expires after three hours and must be renewed with the passphrase. `drive.upload <path>` performs an explicit upload while unlocked. The OAuth token is stored under the current user's private Operator OS home, not in the source tree.

The seven LÖVE2D game executables are copied into the default Operator user's virtual `/Users/operator/home/Games` folder, with game and LÖVE license notices in its `licenses` subfolder. The original projects remain in `CS50 2D`. Per request, only `.exe` game files (not LÖVE runtime DLLs) are installed into Operator OS; each game therefore still needs the matching LÖVE 11.5 runtime DLLs beside it to launch. Complete portable distributions, including those DLLs, remain under each source project's `dist` folder.

Language extensions are package manifests in `packages/repo` with an `editor_extension` object containing `language`, `file_extensions`, and `completions`. Add a package manifest following the existing `editor.lang.*` examples and install its package ID to activate its completion list.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — subsystem design and module responsibilities
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — runtime, build, and platform requirements
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — recommended additions and implementation order

## Development notes

Generated files such as the SQLite database, sparse storage image, command journal, Python caches, Java class files, and native build output should not be committed. The repository `.gitignore` reflects this policy.

## Safety and scope

The shell can invoke host shells and network operations. Run it in a development environment and review scripts before executing them. The current storage image is a simulation and should not be treated as a production filesystem.

## License

No license has been selected yet. Add a `LICENSE` file before distributing the project.
