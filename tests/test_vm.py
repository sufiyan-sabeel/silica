"""VM semantics tests: values, operators, control flow, calls and errors."""

import unittest

from silica.errors import SilicaRuntimeError
from silica.natives import i64

from .helpers import run


def out(source, stdin=""):
    return run(source, stdin=stdin)[1]


def program(body, decls=""):
    return decls + "sfn main() {\n" + body + "\n}\n"


class ValueTests(unittest.TestCase):
    def test_sprint_renders_each_type(self):
        self.assertEqual(out(program('sprint(42)')), "42\n")
        self.assertEqual(out(program('sprint(1.5)')), "1.5\n")
        self.assertEqual(out(program('sprint(2.0)')), "2.0\n")
        self.assertEqual(out(program('sprint(oui)')), "oui\n")
        self.assertEqual(out(program('sprint(nein)')), "nein\n")
        self.assertEqual(out(program('sprint("hi")')), "hi\n")
        self.assertEqual(out(program('sprint([1, 2])')), "[1, 2]\n")
        self.assertEqual(out(program('sprint({"a": 1})')), '{"a": 1}\n')
        self.assertEqual(out(program('sprint(type_of(1))')), "Int\n")

    def test_dit_writes_without_newline(self):
        self.assertEqual(out(program('dit("a")\ndit("b")\nsprint("c")')), "abc\n")

    def test_unit_prints_as_unit(self):
        self.assertEqual(out(program('sprint(push([], 1))')), "unit\n")

    def test_type_of(self):
        body = ('sprint(type_of(1))\nsprint(type_of(1.0))\nsprint(type_of("s"))\n'
                'sprint(type_of(oui))\nsprint(type_of([1]))\nsprint(type_of({"a":1}))')
        self.assertEqual(out(program(body)), "Int\nFloat\nString\nBool\nList\nMap\n")


class ArithmeticTests(unittest.TestCase):
    def test_integer_arithmetic(self):
        self.assertEqual(out(program("sprint(7 + 3)\nsprint(7 - 3)\nsprint(7 * 3)")),
                         "10\n4\n21\n")

    def test_integer_division_truncates_toward_zero(self):
        self.assertEqual(out(program("sprint(7 / 2)\nsprint(-7 / 2)\nsprint(7 / -2)")),
                         "3\n-3\n-3\n")

    def test_modulo_keeps_dividend_sign(self):
        self.assertEqual(out(program("sprint(7 % 2)\nsprint(-7 % 2)\nsprint(7 % -2)")),
                         "1\n-1\n1\n")

    def test_float_arithmetic(self):
        self.assertEqual(out(program("sprint(1.5 + 2.5)\nsprint(7.0 / 2.0)")),
                         "4.0\n3.5\n")

    def test_mixed_arithmetic_promotes_to_float(self):
        self.assertEqual(out(program("sprint(1 + 2.5)")), "3.5\n")

    def test_integer_overflow_wraps(self):
        self.assertEqual(i64(2 ** 63), -(2 ** 63))
        self.assertEqual(
            out(program("let big: Int = 9223372036854775807\nsprint(big + 1)")),
            "-9223372036854775808\n")

    def test_unary_minus(self):
        self.assertEqual(out(program("sprint(-5)\nsprint(-(-5))")), "-5\n5\n")

    def test_division_by_zero_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program("sprint(1 / 0)"))
        self.assertIn("division by zero", ctx.exception.message)

    def test_modulo_by_zero_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError):
            run(program("sprint(1 % 0)"))

    def test_float_division_by_zero_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError):
            run(program("sprint(1.0 / 0.0)"))


class ComparisonTests(unittest.TestCase):
    def test_numeric_comparisons(self):
        self.assertEqual(out(program("sprint(1 < 2)\nsprint(2 <= 2)\nsprint(3 > 4)")),
                         "oui\noui\nnein\n")

    def test_cross_type_equality(self):
        self.assertEqual(out(program("sprint(1 == 1.0)\nsprint(1 != 1.0)")),
                         "oui\nnein\n")

    def test_string_ordering(self):
        self.assertEqual(out(program('sprint("a" < "b")')), "oui\n")

    def test_structural_equality(self):
        self.assertEqual(out(program("sprint([1, 2] == [1, 2])\n"
                                     "sprint({\"a\": 1} == {\"a\": 1})")),
                         "oui\noui\n")


