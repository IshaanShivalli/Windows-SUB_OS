# Atlas OS v3 — Requirements and Support

Atlas OS v3 is the final project release; no further feature releases are planned. These requirements describe the final published source and its host-run CLI subsystem. They do not describe a bootable or bare-metal operating system.

## Intended host platforms

- Windows 10/11, macOS, or Linux
- Python 3.10 or newer
- Git is needed only to clone the source; it is not needed to install an extracted archive
- At least 4 GB RAM recommended
- Free disk space for the application, its Python environment, dependencies, and user data; the 2 GB image is sparse but can grow as files are written
- Network access for DNS and HTTP demonstration commands

Atlas OS is a host-run subsystem, not a bootable ISO, virtual machine, or bare-metal operating system. The portable installer does not need administrator privileges or native build tools. It creates an application copy and Python virtual environment in the current user's application-data directory, then allocates a separate virtual-storage directory and sparse 2 GB image. Installation downloads Python dependencies, so internet access is needed unless those dependencies are already provided and installation is run with `--skip-dependencies`.

Install from the extracted project directory with:

```console
python install/installer.py
```

Use `python3 install/installer.py` if that is the system's Python 3 command. The installer prints the exact launcher path when complete. It uses Windows, macOS, and Linux user-data conventions. End-to-end installation and launch have been verified on Windows only; macOS and Linux have not been validated on their native hosts and should be treated as unverified.

## Required runtimes

- Python 3.10 or newer is required to install and run the portable Python shell.
- Java JDK 17+, Rust 1.85+, and C/C++ compilers are optional development requirements for building demonstrations. The current complete native build is Windows-specific and is not needed to install or run the Python shell.

PowerShell, `cmd.exe`, and Bash are optional integrations used only when running matching host scripts through the polyglot shell. Windows Plug and Play device discovery is Windows-only. The `ssh` client command requires the host OpenSSH client on `PATH`; the Atlas SSH server is implemented in Python and does not require the host's SSH server service.

The Atlas time service makes read-only NTP requests over UDP port 123 when the shell starts. It applies a measured offset to the displayed time, but does not set or alter the host system clock.

## Python dependencies

The installer creates an isolated Python environment and installs the packages listed in `requirements.txt`. The native C++ process supervisor/scheduler features are optional and require a compatible built runtime; they are not prerequisites for using the portable shell.

```console
python -m pip install -r requirements.txt
```

Google Drive is optional and requires `rclone`. The normal development runtime
looks for `rclone` on `PATH`. A Windows developer package can include a local executable
using `python build.py --package-runtime --rclone-executable <path-to-rclone.exe>`;
Operator OS searches the staged copy before reporting rclone unavailable.
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

Powcurl requires an FFmpeg distribution with `ffplay` on `PATH`
(or the `OPERATOR_FFPLAY` environment variable set to its full path). Hardware
decoding requires an FFplay build that supports `-hwaccel auto`; otherwise
playback continues with CPU decoding and reports that fallback. MP3, WAV, MP4,
AVI, and animated GIF playback depends on the codecs enabled in that FFmpeg
build. The Rust runtime links its C Win32 backend during the Cargo build.

## Optional game files

The Windows development checkout may contain fused Windows x64 LÖVE2D 11.5
game executables and associated notices. The portable installer excludes host
executables and build outputs; it does not install those games. Game launch
support and GPU preference integration are host/platform-dependent. Only
redistribute game files when their licenses permit it.

## Packaged runtime

`python build.py --release --package-runtime --rclone-executable <path-to-rclone.exe>`
builds the native and managed components and stages them under
`storage/operator_os_root/System`, grouped by their existing subsystem
directories and recorded in `runtime_manifest.json`. Python modules are
compiled to bytecode and their source files are omitted from the staged
runtime. The package requires the same exact Python version used to build it,
plus the host's installed Python dependencies; it does not include a Python
interpreter. `python boot.py` launches the staged runtime when present, and
`python boot.py --source` runs the repository checkout.

The 2 GB image remains a sparse simulation, not a mounted filesystem. Runtime
files live in the separate directory-backed virtual storage tree, which is
shared with user data. Storage usage reflects that tree's file sizes, but no
hard capacity limit is enforced; the 2 GB figure is a logical capacity, not a
disk reservation or enforced quota.

## Build inputs

Optional developer boot components may use these runtime artifacts:

- `bin/operator_kernel.exe`
- `bin/kernel_guard.exe`
- Java classes under `runtime_java/bin`

If these artifacts are absent or stale, their optional demonstrations may not
run. Their absence does not prevent using the portable Python shell.

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

The Rust executable is produced under `kernel/kernel_guard/target/release/`.
Native build and execution steps below are optional and reflect the Windows
development setup; they are not required for installation:

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

## Final release verification

```console
python -m pytest -q
```

The Python test suite and Windows installer smoke test are the verified checks
for this final source state. Other operating systems and optional native
toolchains were not verified as complete release targets.
