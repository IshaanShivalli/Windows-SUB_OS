"""POW (Polyglot Operator Workflow) execution engine.

POW is intentionally small: each line is a stage, and stages can target
the Operator shell or optional host bridges.  Stages communicate through
UTF-8 stdin/stdout, so a workflow can mix CLI languages without temporary
files.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class PowResult:
    code: int
    output: str
    engine: str


class PowEngine:
    ENGINES = {"operator", "opshell", "powershell", "pwsh", "cmd", "bash", "wsl"}

    def __init__(self, root: Path, operator_runner: Optional[Callable[[str], str]] = None):
        self.root = Path(root).resolve()
        self.operator_runner = operator_runner
        self.variables: dict[str, str] = {}

    def _command(self, engine: str, text: str) -> list[str]:
        engine = engine.lower()
        if engine in ("operator", "opshell"):
            return []
        if engine in ("powershell", "pwsh"):
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command", text]
        if engine == "cmd":
            return ["cmd.exe", "/d", "/s", "/c", text]
        if engine == "bash":
            return ["bash", "-lc", text]
        return ["wsl", "--", "bash", "-lc", text]

    def run(self, engine: str, text: str, stdin: str = "") -> PowResult:
        engine = engine.lower()
        if engine not in self.ENGINES:
            raise ValueError(f"unknown POW engine: {engine}")
        expanded = text
        for key, value in self.variables.items():
            expanded = expanded.replace("${" + key + "}", value)
        if engine in ("operator", "opshell"):
            if not self.operator_runner:
                return PowResult(1, "POW: Operator runner is unavailable", engine)
            result = self.operator_runner(expanded)
            return PowResult(0, result or "", engine)
        try:
            proc = subprocess.run(
                self._command(engine, expanded), input=stdin, text=True,
                capture_output=True, cwd=str(self.root), timeout=60,
                env=os.environ.copy(),
            )
            return PowResult(proc.returncode, proc.stdout + proc.stderr, engine)
        except FileNotFoundError:
            return PowResult(127, f"POW: {engine} is not installed\n", engine)
        except subprocess.TimeoutExpired:
            return PowResult(124, f"POW: {engine} timed out\n", engine)

    def execute(self, source: str) -> str:
        """Execute POW source.

        Syntax:
          let NAME=value
          use powershell: Get-Process
          use cmd: dir
          use bash: grep foo
          use operator: storage.inspect
          pipe powershell: ... | bash: ...
          import path.pow
        """
        output = ""
        for number, raw in enumerate(source.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("let ") and "=" in line:
                key, value = line[4:].split("=", 1)
                self.variables[key.strip()] = value.strip().strip("\"'")
                continue
            if line.startswith("import "):
                path = Path(line[7:].strip().strip("\"'"))
                if not path.is_absolute():
                    path = self.root / path
                if path.suffix != ".pow":
                    path = path.with_suffix(".pow")
                if not path.exists():
                    raise FileNotFoundError(f"POW import not found on line {number}: {path}")
                output += self.execute(path.read_text(encoding="utf-8"))
                continue
            if line.startswith("pipe "):
                stages = [s.strip() for s in line[5:].split("|")]
                stdin = ""
                for stage in stages:
                    engine, text = stage.split(":", 1)
                    result = self.run(engine.strip(), text.strip(), stdin)
                    stdin = result.output
                    if result.code:
                        raise RuntimeError(f"POW stage failed ({result.engine}, exit {result.code}): {stdin}")
                output += stdin
                continue
            if line.startswith("use ") and ":" in line:
                engine, text = line[4:].split(":", 1)
                result = self.run(engine.strip(), text.strip())
                output += result.output
                if result.code:
                    raise RuntimeError(f"POW stage failed ({result.engine}, exit {result.code})")
                continue
            raise SyntaxError(f"POW syntax error on line {number}: {line}")
        return output.rstrip()

    def execute_file(self, path: str) -> str:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.root / file_path
        if file_path.suffix.lower() != ".pow":
            raise ValueError("Operator workflows must use .pow files")
        return self.execute(file_path.read_text(encoding="utf-8"))
