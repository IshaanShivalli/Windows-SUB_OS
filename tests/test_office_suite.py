import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from apps.office import OfficeApplication
from core.office_suite import OfficeSuite, SpreadsheetDatabase
from shell.opshell import OperatorShellEngine


class SpreadsheetDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "budget.opsheet"
        self.database = SpreadsheetDatabase(self.path)

    def test_spreadsheet_file_is_sqlite_and_persists_cells_and_dimensions(self):
        self.database.create(title="Budget", rows=8, columns=5)
        self.database.set_cell(0, 0, "Item")
        self.database.set_cell(1, 0, "Hosting")
        self.database.set_cell(1, 1, "24.50")
        self.database.resize(12, 7)

        loaded = self.database.load()

        self.assertEqual(loaded["title"], "Budget")
        self.assertEqual((loaded["rows"], loaded["columns"]), (12, 7))
        self.assertEqual(loaded["cells"][(0, 0)], "Item")
        self.assertEqual(loaded["cells"][(1, 1)], "24.50")
        with closing(sqlite3.connect(self.path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(tables, {"sheet_info", "cells"})

    def test_cells_can_be_cleared_and_shrinking_removes_out_of_bounds_cells(self):
        self.database.create(rows=3, columns=3)
        self.database.set_cell(2, 2, "remove when resized")
        self.database.set_cell(0, 0, "clear me")
        self.database.set_cell(0, 0, "")
        self.database.resize(2, 2)

        loaded = self.database.load()

        self.assertEqual(loaded["cells"], {})

    def test_rejects_duplicate_files_invalid_dimensions_and_invalid_database(self):
        self.database.create()
        with self.assertRaises(FileExistsError):
            self.database.create()
        with self.assertRaises(ValueError):
            self.database.resize(0, 4)
        invalid = SpreadsheetDatabase(Path(self.temporary.name) / "not-a-sheet.opsheet")
        invalid.path.write_text("not sqlite", encoding="utf-8")
        with self.assertRaises(sqlite3.DatabaseError):
            invalid.load()


class OfficeApplicationLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "Users" / "operator" / "home"
        self.documents = self.home / "Documents"
        self.documents.mkdir(parents=True)

    def resolve_path(self, target, cwd, username):
        if target.startswith("/"):
            virtual = Path(target)
        else:
            virtual = Path(cwd) / target
        physical = self.root.joinpath(*virtual.parts[1:])
        return physical, str(virtual)

    def test_office_command_opens_graphical_app_with_active_user_home(self):
        suite = OfficeSuite(self.resolve_path)
        with patch("apps.office.launch_office") as launch:
            result = suite.execute(
                "office",
                [],
                "/Users/operator/home",
                "operator",
            )

        self.assertEqual(result, "[OFFICE] Office window closed.")
        launch.assert_called_once_with(
            mode="home",
            home_path=self.home,
            initial_path=None,
        )

    def test_sheet_command_opens_database_spreadsheet_for_selected_file(self):
        suite = OfficeSuite(self.resolve_path)
        workbook = self.documents / "budget.opsheet"
        workbook.touch()
        with patch("apps.office.launch_office") as launch:
            suite.execute(
                "office.sheet",
                ["Documents/budget.opsheet"],
                "/Users/operator/home",
                "operator",
            )

        launch.assert_called_once_with(
            mode="sheet",
            home_path=self.home,
            initial_path=workbook,
        )

    def test_office_shell_routes_gui_without_text_command_operations(self):
        shell = OperatorShellEngine.__new__(OperatorShellEngine)
        shell.variables = {
            "SYS.USER": "operator",
            "SYS.CWD": "/Users/operator/home",
        }
        shell.storage = type(
            "Storage",
            (),
            {"resolve_vpath": staticmethod(self.resolve_path)},
        )()
        shell.office_suite = OfficeSuite(self.resolve_path)
        with patch("apps.office.launch_office") as launch:
            result = shell.eval_command("office")

        self.assertEqual(result, "[OFFICE] Office window closed.")
        launch.assert_called_once()

    def test_office_application_rejects_paths_outside_active_home(self):
        application = OfficeApplication.__new__(OfficeApplication)
        application.home_path = self.home.resolve()

        with self.assertRaisesRegex(ValueError, "inside the active user's home"):
            application._inside_home(self.root / "outside.txt")


if __name__ == "__main__":
    unittest.main()