class LogicTests(unittest.TestCase):
    def test_short_circuit_and(self):
        # `f()` must not run when the left side is false
        decls = "sfn f() -> Bool {\n sprint(\"side effect\")\n ret oui\n}\n"
        self.assertEqual(out(program("sprint(nein und f())", decls)), "nein\n")
        self.assertEqual(out(program("sprint(oui und f())", decls)),
                         "side effect\noui\n")

    def test_short_circuit_or(self):
        decls = "sfn f() -> Bool {\n sprint(\"side effect\")\n ret nein\n}\n"
        self.assertEqual(out(program("sprint(oui ou f())", decls)), "oui\n")
        self.assertEqual(out(program("sprint(nein ou f())", decls)),
                         "side effect\nnein\n")

    def test_not(self):
        self.assertEqual(out(program("sprint(non oui)\nsprint(non nein)")),
                         "nein\noui\n")


class ControlFlowTests(unittest.TestCase):
    def test_if_else(self):
        body = 'let n: Int = 5\nsi n > 3 {\n sprint("big")\n} sino {\n sprint("small")\n}'
        self.assertEqual(out(program(body)), "big\n")

    def test_while_loop(self):
        body = "let i: Int = 0\ntant i < 3 {\n i = i + 1\n}\nsprint(i)"
        self.assertEqual(out(program(body)), "3\n")

    def test_for_over_list(self):
        body = "let total: Int = 0\nper x in [1, 2, 3] {\n total = total + x\n}\nsprint(total)"
        self.assertEqual(out(program(body)), "6\n")

    def test_for_over_string(self):
        body = 'let s: String = ""\nper ch in "abc" {\n s = s + ch + "-"\n}\nsprint(s)'
        self.assertEqual(out(program(body)), "a-b-c-\n")

    def test_for_over_map_keys(self):
        body = 'per k in {"x": 1, "y": 2} {\n sprint(k)\n}'
        self.assertEqual(out(program(body)), "x\ny\n")

    def test_nested_loops(self):
        body = ("let n: Int = 0\nper i in range(3) {\n per j in range(3) {\n"
                "  n = n + 1\n }\n}\nsprint(n)")
        self.assertEqual(out(program(body)), "9\n")

    def test_halt_stops_execution(self):
        code, text = run(program('sprint("a")\nhalt(4)\nsprint("b")'))
        self.assertEqual(text, "a\n")
        self.assertEqual(code, 4)

    def test_halt_without_code_is_zero(self):
        code, _ = run(program("halt"))
        self.assertEqual(code, 0)


class FunctionTests(unittest.TestCase):
    def test_recursion(self):
        decls = ("sfn fact(n: Int) -> Int {\n si n <= 1 {\n  ret 1\n }\n"
                 " ret n * fact(n - 1)\n}\n")
        self.assertEqual(out(program("sprint(fact(5))", decls)), "120\n")

    def test_deep_recursion_is_bounded(self):
        decls = "sfn down(n: Int) -> Int {\n si n == 0 {\n  ret 0\n }\n ret down(n - 1)\n}\n"
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program("sprint(down(100000))", decls))
        self.assertIn("call stack overflow", ctx.exception.message)

    def test_arguments_are_evaluated_in_order(self):
        decls = ('sfn tag(n: Int) -> Int {\n dit(n)\n ret n\n}\n'
                 'sfn pair(a: Int, b: Int) -> Int {\n ret a + b\n}\n')
        # tag() prints its argument, so "1", "2" appear before the sum "3"
        self.assertEqual(out(program("sprint(pair(tag(1), tag(2)))", decls)),
                         "123\n")

    def test_globals_are_initialised_before_main(self):
        source = 'let greeting: String = "hello"\n' + program("sprint(greeting)")
        self.assertEqual(out(source), "hello\n")

    def test_globals_mutable_from_functions(self):
        source = ('let counter: Int = 0\n'
                  'sfn bump() {\n counter = counter + 1\n}\n' +
                  program("bump()\nbump()\nsprint(counter)"))
        self.assertEqual(out(source), "2\n")

    def test_unit_function_returns_unit(self):
        decls = "sfn nothing() {\n}\n"
        self.assertEqual(out(program("sprint(nothing())", decls)), "unit\n")


