#!/usr/bin/env python3
"""Launch Operator OS in its own Windows console, or run it directly elsewhere."""

import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
CHILD_MARKER = "--_operator-launcher-child"


def run_boot(arguments: list[str], *, pause: bool) -> int:
    command = [sys.executable, str(ROOT_DIR / "boot.py"), *arguments]
    try:
        result = subprocess.run(command, cwd=ROOT_DIR, check=False)
    except OSError as exc:
        print(f"Could not start Operator OS: {exc}", file=sys.stderr)
        result_code = 1
    else:
        result_code = result.returncode

    if pause:
        try:
            input("Operator OS has stopped. Press Enter to close this window...")
        except EOFError:
            pass
    return result_code


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if CHILD_MARKER in arguments:
        arguments.remove(CHILD_MARKER)
        return run_boot(arguments, pause=True)

    if os.name == "nt":
        command = [sys.executable, str(Path(__file__).resolve()), CHILD_MARKER, *arguments]
        try:
            subprocess.Popen(
                command,
                cwd=ROOT_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError as exc:
            print(f"Could not open an Operator OS console: {exc}", file=sys.stderr)
            return 1
        return 0

    return run_boot(arguments, pause=False)


if __name__ == "__main__":
    raise SystemExit(main())
