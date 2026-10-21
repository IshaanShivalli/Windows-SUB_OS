# Operator OS Requirements

## Supported development platform

- Windows 10/11
- An x86-64 host
- Git for source control
- At least 4 GB RAM recommended
- At least 5 GB free disk space; the storage image is sparse but can grow as it is used
- Network access for DNS and HTTP demonstration commands

The project is currently host-assisted and is not a bootable ISO or bare-metal operating system.

## Required runtimes

- Python 3.10 or newer
- Java JDK 17 or newer, with both `java` and `javac` on `PATH`
- Rust toolchain with Rust 1.85 or newer (`rustup`, `cargo`, and `rustc`); Rust 1.85+ is required by `edition = "2024"`
- MinGW-w64 `g++` with its `libwinpthread-1.dll` runtime for the C++ service/scheduler DLL

PowerShell, `cmd.exe`, and WSL/Bash are optional integrations used only when running matching host scripts through the polyglot shell. The Python build helper and launchers do not require PowerShell or batch files. The `ssh` client command requires the host OpenSSH client (`ssh.exe`) on `PATH`; the Atlas SSH server uses its Python dependency and does not require the Windows `sshd` service.

The Operator time service makes read-only NTP requests over UDP port 123 when the shell starts. It applies a measured offset to Operator's displayed time, but does not set or alter the Windows clock.

## Python dependencies

The shell and core subsystems primarily use the standard library. Build the native C++ process supervisor and scheduler with `python build.py` before using `srv.*` or `cron.*`. The `paramiko` dependency enables the Atlas SSH server. Install the packages listed in `requirements.txt`:

```console
python -m pip install -r requirements.txt
```

Google Drive is optional and requires the `rclone` executable on `PATH`.
Run `drive.mount` in Operator Shell. If no remote exists in the current user's
private rclone config, Operator OS starts `rclone config` for that user;
create a remote with storage type `drive` and complete the Google sign-in
through rclone's browser flow. Rclone manages the sign-in and tokens. The
selected remote mounts at `/Users/<user>/Google Drive`;
`drive.ls [remote-path]` lists remote files, and
`drive.download <file-id-or-path>` downloads a file on demand. Uploads and
automatic new/modified-file sync are disabled until a separate local
passphrase is set/unlocked; that write session expires after three hours.
Rclone configuration and credentials are stored in that user's private
Operator OS home directory, outside the repository.

The terminal code editor uses the installed `prompt_toolkit` and Pygments
dependencies. Language autocomplete is optional and activated per file type
by installing an editor extension package, for example
`pkg.install editor.lang.python`.

Powcurl requires a Windows x64 FFmpeg distribution with `ffplay.exe` on `PATH`
(or the `OPERATOR_FFPLAY` environment variable set to its full path). Hardware
decoding requires an FFplay build that supports `-hwaccel auto`; otherwise
playback continues with CPU decoding and reports that fallback. MP3, WAV, MP4,
AVI, and animated GIF playback depends on the codecs enabled in that FFmpeg
build. The Rust runtime links its C Win32 backend during the Cargo build.

## Installed games

The default `operator` user's `/Users/operator/home/Games` folder contains
fused Windows x64 LÖVE2D 11.5 game executables. Their licenses and credits are
in `Games/licenses`. Operator OS installs only the game `.exe` files, as
requested; those executables still require the matching LÖVE runtime DLLs
beside them. The complete runnable distributions (executables plus runtime
DLLs and notices) are kept in each project's `CS50 2D/<game>/dist` directory.
Installed game binaries and user OS storage are excluded from Git.

## Build inputs

The bootstrapper expects these runtime artifacts:

- `bin/operator_kernel.exe`
- `bin/kernel_guard.exe`
- Java classes under `runtime_java/bin`

If these artifacts are absent or stale, build the corresponding C, Rust, C++, and Java sources before running `boot.py`.

## Cargo / Rust setup

Install Rust through [rustup](https://rustup.rs/), then verify the toolchain:

```console
rustc --version
cargo --version
cargo check --manifest-path kernel/kernel_guard/Cargo.toml
cargo build --release --manifest-path kernel/kernel_guard/Cargo.toml
```

Use the Python project build helper for all native and managed components:

```console
python build.py --release
```

The build helper requires `javac`, `g++`, and `cargo` on `PATH`; it uses `gcc` for the optional C kernel demonstrations when available. Rust builds use the linker configured for the installed Rust toolchain.

The Rust executable is produced under `kernel/kernel_guard/target/release/`. Copy or configure the resulting executable as `bin/kernel_guard.exe` before booting:

```console
bin\kernel_guard.exe
```

## Java setup

Install a JDK, not only a Java Runtime Environment. Verify both tools:

```console
java --version
javac --version
```

Compile the Java runtime from the repository root:

```console
python build.py
java -cp runtime_java/bin operator.runtime.OperatorRuntime calculator
```

The build helper compiles the Java sources to `runtime_java/bin`; the bootstrapper runs the classes directly, so a JAR is not required.

## Recommended verification

```console
python -m compileall boot.py shell storage network
cargo check --manifest-path kernel/kernel_guard/Cargo.toml
```

The native and Java build commands depend on the compiler toolchain installed on the host; `python build.py` runs the configured build steps.
