"""The three application examples, executed as real programs.

Each test runs the application through the CLI in a temporary working directory,
feeds it stdin, and then checks **both** the transcript and whatever the program
wrote to disk. A test that only asserted "exit code 0" would pass on a program
that did nothing.

The applications are the ones documented in `docs/APPLICATIONS.md`:
`calculator_app.sc`, `task_manager.sc` and `data_report.sc`.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from silica import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")

FS_FLAGS = ["--allow-fs-read", ".", "--allow-fs-write", "."]


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="silica-app-")
        self.addCleanup(shutil.rmtree, self.directory, True)

    def run_app(self, name, stdin_text, flags=(), directory=None):
        """Run an example in `directory` (default: the temp dir) and capture output."""
        path = os.path.join(EXAMPLES, name)
        out, err = io.StringIO(), io.StringIO()
        previous = os.getcwd()
        os.chdir(directory or self.directory)
        try:
            with mock.patch("sys.stdin", io.StringIO(stdin_text)), \
                    contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                code = cli.main(["run", path] + list(flags))
        finally:
            os.chdir(previous)
        return code, out.getvalue(), err.getvalue()

    def write(self, name, text):
        path = os.path.join(self.directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def read(self, name):
        with open(os.path.join(self.directory, name), encoding="utf-8") as handle:
            return handle.read()


class CalculatorTests(AppTestCase):
    def test_arithmetic_and_every_error_path(self):
        code, out, err = self.run_app(
            "calculator_app.sc",
            "12 * 4\n7 / 2\n1 / 0\nabc + 2\n12 *\n\n5 % 3\nquit\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, (
            "Silica calculator\n"
            "type an expression such as '12 * 4', or 'quit' to leave\n"
            "calc> 48.0\n"
            "calc> 3.5\n"
            "calc> error: cannot divide by zero\n"
            "calc> error: 'abc' is not a number\n"
            "calc> error: expected three parts, like '12 * 4'\n"
            "calc> error: empty input\n"
            "calc> error: unknown operator '%' (use + - * /)\n"
            "calc> bye\n"))

    def test_negative_and_decimal_numbers(self):
        code, out, err = self.run_app("calculator_app.sc",
                                      "-4 + 1.5\n2.5 * 2\nquit\n")
        self.assertEqual(code, 0, err)
        self.assertIn("-2.5\n", out)
        self.assertIn("5.0\n", out)

    def test_it_needs_no_capability(self):
        # pure computation and stdin: no grant, and it still runs
        code, out, err = self.run_app("calculator_app.sc", "1 + 1\nquit\n")
        self.assertEqual(code, 0, err)
        self.assertIn("2.0\n", out)


class TaskManagerTests(AppTestCase):
    TRANSCRIPT = ("add buy milk\nadd write docs\nlist\ndone 1\nlist\n"
                  "done 9\nremove 2\nlist\nbogus\nquit\n")

    def test_the_full_lifecycle_and_the_file_it_writes(self):
        code, out, err = self.run_app("task_manager.sc", self.TRANSCRIPT, FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("Silica task manager - 0 task(s) in tasks.json", out)
        self.assertIn("added #1: buy milk", out)
        self.assertIn("added #2: write docs", out)
        self.assertIn("[ ] 1. buy milk", out)
        self.assertIn("[x] 1. buy milk", out)
        self.assertIn("2 task(s), 1 still open", out)
        self.assertIn("error: no task with id 9", out)
        self.assertIn("removed task 2", out)
        self.assertIn("error: unknown command 'bogus'", out)
        self.assertIn("bye", out)

        # the file is the real output: parse it and check the state
        saved = json.loads(self.read("tasks.json"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], 1)
        self.assertEqual(saved[0]["title"], "buy milk")
        self.assertIs(saved[0]["done"], True)
        self.assertIsInstance(saved[0]["created"], int)

    def test_state_persists_across_runs(self):
        self.run_app("task_manager.sc", "add keep me\nquit\n", FS_FLAGS)
        code, out, err = self.run_app("task_manager.sc", "list\nquit\n", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("Silica task manager - 1 task(s) in tasks.json", out)
        self.assertIn("[ ] 1. keep me", out)

    def test_without_capabilities_it_refuses_and_writes_nothing(self):
        code, out, err = self.run_app("task_manager.sc", "add x\nquit\n")
        self.assertEqual(code, 1)
        self.assertIn("capability error", err)
        self.assertIn("fs", err)
        self.assertFalse(os.path.exists(os.path.join(self.directory, "tasks.json")))

    def test_an_empty_title_is_refused(self):
        code, out, err = self.run_app("task_manager.sc", "add\nquit\n", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("error: add needs a title", out)

    def test_a_non_numeric_id_is_refused(self):
        code, out, err = self.run_app("task_manager.sc", "done abc\nquit\n", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("error: 'abc' is not an id", out)

    def test_a_corrupt_store_is_reported_not_crashed_on(self):
        # a list of numbers is a list, but not a list of tasks
        self.write("tasks.json", "[1, 2, 3]")
        code, out, err = self.run_app("task_manager.sc", "list\nquit\n", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("holds an entry that is not a task", out)
        self.assertIn("no tasks yet", out)

    def test_a_task_missing_its_fields_is_rejected(self):
        self.write("tasks.json", '[{"id": 1}]')
        code, out, err = self.run_app("task_manager.sc", "list\nquit\n", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("without id, title or done", out)


class DataReportTests(AppTestCase):
    CSV = ("region,units,unit_price\n"
           "north,120,4.50\n"
           "south,80,5.25\n"
           "north,45,4.50\n"
           "east,60,6.00\n")

    def test_it_aggregates_and_writes_a_report(self):
        self.write("sales.csv", self.CSV)
        code, out, err = self.run_app("data_report.sc", "", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("reading 4 row(s) from sales.csv", out)
        # the region column is padded to 12 characters, so build the line the
        # same way rather than counting spaces by hand
        self.assertIn("north".ljust(12) + "742.50", out)   # (120 + 45) * 4.50
        self.assertIn("south".ljust(12) + "420.00", out)   # 80 * 5.25
        self.assertIn("east".ljust(12) + "360.00", out)    # 60 * 6.00
        self.assertIn("total".ljust(12) + "1522.50", out)
        self.assertIn("units".ljust(12) + "305", out)
        self.assertIn("best".ljust(12) + "north", out)

        report = json.loads(self.read("report.json"))
        self.assertEqual(report["rows"], 4)
        self.assertEqual(report["units"], 305)
        self.assertAlmostEqual(report["revenue"], 1522.5, places=6)
        self.assertEqual(report["best"], "north")
        self.assertEqual(report["skipped"], 0)
        self.assertEqual([row["region"] for row in report["regions"]],
                         ["north", "south", "east"])

    def test_a_missing_source_is_reported_and_no_report_is_written(self):
        code, out, err = self.run_app("data_report.sc", "", FS_FLAGS)
        self.assertEqual(code, 1)
        self.assertIn("sales.csv not found", out)
        self.assertIn("copy examples/data/sales.csv", out)
        self.assertFalse(os.path.exists(os.path.join(self.directory, "report.json")))

    def test_bad_rows_are_skipped_and_counted(self):
        self.write("sales.csv",
                   "region,units,unit_price\n"
                   "north,10,2.00\n"
                   "broken,row\n"
                   "south,ten,3.00\n"
                   "east,5,1.00\n")
        code, out, err = self.run_app("data_report.sc", "", FS_FLAGS)
        self.assertEqual(code, 0, err)
        self.assertIn("does not have three fields", out)
        self.assertIn("has a non-numeric value", out)
        self.assertIn("skipped     2 bad row(s)", out)
        report = json.loads(self.read("report.json"))
        self.assertEqual(report["skipped"], 2)
        self.assertEqual(report["units"], 15)          # 10 + 5
        self.assertAlmostEqual(report["revenue"], 25.0, places=6)

    def test_a_file_with_no_usable_rows_fails_cleanly(self):
        self.write("sales.csv", "region,units,unit_price\n")
        code, out, err = self.run_app("data_report.sc", "", FS_FLAGS)
        self.assertEqual(code, 1)
        self.assertIn("needs a header and at least one row", out)

    def test_the_shipped_sample_data_produces_the_documented_report(self):
        shutil.copy(os.path.join(EXAMPLES, "data", "sales.csv"), self.directory)
        code, out, err = self.run_app("data_report.sc", "", FS_FLAGS)
        self.assertEqual(code, 0, err)
        report = json.loads(self.read("report.json"))
        self.assertEqual(report["rows"], 8)
        self.assertEqual(report["units"], 450)
        self.assertAlmostEqual(report["revenue"], 2152.5, places=6)
        self.assertEqual(report["best"], "north")


class ExampleCoverageTests(unittest.TestCase):
    def test_every_application_is_a_discoverable_example(self):
        names = {name for name in os.listdir(EXAMPLES) if name.endswith(".sc")}
        for name in ("calculator_app.sc", "task_manager.sc", "data_report.sc"):
            self.assertIn(name, names)

    def test_the_sample_data_ships_with_the_repository(self):
        path = os.path.join(EXAMPLES, "data", "sales.csv")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as handle:
            self.assertTrue(handle.readline().startswith("region,"))


if __name__ == "__main__":
    unittest.main()
