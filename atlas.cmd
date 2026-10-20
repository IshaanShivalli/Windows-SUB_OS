@echo off
rem ======================================================================
rem Atlas OS Global Launcher
rem Spawns Atlas OS Subsystem in a new terminal window.
rem ======================================================================

for %%I in ("%~dp0.") do set "ATLAS_ROOT=%%~fI"

where wt.exe >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start "" wt.exe --title "Atlas OS Subsystem" -d "%ATLAS_ROOT%" cmd.exe /k "python boot.py %*"
) else (
    start "Atlas OS Subsystem" /D "%ATLAS_ROOT%" cmd.exe /k "python boot.py %*"
)
