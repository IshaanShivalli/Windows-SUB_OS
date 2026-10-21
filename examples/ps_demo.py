"""Python replacement for the former PowerShell host-information demo."""

import platform
import sys


def main() -> None:
    print("=" * 42)
    print("[PYTHON] Running the host-information demo in Operator OS")
    print(f"Host platform: {platform.platform()}")
    print(f"Python version: {sys.version.split()[0]}")
    print("Running from the Operator OS project")
    print("=" * 42)


if __name__ == "__main__":
    main()
