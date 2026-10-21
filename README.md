# Operator OS

Operator OS is an experimental, Windows/WSL-style operating-system subsystem prototype. It combines a small native kernel demo with a Python control plane, a polyglot shell, a Java application runtime, a C++ window manager, a virtual storage device, networking utilities, and a SQLite system registry.

This repository is a development prototype, not yet a bootable standalone operating-system image. The native components currently run as host processes and the networking/storage layers provide simulated or host-assisted services.

## Features

- Python bootstrap sequence in [`boot.py`](boot.py)
- C kernel demonstration in [`kernel/core_kernel.c`](kernel/core_kernel.c), with a public syscall dispatcher, priority-aware aging round-robin scheduling, and owner-checked memory allocation/release
- Rust kernel safety/guard component in [`kernel/kernel_guard`](kernel/kernel_guard), with bounded page allocation and a stateful driver/device registry
- Rust/C `powcurl` media-script runtime in [`powcurl`](powcurl), using FFplay for a separate playback window and Windows-selected hardware decoding when supported
- Polyglot shell for Python, `.opsh`, Bash, PowerShell, and CMD scripts in [`shell/opshell.py`](shell/opshell.py)
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

```console
python boot.py
```

The bootstrapper initializes the SQLite registry and storage image, checks the network layer, starts the native and Java demonstrations, and launches the Operator shell.
Boot output is concise by default. Pass `--verbose` to `boot.py` to show diagnostics from the kernel and runtime startup components. Run `python atlas.py` to open Operator OS in a separate console that remains open after shell exit or startup failure.

To use the shell by itself:

```console
python shell/opshell.py
```

Build the native, Java, and Rust components into `bin`:

```console
python build.py --release
```

Useful commands include `help`, `sys.probe`, `gpu.probe`, `mem`, `storage.inspect`, `net.ifconfig`, `net.speed`, `pkg.list`, and `proc.list`. `gpu.probe` reads the host's GPU and driver status; `mem` reports live host RAM and swap statistics. `net.speed` continuously measures download and upload throughput using 1 MB samples against Cloudflare's public speed-test endpoint, shows current and cumulative average Mbps in a live CLI panel, and stops with Ctrl+C. Each cycle uploads and downloads about 1 MB; it requires internet access.
Use `help <command>` for detailed feature-specific instructions, or `help menu` to browse help for every Operator-specific command. General shell commands remain available in the main `help` reference.

`time` reports the local clock and applies the most recent read-only NTP offset when synchronization is available. The time service starts with Operator Shell, samples public NTP servers in the background, and can be inspected or manually resynchronized with `time.service status` and `time.service sync [server]`. It does not change the Windows system clock.

The shell suggests command names as you type, completes privileged subcommands after multiple words (for example, `passd sh`), and completes virtual-storage paths in command arguments. Previously entered full commands are also suggested from the current session's history.

Open the graphical office suite with `office`. It provides a document browser and GUI editors for text documents, presentations, and database spreadsheets. `office.writer`, `office.sheet`, or `office.slides` opens the matching editor directly; append a file path to open that file. Files are stored in the active user's Operator home under `Documents`. Writer uses `.opdoc`, `.md`, or `.txt`; presentations use `.opsdeck`; spreadsheets use `.opsheet`, a SQLite database containing worksheet dimensions and cell values (not CSV). Double-click a spreadsheet cell to edit it; changes persist directly to its database.

