"""Loop control: `break` and `continue`.

Added in 0.9.0. These tests cover the whole path — lexer, parser, checker,
compiler, verifier and VM — because a loop jump that is only half-implemented
tends to *look* right until it is compiled to bytecode and verified.
"""

import io
import os
import unittest

from silica import ast
from silica.engine import run_chunk
from silica.errors import ParseError, SilicaTypeError
from silica.fmt import format_source
from silica.lexer import tokenize
from silica.parser import parse

from .helpers import (bytecode_roundtrip, check_source, compile_chunk,
                      expect_error, run)


def out(source, stdin=""):
    return run(source, stdin=stdin)[1]


def program(body, decls=""):
    return decls + "sfn main() {\n" + body + "\n}\n"


def parse_source(source):
    tokens, _ = tokenize(source)
    return parse(tokens)


class WhileBreakTests(unittest.TestCase):
    def test_break_leaves_the_loop_immediately(self):
        source = program("let i = 0\n"
                         "tant oui {\n"
                         "    i = i + 1\n"
                         "    si i == 3 {\n"
                         "        break\n"
                         "    }\n"
                         "}\n"
                         "sprint(i)")
        self.assertEqual(out(source), "3\n")

    def test_break_stops_the_remaining_body(self):
        source = program("per n in [1, 2, 3, 4] {\n"
                         "    si n == 3 {\n"
                         "        break\n"
                         "    }\n"
                         "    sprint(n)\n"
                         "}\n"
                         "sprint(\"done\")")
        self.assertEqual(out(source), "1\n2\ndone\n")

    def test_break_is_the_only_statement_in_the_body(self):
        source = program("tant oui {\n    break\n}\nsprint(\"after\")")
        self.assertEqual(out(source), "after\n")

    def test_break_skips_an_empty_body_immediately(self):
        # the loop condition is true, so without `break` this would not terminate
        source = program("let seen = 0\n"
                         "tant oui {\n"
                         "    seen = seen + 1\n"
                         "    break\n"
                         "}\n"
                         "sprint(seen)")
        self.assertEqual(out(source), "1\n")


class WhileContinueTests(unittest.TestCase):
    def test_continue_skips_the_rest_of_the_body(self):
        source = program("let i = 0\n"
                         "let total = 0\n"
                         "tant i < 6 {\n"
                         "    i = i + 1\n"
                         "    si i % 2 == 0 {\n"
                         "        continue\n"
                         "    }\n"
                         "    total = total + i\n"
                         "}\n"
                         "sprint(total)")
        self.assertEqual(out(source), "9\n")

    def test_continue_re_tests_the_condition(self):
        # `continue` must jump back to the condition, not past it, or this
        # loop would run forever
        source = program("let i = 0\n"
                         "tant i < 3 {\n"
                         "    i = i + 1\n"
                         "    continue\n"
                         "}\n"
                         "sprint(i)")
        self.assertEqual(out(source), "3\n")

    def test_continue_does_not_skip_the_increment_when_it_is_written_first(self):
        source = program("let i = 0\n"
                         "let n = 0\n"
                         "tant i < 4 {\n"
                         "    i = i + 1\n"
                         "    n = n + 1\n"
                         "    si n == 2 {\n"
                         "        continue\n"
                         "    }\n"
                         "}\n"
                         "sprint(i)")
        self.assertEqual(out(source), "4\n")


class ForBreakTests(unittest.TestCase):
    def test_break_in_a_list_loop(self):
        source = program("per n in [10, 20, 30] {\n"
                         "    si n == 20 {\n"
                         "        break\n"
                         "    }\n"
                         "    sprint(n)\n"
                         "}")
        self.assertEqual(out(source), "10\n")

    def test_break_in_a_string_loop(self):
        source = program("per ch in \"abcd\" {\n"
                         "    si ch == \"c\" {\n"
                         "        break\n"
                         "    }\n"
                         "    sprint(ch)\n"
                         "}")
        self.assertEqual(out(source), "a\nb\n")

    def test_break_in_a_map_loop(self):
        source = program("let m = {\"a\": 1, \"b\": 2}\n"
                         "per key in m {\n"
                         "    sprint(key)\n"
                         "    break\n"
                         "}")
        self.assertEqual(out(source), "a\n")

    def test_continue_in_a_for_loop(self):
        source = program("per n in [1, 2, 3, 4] {\n"
                         "    si n % 2 == 0 {\n"
                         "        continue\n"
                         "    }\n"
                         "    sprint(n)\n"
                         "}")
        self.assertEqual(out(source), "1\n3\n")

    def test_break_leaves_no_iterator_on_the_stack(self):
        # a `per` loop keeps its iterator on the value stack, so `break` has to
        # pop it; if it did not, the verifier would reject the code and the
        # second call below would see a corrupted stack
        decls = ("sfn firstTwo(items: List) -> List {\n"
                 "    let picked = []\n"
                 "    per item in items {\n"
                 "        si len(picked) == 2 {\n"
                 "            break\n"
                 "        }\n"
                 "        push(picked, item)\n"
                 "    }\n"
                 "    ret picked\n"
                 "}\n")
        source = program("sprint(firstTwo([1, 2, 3, 4]))\n"
                         "sprint(firstTwo([5, 6, 7]))", decls)
        self.assertEqual(out(source), "[1, 2]\n[5, 6]\n")

    def test_break_in_an_empty_collection_body_never_runs(self):
        source = program("per n in [] {\n    break\n}\nsprint(\"empty\")")
        self.assertEqual(out(source), "empty\n")


