"""Example and formatting conformance tests.

Every file in examples/ must compile, verify and run; the documented outputs
are asserted here so the examples cannot silently rot. The Silica-level test
suite in tests/silica/ is executed through `silica test`.
"""

import contextlib
import io
import os
import unittest
from unittest import mock

from silica import cli
from silica.engine import compile_source
from silica.fmt import format_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")
SILICA_TESTS = os.path.join(ROOT, "tests", "silica")

# expected stdout for each example (calculator needs stdin, handled below)
EXPECTED = {
    "hello.sc": "Hello from Silica\n",
    "square.sc": "144\n",
    "conditionals.sc": "Pass\n",
    "logic.sc": "Ready\n",
    "loops.sc": "55\n5 4 3 2 1 \n",
    "strings.sc": ("SILICA\nLANGUAGE\nBYTECODE\n"
                   "silica | language | bytecode\n"
                   "silica language bytecode\noui\n24\ns\n"),
    "collections.sc": ('[1, 3, 5, 9]\n[1, 9, 3, 5]\n18\n2\n31\noui\n'
                       'anita\nrahul\n["anita", "rahul"]\n["apple", "pear"]\n'),
    "math_demo.sc": "17\n3\n8\n9.0\n1024.0\n3\n4\n3\n3.141592653589793\n",
    "fibonacci.sc": "0 1 1 2 3 5 8 13 21 34 55 \n",
    "json_demo.sc": (
        "Map\n"
        '{"project":"silica","version":1,"stable":false,'
        '"tags":["compiler","bytecode"],"extra":null}\n'
        '{\n  "project":"silica",\n  "version":1,\n  "stable":false,\n'
        '  "tags":[\n    "compiler",\n    "bytecode"\n  ],\n  "extra":null\n}\n'
        "oui\n"
        '{"width":80,"ratio":1.5,"wrap":true,"tags":["a","b"]}\n'
        "[1, 2, 3]\n"),
}

# examples that need capability flags to run; the grant is the narrowest that
# works, which is the point of the example
GATED = {
    "fs_demo.sc": (["--allow-fs-read", EXAMPLES, "--allow-fs-list", EXAMPLES],
                   "oui\nsfn main() {\noui\nnein\n"),
}

# UI examples render into build/ and need fs.write for it. Their stdout is a list
# of absolute paths, so it is asserted by suffix rather than by equality.
UI_EXAMPLES = {
    "ui_hello.sc": "ui_hello.html",
    "ui_tasks.sc": "ui_tasks.html",
    "ui_animate.sc": "ui_animate.html",
}

CALCULATOR_INPUT = "12\n*\n4\n"
CALCULATOR_OUTPUT = "first number: operator (+ - * /): second number: 48.0\n"


def example_paths():
    if not os.path.isdir(EXAMPLES):
        return []
    return sorted(os.path.join(EXAMPLES, name) for name in os.listdir(EXAMPLES)
                  if name.endswith(".sc"))