class CollectionTests(unittest.TestCase):
    def test_list_indexing_and_len(self):
        body = "let xs: List = [10, 20, 30]\nsprint(xs[1])\nsprint(len(xs))"
        self.assertEqual(out(program(body)), "20\n3\n")

    def test_list_concatenation(self):
        self.assertEqual(out(program("sprint([1] + [2])")), "[1, 2]\n")

    def test_map_lookup_and_len(self):
        body = 'let m: Map = {"a": 1}\nsprint(m["a"])\nsprint(len(m))'
        self.assertEqual(out(program(body)), "1\n1\n")

    def test_index_out_of_range(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program("sprint([1][3])"))
        self.assertIn("out of range", ctx.exception.message)

    def test_missing_map_key(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint({"a": 1}["b"])'))
        self.assertIn("not found", ctx.exception.message)

    def test_string_indexing(self):
        self.assertEqual(out(program('sprint("abc"[1])')), "b\n")


class NativeTests(unittest.TestCase):
    def test_range_forms(self):
        self.assertEqual(out(program("sprint(range(3))")), "[0, 1, 2]\n")
        self.assertEqual(out(program("sprint(range(2, 5))")), "[2, 3, 4]\n")
        self.assertEqual(out(program("sprint(range(0, 10, 3))")), "[0, 3, 6, 9]\n")

    def test_range_zero_step_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError):
            run(program("sprint(range(0, 5, 0))"))

    def test_push_mutates_in_place(self):
        body = "let xs: List = []\npush(xs, 1)\npush(xs, 2)\nsprint(xs)"
        self.assertEqual(out(program(body)), "[1, 2]\n")

    def test_input_reads_a_line(self):
        self.assertEqual(out(program('let name: String = input("")\nsprint(name)'),
                             stdin="Riyaz\n"), "Riyaz\n")

    def test_input_at_eof_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(input(""))'), stdin="")
        self.assertIn("end of input", ctx.exception.message)

    def test_input_prompt_is_written(self):
        self.assertEqual(out(program('sprint(input("name? "))'), stdin="x\n"),
                         "name? x\n")

    def test_string_module(self):
        decls = "use string\n"
        body = ('sprint(string.split("a,b", ","))\nsprint(string.join(["a"], "-"))\n'
                'sprint(string.trim("  x "))\nsprint(string.contains("abc", "b"))')
        self.assertEqual(out(program(body, decls)),
                         '["a", "b"]\na\nx\noui\n')

    def test_math_module(self):
        decls = "use math\n"
        body = ("sprint(math.abs(-2))\nsprint(math.floor(2.9))\nsprint(math.ceil(2.1))\n"
                "sprint(math.round(2.5))\nsprint(math.min(2, 3))\nsprint(math.max(2, 3))")
        self.assertEqual(out(program(body, decls)), "2\n2\n3\n3\n2\n3\n")

    def test_math_pi_is_a_float_constant(self):
        self.assertTrue(out(program("sprint(math.pi)", "use math\n")).startswith("3.14"))

    def test_collections_module(self):
        decls = "use collections\n"
        body = ("sprint(collections.sort([3, 1, 2]))\n"
                "sprint(collections.reverse([1, 2]))\n"
                "sprint(collections.sum([1, 2, 3]))\n"
                "sprint(collections.index_of([1, 2], 2))")
        self.assertEqual(out(program(body, decls)), "[1, 2, 3]\n[2, 1]\n6\n1\n")

    def test_assert_passes_and_fails(self):
        self.assertEqual(out(program("assert(oui)\nsprint(\"ok\")")), "ok\n")
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('assert(nein, "custom")'))
        self.assertIn("custom", ctx.exception.message)

    def test_str_and_int_conversions(self):
        self.assertEqual(out(program('sprint(int("42") + 1)')), "43\n")
        self.assertEqual(out(program('sprint(str(1.5))')), "1.5\n")


if __name__ == "__main__":
    unittest.main()
