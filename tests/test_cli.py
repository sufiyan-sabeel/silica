"""End-to-end CLI tests: every documented command must actually work."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from silica import cli
from silica.bytecode import MAGIC

SQUARE = """sfn square(n: Int) -> Int {
    ret n * n
}

sfn main() {
    sprint(square(12))
}
"""


def cli_run(args, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(stdin)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="silica-cli-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class VersionAndHelpTests(CliTestCase):
    def test_version(self):
        code, out, _ = cli_run(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "silica 0.1.0")

    def test_help_lists_commands(self):
        code, out, _ = cli_run(["--help"])
        self.assertEqual(code, 0)
        for command in ("run", "check", "compile", "repl", "fmt", "test"):
            self.assertIn(command, out)

    def test_no_arguments_prints_usage(self):
        code, out, _ = cli_run([])
        self.assertEqual(code, 0)
        self.assertIn("usage", out)

    def test_unknown_command(self):
        code, _, err = cli_run(["frobnicate"])
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)

    def test_planned_commands_are_honest(self):
        for command in ("new", "add", "remove", "install", "build"):
            code, _, err = cli_run([command, "x"])
            self.assertEqual(code, 1, command)
            self.assertIn("not implemented", err)


class RunTests(CliTestCase):
    def test_run_source(self):
        path = self.write("main.sc", SQUARE)
        code, out, _ = cli_run(["run", path])
        self.assertEqual((code, out), (0, "144\n"))

    def test_run_missing_file(self):
        code, _, err = cli_run(["run", os.path.join(self.dir, "nope.sc")])
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)

    def test_run_reports_located_diagnostic(self):
        path = self.write("bad.sc", "sfn main() {\n    let x: Int = 1.5\n}\n")
        code, _, err = cli_run(["run", path])
        self.assertEqual(code, 1)
        self.assertIn("bad.sc:2:18: type error", err)

    def test_run_propagates_halt_code(self):
        path = self.write("halt.sc", "sfn main() {\n    halt(7)\n}\n")
        code, _, _ = cli_run(["run", path])
        self.assertEqual(code, 7)

    def test_run_feeds_stdin(self):
        path = self.write("io.sc", 'sfn main() {\n    sprint(input(""))\n}\n')
        code, out, _ = cli_run(["run", path], stdin="Riyaz\n")
        self.assertEqual((code, out), (0, "Riyaz\n"))

    def test_run_bytecode_directly(self):
        path = self.write("main.sc", SQUARE)
        self.assertEqual(cli_run(["compile", path])[0], 0)
        sbc = os.path.join(self.dir, "main.sbc")
        code, out, _ = cli_run(["run", sbc])
        self.assertEqual((code, out), (0, "144\n"))

    def test_run_rejects_corrupt_bytecode(self):
        path = self.write("main.sc", SQUARE)
        cli_run(["compile", path])
        sbc = os.path.join(self.dir, "main.sbc")
        with open(sbc, "rb") as handle:
            data = bytearray(handle.read())
        data[-1] ^= 0xFF
        with open(sbc, "wb") as handle:
            handle.write(data)
        code, _, err = cli_run(["run", sbc])
        self.assertEqual(code, 1)
        self.assertIn("checksum", err)


class CheckTests(CliTestCase):
    def test_check_success_is_silent(self):
        path = self.write("main.sc", SQUARE)
        code, out, err = cli_run(["check", path])
        self.assertEqual((code, out, err), (0, "", ""))

    def test_check_failure_explains_why(self):
        path = self.write("bad.sc", "sfn main() {\n    nope(1)\n}\n")
        code, _, err = cli_run(["check", path])
        self.assertEqual(code, 1)
        self.assertIn("unknown function", err)


class CompileTests(CliTestCase):
    def test_compile_writes_versioned_bytecode(self):
        path = self.write("main.sc", SQUARE)
        code, out, _ = cli_run(["compile", path])
        self.assertEqual(code, 0)
        sbc = os.path.join(self.dir, "main.sbc")
        self.assertTrue(os.path.exists(sbc))
        with open(sbc, "rb") as handle:
            data = handle.read()
        self.assertEqual(data[:8], MAGIC)
        self.assertIn("wrote", out)

    def test_compile_with_output_path(self):
        path = self.write("main.sc", SQUARE)
        target = os.path.join(self.dir, "custom.sbc")
        code, _, _ = cli_run(["compile", path, "-o", target])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(target))

    def test_compile_rejects_broken_source(self):
        path = self.write("bad.sc", "sfn main() {\n")
        code, _, err = cli_run(["compile", path])
        self.assertEqual(code, 1)
        self.assertIn("missing '}'", err)


class FmtTests(CliTestCase):
    def test_fmt_rewrites_file(self):
        path = self.write("ugly.sc", "sfn main() {\n        let x:Int=1+2\n  sprint(x)\n}\n")
        code, _, _ = cli_run(["fmt", path])
        self.assertEqual(code, 0)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(),
                             "sfn main() {\n    let x: Int = 1 + 2\n    sprint(x)\n}\n")

    def test_fmt_check_mode_reports_differences(self):
        path = self.write("ugly.sc", "sfn main() {\n        sprint(1)\n}\n")
        code, out, _ = cli_run(["fmt", "--check", path])
        self.assertEqual(code, 1)
        self.assertIn("would be reformatted", out)

    def test_fmt_check_mode_passes_on_formatted_file(self):
        path = self.write("ok.sc", SQUARE)
        code, out, _ = cli_run(["fmt", "--check", path])
        self.assertEqual(code, 0)

    def test_fmt_refuses_comments(self):
        path = self.write("c.sc", "# note\nsfn main() {\n    sprint(1)\n}\n")
        code, _, err = cli_run(["fmt", path])
        self.assertEqual(code, 1)
        self.assertIn("comments", err)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("# note", handle.read())

    def test_fmt_multiple_files(self):
        a = self.write("a.sc", "sfn main() {\n      sprint(1)\n}\n")
        b = self.write("b.sc", "sfn main() {\n      sprint(2)\n}\n")
        code, out, _ = cli_run(["fmt", a, b])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("formatted"), 2)


class TestCommandTests(CliTestCase):
    def test_runs_passing_tests(self):
        self.write("tests/ok_test.sc", 'sfn main() {\n    assert(1 + 1 == 2)\n}\n')
        code, out, _ = cli_run(["test", os.path.join(self.dir, "tests")])
        self.assertEqual(code, 0)
        self.assertIn("1/1 test files passed", out)

    def test_reports_failing_tests(self):
        self.write("tests/bad_test.sc", 'sfn main() {\n    assert(1 == 2)\n}\n')
        code, out, err = cli_run(["test", os.path.join(self.dir, "tests")])
        self.assertEqual(code, 1)
        self.assertIn("0/1 test files passed", out)
        self.assertIn("assertion failed", err)

    def test_missing_directory(self):
        code, _, err = cli_run(["test", os.path.join(self.dir, "nope")])
        self.assertEqual(code, 2)
        self.assertIn("no test directory", err)

    def test_empty_directory(self):
        os.makedirs(os.path.join(self.dir, "empty"))
        code, _, err = cli_run(["test", os.path.join(self.dir, "empty")])
        self.assertEqual(code, 2)
        self.assertIn("no *_test.sc files", err)


class ReplTests(CliTestCase):
    def test_repl_keeps_state_between_entries(self):
        script = "let x: Int = 21\nx * 2\nx = x + 1\nx\n:quit\n"
        code, out, _ = cli_run(["repl"], stdin=script)
        self.assertEqual(code, 0)
        self.assertIn("x: Int = 21", out)
        self.assertIn("42", out)
        self.assertIn("22", out)

    def test_repl_supports_multiline_functions(self):
        script = ("sfn twice(n: Int) -> Int {\n    ret n * 2\n}\n"
                  "twice(5)\n:quit\n")
        code, out, _ = cli_run(["repl"], stdin=script)
        self.assertEqual(code, 0)
        self.assertIn("defined twice", out)
        self.assertIn("10", out)

    def test_repl_reports_errors_and_continues(self):
        script = "nope(1)\n1 + 1\n:quit\n"
        code, out, err = cli_run(["repl"], stdin=script)
        self.assertEqual(code, 0)
        self.assertIn("unknown function", err)
        self.assertIn("2", out)

    def test_repl_globals_command(self):
        code, out, _ = cli_run(["repl"], stdin="let a: Int = 5\n:globals\n:quit\n")
        self.assertEqual(code, 0)
        self.assertIn("a: Int = 5", out)

    def test_repl_exits_on_eof(self):
        code, _, _ = cli_run(["repl"], stdin="")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
