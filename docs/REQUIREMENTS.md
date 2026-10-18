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
- Microsoft Edge WebView2 Runtime, required by the embedded Rust browser window
- A C compiler such as MSVC Build Tools or MinGW-w64
- A C++ compiler such as MSVC Build Tools or MinGW-w64
- PHP 8 or newer only when serving the browser PHP backend

PowerShell, `cmd.exe`, and WSL/Bash are optional integrations used by the polyglot shell. They are not required for Python-only commands.

## Python dependencies

The current Python implementation uses only the standard library. Install the requirements file with:

```powershell
python -m pip install -r requirements.txt
```

No third-party package is currently required.

Google Drive is optional. Install the Google packages from `requirements.txt`,
then run `drive.connect` in Operator Shell. Boot never authenticates or asks
for credentials. The runtime command asks for the OAuth client JSON path,
opens the Google authorization page, and creates only `Operator OS/Pictures`,
`Operator OS/Videos`, and `Operator OS/Docs`.

## Build inputs

The bootstrapper expects these runtime artifacts:

- `bin/operator_kernel.exe`
- `bin/kernel_guard.exe`
- `bin/operator_wm.exe`
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

The Rust executable is produced under `kernel/kernel_guard/target/release/`. Copy or configure the resulting executable as `bin/kernel_guard.exe` before booting. The `browser` argument opens the embedded browser UI:

```powershell
bin\kernel_guard.exe browser
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

## GUI build requirements

The desktop compositor requires a Windows MinGW-w64 or MSVC C++ compiler and the Windows user32, gdi32, and shell32 libraries. Stop `operator_wm.exe` before rebuilding because Windows locks a running executable. See [`UI.md`](UI.md) for the build command.