class NestedLoopTests(unittest.TestCase):
    def test_break_only_leaves_the_inner_loop(self):
        source = program("per a in [1, 2] {\n"
                         "    per b in [1, 2, 3] {\n"
                         "        si b == 2 {\n"
                         "            break\n"
                         "        }\n"
                         "        sprint(a * 10 + b)\n"
                         "    }\n"
                         "}")
        self.assertEqual(out(source), "11\n21\n")

    def test_continue_only_affects_the_inner_loop(self):
        source = program("per a in [1, 2] {\n"
                         "    per b in [1, 2] {\n"
                         "        si b == 1 {\n"
                         "            continue\n"
                         "        }\n"
                         "        sprint(a * 10 + b)\n"
                         "    }\n"
                         "}")
        self.assertEqual(out(source), "12\n22\n")

    def test_break_out_of_a_while_nested_in_a_for(self):
        source = program("per a in [1, 2] {\n"
                         "    let i = 0\n"
                         "    tant oui {\n"
                         "        i = i + 1\n"
                         "        si i == 2 {\n"
                         "            break\n"
                         "        }\n"
                         "    }\n"
                         "    sprint(a * 10 + i)\n"
                         "}")
        self.assertEqual(out(source), "12\n22\n")

    def test_break_out_of_a_for_nested_in_a_while(self):
        source = program("let total = 0\n"
                         "let rounds = 0\n"
                         "tant rounds < 3 {\n"
                         "    rounds = rounds + 1\n"
                         "    per n in [1, 2, 3] {\n"
                         "        si n == 2 {\n"
                         "            break\n"
                         "        }\n"
                         "        total = total + n\n"
                         "    }\n"
                         "}\n"
                         "sprint(total)")
        self.assertEqual(out(source), "3\n")


class InteractionTests(unittest.TestCase):
    def test_break_inside_a_function_loop(self):
        decls = ("sfn firstEven(items: List) -> Int {\n"
                 "    per n in items {\n"
                 "        si n % 2 == 0 {\n"
                 "            ret n\n"
                 "        }\n"
                 "    }\n"
                 "    ret 0 - 1\n"
                 "}\n")
        self.assertEqual(out(program("sprint(firstEven([1, 3, 4, 6]))", decls)), "4\n")

    def test_break_inside_a_conditional_inside_a_loop(self):
        source = program("per n in [1, 2, 3] {\n"
                         "    si n > 0 {\n"
                         "        si n == 2 {\n"
                         "            break\n"
                         "        } sino {\n"
                         "            sprint(n)\n"
                         "        }\n"
                         "    }\n"
                         "}")
        self.assertEqual(out(source), "1\n")

    def test_loop_jumps_survive_the_optimizer_both_ways(self):
        # folding must not change loop control; compile with and without it
        source = program("let acc = []\n"
                         "per n in [1, 2, 3, 4] {\n"
                         "    si n == 2 + 2 {\n"
                         "        break\n"
                         "    }\n"
                         "    si n == 1 + 1 {\n"
                         "        continue\n"
                         "    }\n"
                         "    push(acc, n * (1 + 1))\n"
                         "}\n"
                         "sprint(acc)")
        previous = os.environ.get("SILICA_NO_OPT")
        try:
            os.environ.pop("SILICA_NO_OPT", None)
            folded = out(source)
            os.environ["SILICA_NO_OPT"] = "1"
            unfolded = out(source)
        finally:
            os.environ.pop("SILICA_NO_OPT", None)
            if previous is not None:
                os.environ["SILICA_NO_OPT"] = previous
        self.assertEqual(folded, unfolded)
        # 1 -> pushed as 2, 2 -> continue, 3 -> pushed as 6, 4 -> break
        self.assertEqual(folded, "[2, 6]\n")

    def test_loop_jumps_survive_bytecode_serialisation(self):
        source = program("let s = 0\n"
                         "per n in [1, 2, 3, 4, 5] {\n"
                         "    si n == 4 {\n"
                         "        break\n"
                         "    }\n"
                         "    si n % 2 == 0 {\n"
                         "        continue\n"
                         "    }\n"
                         "    s = s + n\n"
                         "}\n"
                         "sprint(s)")
        chunk = compile_chunk(source)
        restored, _data = bytecode_roundtrip(chunk)
        buffer = io.StringIO()
        code = run_chunk(restored, "<restored>", stdin=io.StringIO(""),
                         stdout=buffer, stderr=io.StringIO())
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "4\n")


