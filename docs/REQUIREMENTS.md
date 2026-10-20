# Operator OS Requirements

## Supported development platform

- Windows 10/11, with PowerShell available
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
- A C compiler such as MSVC Build Tools or MinGW-w64
- A C++ compiler such as MSVC Build Tools or MinGW-w64

PowerShell, `cmd.exe`, and WSL/Bash are optional integrations used by the polyglot shell. They are not required for Python-only commands. The `ssh` client command requires the host OpenSSH client (`ssh.exe`) on `PATH`; the Atlas SSH server uses its Python dependency and does not require the Windows `sshd` service.

## Python dependencies

The shell and core subsystems primarily use the standard library. The `paramiko` dependency enables the Atlas SSH server; Google API packages enable the optional Drive integration. Install the packages listed in `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

Google Drive is optional. Install the Google API packages from
`requirements.txt`, configure a Google OAuth Desktop client ID with the Drive
API enabled, and run `drive.mount` in Operator Shell. The command asks for the
client ID and opens Google's sign-in page; it never requests the Google
account password. OAuth token exchange and refresh use the Operator network
stack. The authenticated account mounts at `/Users/<user>/Google Drive`.
Remote files are listed with `drive.ls` and downloaded on demand with
`drive.download <file-id>`. Uploads and automatic new/modified-file sync are
disabled until a separate local passphrase is set/unlocked; that write session
expires after three hours. Google OAuth tokens are stored in that user's
private Operator OS home directory, outside the repository.

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

```powershell
rustc --version
cargo --version
cargo check --manifest-path kernel/kernel_guard/Cargo.toml
cargo build --release --manifest-path kernel/kernel_guard/Cargo.toml
```

On Windows, use the project helper from PowerShell:

```powershell
.\build.ps1 -Release
```

This uses the Visual Studio C++ toolchain. MSYS2 GCC alone is not enough for the current setup because Cargo build scripts also need a linker for the active MSVC host toolchain. Do not use `C:\msys64\usr\bin\link.exe` as the linker for the MSVC target.

The Rust executable is produced under `kernel/kernel_guard/target/release/`. Copy or configure the resulting executable as `bin/kernel_guard.exe` before booting:

```powershell
bin\kernel_guard.exe
```

## Java setup

Install a JDK, not only a Java Runtime Environment. Verify both tools:

```powershell
java --version
javac --version
```

Compile the Java runtime from the repository root:

```powershell
New-Item -ItemType Directory -Force runtime_java/bin | Out-Null
javac -d runtime_java/bin runtime_java/src/operator/runtime/OperatorRuntime.java
java -cp runtime_java/bin operator.runtime.OperatorRuntime calculator
```

The bootstrapper currently runs the compiled classes directly from `runtime_java/bin`; a JAR is not required.

## Recommended verification

```powershell
python -m compileall boot.py shell storage network
cargo check --manifest-path kernel/kernel_guard/Cargo.toml
```

The native and Java build commands depend on the compiler toolchain installed on the host and should be added to a future build script or CI workflow.
