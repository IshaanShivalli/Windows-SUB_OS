param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Join-Path $projectRoot "kernel\kernel_guard\Cargo.toml"
$powcurlManifest = Join-Path $projectRoot "powcurl\Cargo.toml"

New-Item -ItemType Directory -Force (Join-Path $projectRoot "runtime_java\bin") | Out-Null
javac -d (Join-Path $projectRoot "runtime_java\bin") (Get-ChildItem (Join-Path $projectRoot "runtime_java\src") -Filter *.java -Recurse | ForEach-Object FullName)
if ($LASTEXITCODE -ne 0) { throw "Java runtime compilation failed." }

if (Get-Command gcc -ErrorAction SilentlyContinue) {
    gcc (Join-Path $projectRoot "kernel\core_kernel.c") -o (Join-Path $projectRoot "bin\operator_kernel.exe")
    if ($LASTEXITCODE -ne 0) { throw "C microkernel compilation failed." }
    gcc (Join-Path $projectRoot "shell\operator_shell.c") -o (Join-Path $projectRoot "bin\operator_shell.exe")
    if ($LASTEXITCODE -ne 0) { throw "C shell launcher compilation failed." }
    g++ -std=c++17 (Join-Path $projectRoot "shell\pow_console.cpp") -o (Join-Path $projectRoot "bin\pow_console.exe")
    if ($LASTEXITCODE -ne 0) { throw "C++ POW console compilation failed." }
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Cargo was not found. Install Rust with rustup first."
}

$cargoArgs = @("build", "--manifest-path", $manifest)
if ($Release) { $cargoArgs += "--release" }
& cargo @cargoArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$profile = if ($Release) { "release" } else { "debug" }
$built = Join-Path $projectRoot "kernel\kernel_guard\target\$profile\kernel_guard.exe"
$destination = Join-Path $projectRoot "bin\kernel_guard.exe"
if (-not (Test-Path $built)) { throw "Cargo completed but output was not found: $built" }
Copy-Item -LiteralPath $built -Destination $destination -Force
Write-Host "Rust kernel guard copied to $destination"

$powcurlArgs = @("build", "--manifest-path", $powcurlManifest)
if ($Release) { $powcurlArgs += "--release" }
& cargo @powcurlArgs
if ($LASTEXITCODE -ne 0) { throw "Powcurl Rust/C media runtime build failed." }

$powcurlProfile = if ($Release) { "release" } else { "debug" }
$powcurlBuilt = Join-Path $projectRoot "powcurl\target\$powcurlProfile\powcurl.exe"
$powcurlDestination = Join-Path $projectRoot "bin\powcurl.exe"
if (-not (Test-Path $powcurlBuilt)) { throw "Cargo completed but powcurl output was not found: $powcurlBuilt" }
Copy-Item -LiteralPath $powcurlBuilt -Destination $powcurlDestination -Force
Write-Host "Powcurl runtime copied to $powcurlDestination"