class DiagnosticsTests(unittest.TestCase):
    def test_break_outside_a_loop_is_rejected(self):
        error = expect_error(self, program("break"), SilicaTypeError,
                             "'break' is only allowed inside a loop")
        self.assertIn("tant", error.hint)

    def test_continue_outside_a_loop_is_rejected(self):
        expect_error(self, program("continue"), SilicaTypeError,
                     "'continue' is only allowed inside a loop")

    def test_break_in_a_function_without_a_loop_is_rejected(self):
        # the loop counter does not leak across a function boundary
        source = ("sfn helper() {\n    break\n}\n"
                  "sfn main() {\n    tant oui {\n        helper()\n        break\n    }\n}\n")
        expect_error(self, source, SilicaTypeError,
                     "'break' is only allowed inside a loop")

    def test_break_at_the_top_level_is_rejected(self):
        expect_error(self, "break\n", SilicaTypeError,
                     "top level")

    def test_break_inside_a_builder_block_is_rejected(self):
        source = ("use ui\n"
                  "sfn main() {\n"
                  "    tant oui {\n"
                  "        ui.card() {\n"
                  "            break\n"
                  "        }\n"
                  "    }\n"
                  "}\n")
        expect_error(self, source, SilicaTypeError,
                     "'break' inside a builder block is not allowed")

    def test_break_is_a_keyword_and_cannot_be_a_variable(self):
        with self.assertRaises(ParseError):
            parse_source(program("let break = 1"))

    def test_error_reports_the_line_of_the_jump(self):
        source = ("sfn main() {\n"
                  "    let x = 1\n"
                  "    break\n"
                  "}\n")
        error = expect_error(self, source, SilicaTypeError,
                             "only allowed inside a loop")
        self.assertEqual(error.line, 3)


class ParserAndFormatterTests(unittest.TestCase):
    def test_break_parses_to_a_break_statement(self):
        parsed = parse_source(program("tant oui {\n    break\n}"))
        loop = parsed.stmts[0].body.stmts[0]
        self.assertIsInstance(loop, ast.WhileStmt)
        self.assertIsInstance(loop.body.stmts[0], ast.BreakStmt)

    def test_continue_parses_to_a_continue_statement(self):
        parsed = parse_source(program("per n in [1] {\n    continue\n}"))
        loop = parsed.stmts[0].body.stmts[0]
        self.assertIsInstance(loop, ast.ForStmt)
        self.assertIsInstance(loop.body.stmts[0], ast.ContinueStmt)

    def test_statement_locations_are_recorded(self):
        parsed = parse_source(program("per n in [1] {\n    continue\n}"))
        stmt = parsed.stmts[0].body.stmts[0].body.stmts[0]
        self.assertEqual(stmt.line, 3)
        self.assertEqual(stmt.col, 5)

    def test_formatter_round_trips_loop_jumps(self):
        source = program("per n in [1, 2, 3] {\n"
                         "    si n == 2 {\n"
                         "        continue\n"
                         "    }\n"
                         "    si n == 3 {\n"
                         "        break\n"
                         "    }\n"
                         "    sprint(n)\n"
                         "}")
        formatted = format_source(source)
        self.assertIn("        continue", formatted)
        self.assertIn("        break", formatted)
        self.assertEqual(format_source(formatted), formatted)

    def test_formatted_output_still_runs_the_same_way(self):
        source = program("per n in [1, 2, 3, 4] {\n"
                         "    si n == 2 {\n"
                         "        continue\n"
                         "    }\n"
                         "    si n == 4 {\n"
                         "        break\n"
                         "    }\n"
                         "    sprint(n)\n"
                         "}")
        self.assertEqual(out(format_source(source)), out(source))

    def test_check_source_accepts_loop_jumps(self):
        check_source(program("tant oui {\n    break\n}"))
        check_source(program("per n in [1] {\n    continue\n}"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
