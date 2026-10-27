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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")

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
        from silica import __version__
        code, out, _ = cli_run(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "silica %s" % __version__)

    def test_help_lists_commands(self):
        code, out, _ = cli_run(["--help"])
        self.assertEqual(code, 0)
        for command in ("run", "check", "compile", "repl", "fmt", "test",
                        "capabilities"):
            self.assertIn(command, out)

    def test_no_arguments_starts_the_interpreter(self):
        code, out, _ = cli_run([], stdin="exit\n")
        self.assertEqual(code, 0)
        self.assertIn("Silica Interpreter v%s" % cli.VERSION, out)
        self.assertIn(cli.PROMPT, out)
        self.assertNotIn("usage:", out)

    def test_the_banner_is_one_line_and_comes_first(self):
        code, out, _ = cli_run([], stdin="exit\n")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "Silica Interpreter v%s" % cli.VERSION)
        self.assertEqual(lines[1], cli.PROMPT.rstrip() + " ", lines[1])
        self.assertEqual(len(lines), 2, lines)

    def test_the_prompt_is_the_cent_sign(self):
        self.assertEqual(cli.PROMPT, "\u00a2 ")
        code, out, _ = cli_run([], stdin="1 + 1\nexit\n")
        self.assertEqual(code, 0)
        self.assertIn("\u00a2 2", out)
        self.assertNotIn("silica>", out)

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


class DirectFileTests(CliTestCase):
    """`silica file.sc` — the form people actually type."""

    def test_runs_a_source_file_directly(self):
        path = self.write("square.sc", SQUARE)
        code, out, err = cli_run([path])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "144\n")

    def test_matches_the_run_subcommand(self):
        path = self.write("square.sc", SQUARE)
        direct = cli_run([path])
        explicit = cli_run(["run", path])
        self.assertEqual(direct, explicit)

    def test_runs_bytecode_directly(self):
        source = self.write("square.sc", SQUARE)
        out_path = os.path.join(self.dir, "square.sbc")
        self.assertEqual(cli_run(["compile", source, "-o", out_path])[0], 0)
        code, out, err = cli_run([out_path])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "144\n")

    def test_relative_path_works(self):
        self.write("nested/hello.sc", 'sfn main() {\n    sprint("hi")\n}\n')
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            code, out, _ = cli_run([os.path.join("nested", "hello.sc")])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0)
        self.assertEqual(out, "hi\n")

    def test_uppercase_extension_is_recognised(self):
        path = self.write("LOUD.SC", 'sfn main() {\n    sprint("loud")\n}\n')
        code, out, err = cli_run([path])
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "loud\n")

    def test_missing_file_is_an_error_not_a_traceback(self):
        code, out, err = cli_run([os.path.join(self.dir, "nope.sc")])
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_invalid_syntax_reports_file_and_line(self):
        path = self.write("broken.sc", "sfn main() {\n    return 1\n}\n")
        code, _out, err = cli_run([path])
        self.assertEqual(code, 1)
        self.assertIn("broken.sc:2", err)
        self.assertIn("parse error", err)
        self.assertNotIn("Traceback", err)

    def test_unbalanced_parenthesis_still_reports_a_location(self):
        path = self.write("unbalanced.sc", "sfn main() {\n    sprint(\n}\n")
        code, _out, err = cli_run([path])
        self.assertEqual(code, 1)
        self.assertRegex(err, r"unbalanced\.sc:\d+:\d+")
        self.assertIn("parse error", err)

    def test_type_error_reports_file_and_line(self):
        path = self.write("typed.sc", 'sfn main() {\n    let x: Int = "no"\n}\n')
        code, _out, err = cli_run([path])
        self.assertEqual(code, 1)
        self.assertIn("typed.sc:2", err)
        self.assertIn("type error", err)

    def test_capability_flags_are_forwarded(self):
        example = os.path.join(ROOT, "examples", "fs_demo.sc")
        code, out, err = cli_run([example, "--allow-fs-read", EXAMPLES,
                                  "--allow-fs-list", EXAMPLES])
        self.assertEqual(code, 0, err)
        self.assertIn("oui", out)

    def test_capability_flags_are_enforced_in_the_direct_form(self):
        example = os.path.join(ROOT, "examples", "fs_demo.sc")
        code, _out, err = cli_run([example])
        self.assertEqual(code, 1)
        self.assertIn("capability error", err)

    def test_a_non_silica_file_is_not_treated_as_source(self):
        path = self.write("notes.txt", "hello")
        code, _out, err = cli_run([path])
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)


class ReplTests(CliTestCase):
    def test_banner_names_the_interpreter_and_version(self):
        code, out, _ = cli_run([], stdin="exit\n")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("Silica Interpreter v%s\n" % cli.VERSION), out)

    def test_ctrl_d_exits_cleanly(self):
        """EOF is Ctrl+D on a terminal; it must end the session, not crash."""
        code, out, err = cli_run([], stdin="1 + 1\n")
        self.assertEqual(code, 0)
        self.assertIn("2", out)
        self.assertEqual(err, "")

    def test_a_prompt_is_written_for_every_ready_line(self):
        code, out, _ = cli_run([], stdin="1\n2\n3\n")
        self.assertEqual(code, 0)
        self.assertEqual(out.count(cli.PROMPT), 4)  # three lines plus the EOF prompt

    def test_the_prompt_survives_an_ascii_only_stdout(self):
        """A C locale must not crash the interpreter on a non-ASCII prompt."""
        import sys as _sys
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
        saved_out, saved_in = _sys.stdout, _sys.stdin
        _sys.stdout = stream
        _sys.stdin = io.StringIO("1 + 1\nexit\n")
        try:
            code = cli.cmd_repl([])
        finally:
            _sys.stdout = saved_out
            _sys.stdin = saved_in
            stream.flush()
        self.assertEqual(code, 0)
        written = raw.getvalue().decode("utf-8", "replace")
        self.assertIn("2", written)
        self.assertIn("\u00a2", written)

    def test_help_command_lists_the_commands(self):
        code, out, _ = cli_run([], stdin="help\nexit\n")
        self.assertEqual(code, 0)
        self.assertIn("this text", out)
        self.assertIn("leave the interpreter", out)
        self.assertIn("globals", out)

    def test_exit_and_quit_both_leave(self):
        for word in ("exit", "quit", ":quit", ":q"):
            with self.subTest(word=word):
                code, _out, _ = cli_run([], stdin="%s\n" % word)
                self.assertEqual(code, 0)

    def test_bare_expressions_are_evaluated(self):
        code, out, _ = cli_run([], stdin="2 + 3 * 4\nexit\n")
        self.assertEqual(code, 0)
        self.assertIn("14", out)

    def test_statements_persist(self):
        code, out, _ = cli_run([], stdin="let n: Int = 7\nn * 6\nexit\n")
        self.assertEqual(code, 0)
        self.assertIn("n: Int = 7", out)
        self.assertIn("42", out)

    def test_errors_are_reported_and_the_session_continues(self):
        code, out, err = cli_run([], stdin="1 +\n1 + 1\nexit\n")
        self.assertEqual(code, 0)
        self.assertIn("parse error", err)
        self.assertIn("2", out)
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
