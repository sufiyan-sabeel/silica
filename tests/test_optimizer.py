"""Constant folding: a differential test, not a table of expected values.

The claim being tested is narrow and checkable: for any expression, compiling with
folding on and with folding off produces the same stdout, the same stderr and the
same exit code. `SILICA_NO_OPT=1` disables folding, so both sides use the same
compiler, parser, checker and VM — only the optimisation differs.

A hand-written table of expected values would only prove that the table matches
the optimiser's own arithmetic. This compares against the VM instead.
"""

import io
import os
import subprocess
import sys
import unittest
from unittest import mock

from silica import optimizer
from silica.engine import compile_source, run_chunk
from silica.errors import SilicaError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every expression is compiled into its own program so one failure cannot mask
# another, and so the stderr location is comparable too.
EXPRESSIONS = [
    # integers
    "2 + 3", "2 - 3", "2 * 3", "7 / 2", "-7 / 2", "7 / -2", "0 - 5",
    "-(-5)", "2 + 3 * 4", "(2 + 3) * 4", "1 + 1 + 1 + 1",
    # overflow: the VM wraps at 64 bits, so folding must too
    "9223372036854775807 + 1", "-9223372036854775808 - 1",
    "4611686018427387904 * 4",
    # floats
    "1.5 + 2.5", "1.5 * 2.0", "0.1 + 0.2", "1.0 / 4.0", "-2.5 - 1.5",
    # mixed: the VM promotes to Float
    "1 + 2.5", "2.5 * 2", "7 / 2.0",
    # strings
    '"a" + "b"', '"a" + "b" + "c"', '"" + "x"',
    # booleans and unary
    "non oui", "non nein", "non (1 == 1)",
    # division by zero: must stay a runtime error, with its location intact
    "1 / 0", "1.0 / 0.0", "1 / (2 - 2)",
    # things that must NOT fold and must still error the same way
    '"a" - "b"', "oui + 1", "oui * 2",
]

PROGRAM = "sfn main() {\n    sprint(%s)\n}\n"


def run_source(source):
    """(stdout, error-or-None) with folding as configured in the environment."""
    out = io.StringIO()
    try:
        chunk = compile_source(source, "<test>").chunk
        run_chunk(chunk, "<test>", stdin=io.StringIO(""), stdout=out,
                  stderr=io.StringIO())
    except SilicaError as exc:
        return out.getvalue(), (type(exc).__name__, exc.format())
    return out.getvalue(), None


