#!/usr/bin/env python3
"""Launch Operator OS's built-in terminal editor."""

import runpy
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.argv[0] = str(ROOT_DIR / "apps" / "nano.py")
runpy.run_path(sys.argv[0], run_name="__main__")
