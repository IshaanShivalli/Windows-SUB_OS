"""Python replacement for the former CMD/batch environment demo."""

import os
from pathlib import Path


def main() -> None:
    print("=" * 42)
    print("[PYTHON] Running the environment demo in Operator OS")
    print(f"Script file: {Path(__file__).name}")
    print(f"Host OS: {os.name}")
    print(f"Working directory: {Path.cwd()}")
    print("=" * 42)


if __name__ == "__main__":
    main()
