# PowerShell Script for Operator OS
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "[POWERSHELL] Executing ps1 script inside Operator OS" -ForegroundColor Green
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
Write-Host "Host Caption: $($os.Caption)"
Write-Host "Active PowerShell Version: $($PSVersionTable.PSVersion)"
Write-Host "Running in Operator OS Subsystem Root"
Write-Host "==========================================" -ForegroundColor Cyan
