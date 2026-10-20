@echo off
rem Atlas OS Inbuilt GNU Nano Launcher
if exist "C:\msys64\usr\bin\nano.exe" (
    "C:\msys64\usr\bin\nano.exe" %*
    exit /b %ERRORLEVEL%
)
if exist "C:\Users\Default\Desktop\Git\usr\bin\nano.exe" (
    "C:\Users\Default\Desktop\Git\usr\bin\nano.exe" %*
    exit /b %ERRORLEVEL%
)
python "%~dp0..\apps\nano.py" %*