Separate commands with `;` (`cd ..; cd Games`). Single and double quotes preserve spaces and semicolons inside an argument, and backslashes are preserved in Windows paths such as `"C:\Users\Name\Games"`; use `\` to escape a quote, space, or semicolon when needed.

The first `passd <command>` use for a non-root account prompts you to create and confirm a separate passd password, then runs the command. You can instead initialize it with `passd.setup`; use that command again to change the passd password after authenticating with the existing one. Passwords must be at least eight characters, are stored only as salted PBKDF2 hashes, and a successful authentication is cached for five minutes. This is separate from your Operator account password.

Scheduled jobs and managed services run in the native C++ runtime. Build it with `python build.py` before using `cron.*` or `srv.*`; its definitions, schedules, and logs are stored under the private Operator OS storage tree. Example jobs: `passd cron.add daily-backup 86400 backup.create daily` and `passd cron.add temp-cleanup 3600 storage.cleanup 7`. Jobs support only restore-point creation, age-limited cleanup under `/tmp`, `echo`, or validated `.opsh` scripts from the owner's virtual home. The minimum interval is 10 seconds. Use `cron.list`, `cron.logs <name>`, and `cron.remove <name>` to inspect/manage them. Jobs run only while Operator Shell is open; overdue jobs run when its C++ scheduler starts. Restore-point creation and shared `/tmp` cleanup require root.

Register and manage a native process as a service with `passd srv.register web --health process -- C:/path/to/server.exe --port 8080`. Registration starts it immediately; saved service definitions are started again when Operator Shell opens. Restart defaults to `always` (capped exponential backoff); `on-failure` and `no` are available as explicit overrides. Health checks support `process` or `tcp:<host>:<port>` and restart a service after 15 seconds of failed checks. Use `passd srv.list`, `passd srv.logs web`, `passd srv.restart web`, `passd srv.stop web`, and `passd srv.remove web` to inspect/control services. Managed service processes run only while Operator Shell is open and are stopped when it exits.

SSH client connections use the host's OpenSSH `ssh` executable: `ssh <user@host>`. Atlas's SSH server is separate from Windows `sshd`; it accepts Ed25519 public keys for existing Atlas users and exposes a restricted Atlas command set without host PowerShell/CMD access. File commands are confined to the authenticated user's virtual home directory. Generate an Ed25519 key with `ssh-keygen -t ed25519`, then enroll its `.pub` file with `ssh.key.add <user> <public-key-file>`; the file may be in Atlas virtual storage or supplied by its absolute host path. Use `ssh.key.list [user]` and `ssh.key.remove <user> <fingerprint>` to manage enrolled keys. Start, inspect, and stop the server with `ssh.server start`, `ssh.server status`, and `ssh.server stop`. It listens on `127.0.0.1:2222` by default; explicitly use `ssh.server start --host <IPv4> --port <port>` to listen on another interface. For example, connect locally with `ssh -p 2222 operator@127.0.0.1`. Only expose it on a trusted network, since host firewall and network policy still apply. Atlas generates its server host key and stores it with SSH key data under private Operator OS storage. The server remains active only while the Atlas shell process is running.

Open the code editor with `nano <file>`. Install the language packs with `pkg.install editor.lang.python` and `pkg.install editor.lang.vyn`. Python gets Pygments syntax highlighting, completions for keywords, builtins, standard-library modules, current-file names, and known built-in object members, plus live syntax diagnostics while editing. Use `python.check <file.py>` to check syntax without running the file and `python.run <file.py> [args...]` to execute it. Vyn gets dedicated syntax highlighting, Vyn keywords/builtins and current-file identifier completions; use `vyn.run <file.vyn>` to execute through the supplied Vyn interpreter and see its runtime diagnostics. Vyn has no standalone parser/language-server API, so its pack does not claim static diagnostics or Python-level semantic analysis. Other available extensions include `editor.lang.javascript`, `editor.lang.typescript`, `editor.lang.rust`, `editor.lang.c`, `editor.lang.cpp`, `editor.lang.java`, `editor.lang.powershell`, `editor.lang.batch` (`.bat` and `.cmd`), and `editor.lang.powcurl` (`.powcurl`). Completion suggestions appear while typing and Tab requests or accepts a completion. By default the Vyn interpreter is loaded from `../lua/vyn/vyn` relative to the project directory; set `OPERATOR_VYN_HOME` to the directory containing `main.py` to use another Vyn checkout.

Launch manifest apps with `app.launch <app-name-or-id>` and inspect installed apps with `app.list`. These current Java apps are console demonstrations and print their output in the shell. `games.list` lists executable games installed in the active user's `Games` directory.

Powcurl runs `.powcurl` media scripts through the Rust/C runtime. Install a Windows FFmpeg build that includes `ffplay.exe`, then build Operator OS with `python build.py --release`. `powcurl <script.powcurl>` opens a separate player window for MP3, WAV, MP4, AVI, and animated GIF files supported by the installed FFmpeg codecs. Windows chooses the GPU for the player; hardware decoding is used when the FFplay build supports it, otherwise powcurl reports CPU fallback. Seeking uses 10-second steps. A script can use `open "file.mp4"`, `volume 70`, `play`, `pause`, `resume`, `seek -10`, `wait`, and `stop`; relative media paths are resolved beside the script. Powcurl currently requires a local media file; direct web URLs are not supported. Set `OPERATOR_FFPLAY` if `ffplay.exe` is not on `PATH`.

Connect Google Drive through rclone. Install the `rclone` executable, then run `drive.mount`. If the current Operator user has no configured rclone remote, `drive.mount` starts `rclone config` in that user's private config location; create a remote with the Google Drive (`drive`) storage type and complete rclone's browser sign-in. Operator OS does not ask for a Google OAuth Client ID or Google account password; rclone manages the sign-in and tokens. The chosen remote is mounted at `/Users/<user>/Google Drive`. `drive.ls [remote-path]` lists remote files; `drive.download <file-id-or-path>` downloads a file on demand. Writes are locked by default: run `drive.write.setup` to set a separate local passphrase, or `drive.write.unlock` to unlock an existing one. While unlocked, new and modified files in the local Drive folder upload automatically; the write unlock expires after three hours and must be renewed with the passphrase. `drive.upload <path>` performs an explicit upload while unlocked. Rclone configuration and credentials are stored under the current user's private Operator OS home, not in the source tree.

The seven LÖVE2D game executables are copied into the default Operator user's virtual `/Users/operator/home/Games` folder, with game and LÖVE license notices in its `licenses` subfolder. Run `games.list` to see installed games and `games.launch "MATCH 3"` (or `game.launch PONG`) to play one. On first launch, missing LÖVE runtime DLLs are copied from the corresponding `CS50 2D/<game>/dist` distribution when available. On Windows, the launcher requests the per-application high-performance GPU preference; the selected GPU remains under Windows and graphics-driver control, so the OS may still choose an adapter. The original game distributions remain in `CS50 2D`.

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
