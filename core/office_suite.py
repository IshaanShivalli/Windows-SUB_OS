"""Office application launcher and SQLite-backed spreadsheet storage."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable


class SpreadsheetDatabase:
    """Persist a worksheet's dimensions and cells in one SQLite database file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def create(self, title=None, rows=100, columns=26):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("xb"):
                pass
        except FileExistsError:
            raise FileExistsError(f"Spreadsheet already exists: {self.path.name}") from None
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    connection.executescript(
                        """
                        CREATE TABLE sheet_info (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            title TEXT NOT NULL,
                            row_count INTEGER NOT NULL CHECK (row_count > 0),
                            column_count INTEGER NOT NULL CHECK (column_count > 0)
                        );
                        CREATE TABLE cells (
                            row_index INTEGER NOT NULL CHECK (row_index >= 0),
                            column_index INTEGER NOT NULL CHECK (column_index >= 0),
                            value TEXT NOT NULL,
                            PRIMARY KEY (row_index, column_index)
                        );
                        """
                    )
                    connection.execute(
                        "INSERT INTO sheet_info (id, title, row_count, column_count) "
                        "VALUES (1, ?, ?, ?)",
                        (title or self.path.stem, rows, columns),
                    )
        except sqlite3.Error:
            self.path.unlink(missing_ok=True)
            raise

    def load(self):
        if not self.path.is_file():
            raise FileNotFoundError(f"Spreadsheet not found: {self.path}")
        with closing(sqlite3.connect(self.path)) as connection:
            info = connection.execute(
                "SELECT title, row_count, column_count FROM sheet_info WHERE id = 1"
            ).fetchone()
            if info is None:
                raise ValueError(f"Not an Operator spreadsheet database: {self.path.name}")
            values = connection.execute(
                "SELECT row_index, column_index, value FROM cells "
                "ORDER BY row_index, column_index"
            ).fetchall()
        return {
            "title": info[0],
            "rows": info[1],
            "columns": info[2],
            "cells": {
                (row_index, column_index): value
                for row_index, column_index, value in values
            },
        }

    def set_cell(self, row_index, column_index, value):
        if row_index < 0 or column_index < 0:
            raise ValueError("Cell indexes must be non-negative")
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                info = connection.execute(
                    "SELECT row_count, column_count FROM sheet_info WHERE id = 1"
                ).fetchone()
                if info is None:
                    raise ValueError(f"Not an Operator spreadsheet database: {self.path.name}")
                if row_index >= info[0] or column_index >= info[1]:
                    raise ValueError("Cell is outside the current spreadsheet dimensions")
                if value == "":
                    connection.execute(
                        "DELETE FROM cells WHERE row_index = ? AND column_index = ?",
                        (row_index, column_index),
                    )
                else:
                    connection.execute(
                        "INSERT INTO cells (row_index, column_index, value) VALUES (?, ?, ?) "
                        "ON CONFLICT(row_index, column_index) DO UPDATE SET value = excluded.value",
                        (row_index, column_index, str(value)),
                    )

    def resize(self, rows, columns):
        if rows < 1 or columns < 1:
            raise ValueError("A spreadsheet must contain at least one row and one column")
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                result = connection.execute(
                    "UPDATE sheet_info SET row_count = ?, column_count = ? WHERE id = 1",
                    (rows, columns),
                )
                if result.rowcount != 1:
                    raise ValueError(f"Not an Operator spreadsheet database: {self.path.name}")
                connection.execute(
                    "DELETE FROM cells WHERE row_index >= ? OR column_index >= ?",
                    (rows, columns),
                )


class OfficeSuite:
    def __init__(self, resolve_path: Callable):
        self.resolve_path = resolve_path

    def execute(self, program, args, cwd, username):
        if len(args) > 1:
            return f"Usage: {program} [file]"
        initial_path = None
        if args:
            initial_path, _ = self.resolve_path(
                args[0],
                cwd,
                username,
            )
        mode = {
            "office": "home",
            "office.writer": "writer",
            "office.sheet": "sheet",
            "office.slides": "slides",
        }.get(program)
        if mode is None:
            return f"[OFFICE ERROR] Unknown program: {program}"
        try:
            import tkinter as tk
        except ImportError as exc:
            return f"[OFFICE ERROR] Tkinter is not available in this Python installation: {exc}"
        try:
            from apps.office import launch_office

            launch_office(
                mode=mode,
                home_path=self._home_path(cwd, username),
                initial_path=initial_path,
            )
        except (ImportError, OSError, RuntimeError, ValueError, tk.TclError) as exc:
            return f"[OFFICE ERROR] Could not open the office suite: {exc}"
        return "[OFFICE] Office window closed."

    def _home_path(self, cwd, username):
        home_path, _ = self.resolve_path(
            f"/Users/{username}/home",
            cwd,
            username,
        )
        return Path(home_path)
