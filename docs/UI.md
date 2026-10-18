# Operator OS Desktop UI

Operator OS uses a host-based Win32 desktop compositor. It is launched on demand from Operator Shell rather than during boot.

## Starting the desktop

Run `python boot.py`, then type `gui` in Operator Shell. The desktop executable is `bin/operator_wm.exe`.

The desktop contains a top panel, application rail, application windows, and a bottom dock. Windows support focus, dragging, minimizing, maximizing, and closing.

## GUI terminal

Click the terminal window and type a command. Press Enter to pass the command to `shell/opshell.py`; Backspace edits the current input.

## Operator File Manager

The Operator home tree is restricted to the 2GB volume at `storage/operator_home/`: `Home/Docs`, `Home/Downloads`, `Home/Pictures`, `Home/Videos`, and `Google Drive/Docs`, `Google Drive/Videos`, and `Google Drive/Pictures`.

## Google Drive

Google Drive is optional and configured at runtime only. Boot never asks for credentials. Use `drive.status` and `drive.connect` in Operator Shell. Until authentication is provided, directory listings show `Google Drive (not connected)`. Authentication creates the remote `Operator OS/Docs`, `Operator OS/Videos`, and `Operator OS/Pictures` folders. OAuth files under `config/` are excluded by `.gitignore`.

## Building the GUI

Close the running desktop before rebuilding:

```powershell
Stop-Process -Name operator_wm -Force -ErrorAction SilentlyContinue
g++ -std=c++17 -municode gui/window_manager_v2.cpp gui/ui/desktop_shell.cpp gui/ui/file_manager.cpp gui/ui/input_controller.cpp -Igui -o bin/operator_wm.exe -lgdi32 -luser32 -lshell32
```

UI support code is organized under `gui/ui/` for theme tokens, desktop shell drawing, file operations, and input handling.
