param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Join-Path $projectRoot "kernel\kernel_guard\Cargo.toml"

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Cargo was not found. Install Rust with rustup first."
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$vsInstall = if (Test-Path $vswhere) {
    & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}

$target = "x86_64-pc-windows-msvc"
if ($vsInstall) {
    $devCmd = Join-Path $vsInstall "Common7\Tools\Launch-VsDevShell.ps1"
    . $devCmd -Arch amd64 -HostArch amd64
} else {
    throw "Visual Studio C++ tools were not found. Install the Desktop development with C++ workload. MSYS2 GCC alone cannot build this MSVC Rust toolchain because Cargo build scripts must also be linked."
}

$cargoArgs = @("build", "--target", $target, "--manifest-path", $manifest)
if ($Release) { $cargoArgs += "--release" }
& cargo @cargoArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$profile = if ($Release) { "release" } else { "debug" }
$built = Join-Path $projectRoot "kernel\kernel_guard\target\$target\$profile\kernel_guard.exe"
$destination = Join-Path $projectRoot "bin\kernel_guard.exe"
if (-not (Test-Path $built)) { throw "Cargo completed but output was not found: $built" }
Copy-Item -LiteralPath $built -Destination $destination -Force
Write-Host "Rust kernel guard copied to $destination"