class ExampleTests(unittest.TestCase):
    def test_examples_exist(self):
        names = {os.path.basename(p) for p in example_paths()}
        self.assertGreaterEqual(len(names), 8)
        self.assertIn("square.sc", names)

    def test_every_example_compiles_and_verifies(self):
        for path in example_paths():
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                compile_source(source, path)  # raises on any failure

    def test_documented_outputs(self):
        for name, expected in EXPECTED.items():
            path = os.path.join(EXAMPLES, name)
            with self.subTest(example=name):
                out = io.StringIO()
                with mock.patch("sys.stdin", io.StringIO("")), \
                        contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(["run", path])
                self.assertEqual(code, 0)
                self.assertEqual(out.getvalue(), expected)

    def test_gated_examples_need_their_capabilities(self):
        """Without the grant the program must fail, not quietly succeed."""
        for name in GATED:
            path = os.path.join(EXAMPLES, name)
            with self.subTest(example=name):
                err = io.StringIO()
                with mock.patch("sys.stdin", io.StringIO("")), \
                        contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(err):
                    code = cli.main(["run", path])
                self.assertEqual(code, 1)
                self.assertIn("capability error", err.getvalue())

    def test_gated_examples_with_capabilities(self):
        for name, (flags, expected) in GATED.items():
            path = os.path.join(EXAMPLES, name)
            with self.subTest(example=name):
                out = io.StringIO()
                with mock.patch("sys.stdin", io.StringIO("")), \
                        contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(["run", path] + flags)
                self.assertEqual(code, 0)
                self.assertEqual(out.getvalue(), expected)

    def test_calculator_subtraction_via_the_run_subcommand(self):
        """The brief's case: 4 - 2 -> 2.0."""
        path = os.path.join(EXAMPLES, "calculator.sc")
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("4\n-\n2\n")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["run", path])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(),
                         "first number: operator (+ - * /): second number: 2.0\n")

    def test_calculator_via_the_direct_form(self):
        """`silica calculator.sc` must behave exactly like `silica run ...`."""
        path = os.path.join(EXAMPLES, "calculator.sc")
        direct_out, sub_out = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("4\n-\n2\n")), \
                contextlib.redirect_stdout(direct_out), \
                contextlib.redirect_stderr(io.StringIO()):
            direct_code = cli.main([path])
        with mock.patch("sys.stdin", io.StringIO("4\n-\n2\n")), \
                contextlib.redirect_stdout(sub_out), \
                contextlib.redirect_stderr(io.StringIO()):
            sub_code = cli.main(["run", path])
        self.assertEqual(direct_code, 0)
        self.assertEqual(sub_code, 0)
        self.assertEqual(direct_out.getvalue(), sub_out.getvalue())
        self.assertIn("2.0", direct_out.getvalue())

    def test_calculator_division_and_divide_by_zero(self):
        path = os.path.join(EXAMPLES, "calculator.sc")
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("9\n/\n2\n")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main([path])
        self.assertIn("4.5", out.getvalue())

        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("1\n/\n0\n")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main([path])
        self.assertIn("cannot divide by zero", out.getvalue())

    def test_ui_examples_render(self):
        import shutil
        build = os.path.join(ROOT, "build")
        created = not os.path.isdir(build)
        os.makedirs(build, exist_ok=True)
        try:
            for name, artifact in UI_EXAMPLES.items():
                path = os.path.join(EXAMPLES, name)
                with self.subTest(example=name):
                    out = io.StringIO()
                    err = io.StringIO()
                    with mock.patch("sys.stdin", io.StringIO("")), \
                            contextlib.redirect_stdout(out), \
                            contextlib.redirect_stderr(err):
                        code = cli.main(["run", path, "--allow-fs-write", build])
                    self.assertEqual(code, 0, err.getvalue())
                    self.assertIn(artifact, out.getvalue())
                    produced = os.path.join(build, artifact)
                    self.assertTrue(os.path.exists(produced), produced)
                    with open(produced, encoding="utf-8") as handle:
                        html = handle.read()
                    self.assertIn("<!DOCTYPE html>", html)
                    self.assertIn("silica-ui-actions", html)
                    for shared in ("theme.css", "silica-ui-runtime.js"):
                        self.assertTrue(os.path.exists(os.path.join(build, shared)))
        finally:
            shutil.rmtree(build, ignore_errors=True)

    def test_ui_examples_need_the_write_capability(self):
        for name in UI_EXAMPLES:
            path = os.path.join(EXAMPLES, name)
            with self.subTest(example=name):
                err = io.StringIO()
                with mock.patch("sys.stdin", io.StringIO("")), \
                        contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(err):
                    code = cli.main(["run", path])
                self.assertEqual(code, 1)
                self.assertIn("capability error", err.getvalue())

    def test_calculator_reads_input(self):
        path = os.path.join(EXAMPLES, "calculator.sc")
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(CALCULATOR_INPUT)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["run", path])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), CALCULATOR_OUTPUT)


class FormattingTests(unittest.TestCase):
    def test_examples_are_canonically_formatted(self):
        for path in example_paths():
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                self.assertEqual(format_source(source, path), source)

    def test_silica_tests_are_canonically_formatted(self):
        for name in sorted(os.listdir(SILICA_TESTS)):
            if not name.endswith(".sc"):
                continue
            path = os.path.join(SILICA_TESTS, name)
            with self.subTest(test=name):
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                self.assertEqual(format_source(source, path), source)

    def test_formatting_is_idempotent(self):
        source = ("sfn f(a: Int,b: Int)->Int{\nret a+b\n}\n"
                  "sfn main(){\nlet x:Int=f(1,2)\nsprint(x)\n}\n")
        once = format_source(source)
        self.assertEqual(format_source(once), once)


class SilicaTestSuiteTests(unittest.TestCase):
    def test_silica_level_tests_pass(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["test", SILICA_TESTS])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("5/5 test files passed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