class DifferentialTests(unittest.TestCase):
    def test_folding_never_changes_behaviour(self):
        for expression in EXPRESSIONS:
            with self.subTest(expression=expression):
                source = PROGRAM % expression
                with mock.patch.dict(os.environ, {"SILICA_NO_OPT": "1"}):
                    off = run_source(source)
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("SILICA_NO_OPT", None)
                    on = run_source(source)
                self.assertEqual(on, off,
                                 "folding changed the result of %r" % expression)

    def test_the_expected_values_are_what_the_vm_produces(self):
        """A few hand-checked values, so a double bug cannot cancel out."""
        cases = {
            "2 + 3 * 4": "14\n",
            '"a" + "b" + "c"': "abc\n",
            "7 / 2": "3\n",
            "-7 / 2": "-3\n",
            "7 / -2": "-3\n",
            "1 + 2.5": "3.5\n",
            "9223372036854775807 + 1": "-9223372036854775808\n",
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                out, error = run_source(PROGRAM % expression)
                self.assertIsNone(error)
                self.assertEqual(out, expected)

    def test_division_by_zero_keeps_its_location(self):
        _out, error = run_source(PROGRAM % "1 / 0")
        self.assertIsNotNone(error)
        kind, message = error
        self.assertEqual(kind, "SilicaRuntimeError")
        self.assertIn("division by zero", message)
        self.assertIn("<test>:2", message)

    def test_type_errors_are_still_type_errors(self):
        """These are caught by the checker, so folding never reaches them."""
        for expression in ('"a" - "b"', "oui + 1", "oui * 2"):
            with self.subTest(expression=expression):
                _out, error = run_source(PROGRAM % expression)
                self.assertIsNotNone(error, "%r should fail" % expression)
                self.assertEqual(error[0], "SilicaTypeError")
                self.assertTrue("expects numbers" in error[1]
                                or "cannot add" in error[1], error[1])


class FoldUnitTests(unittest.TestCase):
    """The folder itself, independent of the compiler."""

    def fold(self, source):
        from silica.lexer import tokenize
        from silica.parser import parse
        program = parse(tokenize(PROGRAM % source)[0], "<t>")
        func = program.stmts[0]
        call = func.body.stmts[0].expr
        return optimizer.fold(call.args[0])

    def test_it_folds_plain_arithmetic(self):
        self.assertEqual(self.fold("2 + 3"), (5, "Int"))

    def test_it_wraps_like_the_vm(self):
        self.assertEqual(self.fold("9223372036854775807 + 1"),
                         (-9223372036854775808, "Int"))

    def test_it_refuses_division_by_zero(self):
        self.assertEqual(self.fold("1 / 0"), optimizer.UNKNOWN)

    def test_it_refuses_mismatched_types(self):
        self.assertEqual(self.fold('"a" - "b"'), optimizer.UNKNOWN)
        self.assertEqual(self.fold("oui + 1"), optimizer.UNKNOWN)

    def test_it_promotes_like_the_vm(self):
        self.assertEqual(self.fold("1 + 2.5"), (3.5, "Float"))

    def test_it_concatenates_strings(self):
        self.assertEqual(self.fold('"a" + "b"'), ("ab", "String"))


class CodeSizeTests(unittest.TestCase):
    """The point of folding is fewer instructions and less work at run time."""

    def instructions(self, source):
        chunk = compile_source(source, "<test>").chunk
        total = 0
        for fn in chunk.functions:
            from silica.bytecode import decode
            total += len(decode(fn.code, "<test>", fn.name))
        return total

    def test_folding_removes_instructions(self):
        source = PROGRAM % "(1 + 2) * (3 + 4) - 5"
        with mock.patch.dict(os.environ, {"SILICA_NO_OPT": "1"}):
            before = self.instructions(source)
        os.environ.pop("SILICA_NO_OPT", None)
        after = self.instructions(source)
        self.assertLess(after, before,
                        "folding should emit fewer instructions (%d vs %d)"
                        % (after, before))

    def test_a_folded_program_is_smaller_on_disk(self):
        source = "sfn main() {\n" + "".join(
            "    sprint(%d + %d * %d)\n" % (i, i + 1, i + 2) for i in range(40)
        ) + "}\n"
        with mock.patch.dict(os.environ, {"SILICA_NO_OPT": "1"}):
            from silica.bytecode import serialize
            big = len(serialize(compile_source(source, "<t>").chunk))
        os.environ.pop("SILICA_NO_OPT", None)
        from silica.bytecode import serialize
        small = len(serialize(compile_source(source, "<t>").chunk))
        self.assertLess(small, big)


class RegressionTests(unittest.TestCase):
    """Folding must not disturb programs that have nothing to fold."""

    def test_the_examples_still_run(self):
        examples = os.path.join(ROOT, "examples")
        for name in sorted(os.listdir(examples)):
            if not name.endswith(".sc"):
                continue
            if name in ("calculator.sc", "fs_demo.sc", "tui_demo.sc",
                        "gui_demo.sc", "ui_tasks.sc", "ui_hello.sc",
                        "ui_animate.sc"):
                continue  # these need stdin, capabilities or a display
            with self.subTest(example=name):
                completed = subprocess.run(
                    [sys.executable, "-m", "silica", "run",
                     os.path.join(examples, name)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    cwd=ROOT, timeout=120)
                self.assertEqual(completed.returncode, 0, completed.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
