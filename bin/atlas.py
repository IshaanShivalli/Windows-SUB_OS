#!/usr/bin/env python3
"""Compatibility launcher for the repository's Operator OS launcher."""

import runpy
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
runpy.run_path(str(ROOT_DIR / "atlas.py"), run_name="__main__")
