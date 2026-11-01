"""Cases promoted from the pre-merge generics audit (`tools/audit_generics.py`).

`tests/test_generics.py` already covers the core rules; this module holds only
the audit cases that were **not** covered there — deep nesting, inference chains,
method dispatch between classes, a few diagnostics, formatter round-trips with
private/static members, and generics meeting natives and other types.

The audit tool stays outside `tests/` on purpose: it is a broad sweep to run by
hand before a merge, not a second copy of the suite.
"""

import unittest

from silica.checker import Checker
from silica.errors import ParseError, SilicaTypeError
from silica.fmt import format_program
from silica.lexer import tokenize
from silica.parser import parse

from .helpers import run


def check(source):
    prog = parse(tokenize(source)[0])
    Checker(prog).check()
    return prog


def program(body, decls=""):
    return decls + "sfn main() {\n" + body + "\n}\n"


BOX = "struct Box<T> {\n    v: T\n}\n\n"


class AuditCase(unittest.TestCase):
    def assertTypeError(self, source, fragment):
        with self.assertRaises(SilicaTypeError) as ctx:
            check(source)
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    def assertParseError(self, source, fragment):
        with self.assertRaises(ParseError) as ctx:
            parse(tokenize(source)[0])
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    def assertRuns(self, source, expected):
        code, out = run(source)
        self.assertEqual((code, out), (0, expected))


class NestedContainerTests(AuditCase):
    """Container types inside one another."""

    def test_a_list_of_lists_indexes_twice(self):
        self.assertTypeError(
            program("let xs: List<List<Int>> = [[1]]\nlet s: String = xs[0][0]"),
            "cannot initialise String")
        check(program("let xs: List<List<Int>> = [[1]]\n"
                      "let inner: List<Int> = xs[0]\nlet n: Int = xs[0][0]"))

    def test_a_map_of_maps_indexes_twice(self):
        self.assertRuns(program('let m: Map<String, Map<String, Int>> = '
                                '{"a": {"b": 1}}\nsprint(m["a"]["b"])'), "1\n")

    def test_three_levels_deep(self):
        self.assertRuns(program('let m: Map<String, List<Map<String, Int>>> = '
                                '{"a": [{"b": 1}]}\nsprint(m["a"][0]["b"])'), "1\n")

    def test_a_nested_element_keeps_its_type(self):
        self.assertTypeError(
            program('let m: Map<String, List<Int>> = {"a": [1, 2]}\n'
                    'let s: String = m["a"][1]'),
            "cannot initialise String")

    def test_arity_is_reported_at_depth(self):
        self.assertTypeError(program("let m: Map<String, List<Int, Int>> = {}"),
                             "List expects 0 or 1 type argument(s)")

    def test_a_struct_may_hold_a_list_of_itself(self):
        # the self-containment rule forbids a direct cycle, not a List of them
        self.assertRuns("struct Tree {\n    kids: List<Tree>\n}\n" +
                        program("let t: Tree = Tree([])\nsprint(len(t.kids))"),
                        "0\n")

    def test_nested_lists_as_a_parameter_and_return(self):
        decls = ("sfn flatten(xs: List<List<Int>>) -> List<Int> {\n"
                 "    let out: List<Int> = []\n"
                 "    per row in xs {\n        per v in row {\n"
                 "            push(out, v)\n        }\n    }\n    ret out\n}\n\n")
        self.assertRuns(decls + program("let xs: List<List<Int>> = [[1, 2], [3]]\n"
                                        "sprint(flatten(xs))"), "[1, 2, 3]\n")

    def test_iterating_a_map_yields_its_key_type(self):
        check(program('let m: Map<String, List<Int>> = {"a": [1]}\n'
                      'per key in m {\n    let k: String = key\n}'))
        self.assertTypeError(
            program('let m: Map<String, List<Int>> = {"a": [1]}\n'
                    'per key in m {\n    let n: Int = key\n}'),
            "cannot initialise Int")


class InferenceChainTests(AuditCase):
    """Inference across more than one expression."""

    def test_inference_through_a_nested_literal(self):
        decls = "sfn flat<T>(x: List<List<T>>) -> List<T> {\n    ret x[0]\n}\n\n"
        self.assertRuns(decls + program('sprint(flat([["a"]]))'), '["a"]\n')

    def test_an_annotation_of_the_wrong_shape_is_rejected(self):
        decls = "class S<T> {\n    items: List<T>\n}\n\n"
        self.assertTypeError(decls + program('let s: S<Int> = S(["a"])'),
                             "expects List<T>, found List<String>")

    def test_a_generic_call_feeds_another_generic_call(self):
        decls = ("sfn ident<T>(x: T) -> T {\n    ret x\n}\n\n"
                 "sfn first<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n\n")
        self.assertRuns(decls + program("sprint(ident(first([7])))"), "7\n")

    def test_a_method_result_feeds_a_generic_call(self):
        decls = ("class B<T> {\n    items: List<T>\n    sfn all() -> List<T> {\n"
                 "        ret self.items\n    }\n}\n\n"
                 "sfn first<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n\n")
        check(decls + program("let b: B<Int> = B([1, 2])\nlet n: Int = first(b.all())"))
        self.assertTypeError(
            decls + program("let b: B<Int> = B([1, 2])\nlet s: String = first(b.all())"),
            "cannot initialise String")

    def test_a_generic_body_can_construct_its_own_type(self):
        decls = BOX + "sfn wrap<T>(x: T) -> Box<T> {\n    ret Box(x)\n}\n\n"
        self.assertRuns(decls + program("let b: Box<Int> = wrap(1)\nsprint(b.v)"),
                        "1\n")

    def test_a_bare_container_argument_cannot_bind_a_parameter(self):
        decls = "sfn f<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n\n"
        self.assertTypeError(decls + program("let xs: List = [1]\nlet n: Int = f(xs)"),
                             "cannot infer")


class DispatchTests(AuditCase):
    """Silica has no inheritance, so dispatch is by declared type."""

    def test_there_is_no_inheritance(self):
        # documents the boundary: `class B : A` is not part of the language
        self.assertParseError("class A {\n    v: Int\n}\n"
                              "class B : A {\n    w: Int\n}\n", "expected")

    def test_same_method_name_on_two_classes_dispatches_by_type(self):
        decls = ("class A {\n    n: Int\n    sfn run() -> Int {\n"
                 "        ret 1\n    }\n}\n\n"
                 "class B {\n    n: Int\n    sfn run() -> Int {\n"
                 "        ret 2\n    }\n}\n\n")
        self.assertRuns(decls + program("let a: A = A(0)\nlet b: B = B(0)\n"
                                        "sprint(a.run())\nsprint(b.run())"), "1\n2\n")

    def test_same_method_name_on_generic_and_non_generic_classes(self):
        decls = ("class A {\n    n: Int\n    sfn get() -> Int {\n"
                 "        ret 9\n    }\n}\n\n"
                 "class G<T> {\n    v: T\n    sfn get() -> T {\n"
                 "        ret self.v\n    }\n}\n\n")
        self.assertRuns(decls + program('let a: A = A(0)\nlet g: G<String> = G("x")\n'
                                        "sprint(a.get())\nsprint(g.get())"), "9\nx\n")

    def test_a_method_of_another_class_is_rejected(self):
        decls = "class A {\n    n: Int\n}\n\nclass B {\n    m: Int\n}\n\n"
        self.assertTypeError(decls + program("let a: A = A(0)\nsprint(a.missing())"),
                             "has no member")


class DiagnosticCoverageTests(AuditCase):
    """Diagnostics the core tests do not reach."""

    def test_an_unknown_type_argument_is_named(self):
        # type names resolve at parse time in 0.9.3, including inside arguments
        self.assertParseError(program("let xs: List<Nope> = [1]"), "unknown type")

    def test_a_type_parameter_takes_no_type_arguments(self):
        self.assertTypeError("sfn g<U>(y: U<Int>) -> U {\n    ret y\n}\n" + program(""),
                             "cannot take type arguments")


class FormatterCoverageTests(AuditCase):
    """Round-trips the core formatter test does not build."""

    def round_trip(self, source):
        once = format_program(parse(tokenize(source)[0]))
        self.assertEqual(once, format_program(parse(tokenize(once)[0])),
                         "the formatter is not idempotent")
        parse(tokenize(once)[0])          # and the output must re-parse
        return once

    def test_multi_parameter_and_nested_annotations(self):
        once = self.round_trip(
            "struct Pair<K, V> {\n    k: K\n    v: V\n}\n\n"
            "sfn main() {\n    let m: Map<String, List<Int>> = {}\n"
            "    let p: Pair<String, List<Int>> = Pair(\"a\", [])\n}\n")
        self.assertIn("struct Pair<K, V>", once)
        self.assertIn("Map<String, List<Int>>", once)

    def test_private_and_static_members_on_a_generic_class(self):
        once = self.round_trip(
            "class C<T> {\n    v: T\n    private label: String\n\n"
            "    sfn get() -> T {\n        ret self.v\n    }\n\n"
            "    static sfn of<U>(x: U) -> List<U> {\n        ret [x]\n    }\n}\n")
        self.assertIn("class C<T>", once)
        self.assertIn("private label: String", once)
        self.assertIn("static sfn of<U>", once)


class InteractionTests(AuditCase):
    """Generics meeting the rest of the language."""

    def test_a_generic_class_holding_generic_structs(self):
        decls = BOX + ("class Shelf<T> {\n    items: List<T>\n\n"
                       "    sfn add(x: T) {\n        push(self.items, x)\n    }\n\n"
                       "    sfn first() -> T {\n        ret self.items[0]\n    }\n}\n\n")
        self.assertRuns(decls + program("let s: Shelf<Box<Int>> = Shelf([])\n"
                                        "s.add(Box(1))\nsprint(s.first().v)"), "1\n")

    def test_a_generic_function_over_a_list_of_classes(self):
        decls = ("class C {\n    v: Int\n}\n\n"
                 "sfn first<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n\n")
        self.assertRuns(decls + program("let cs: List<C> = [C(4)]\n"
                                        "let c: C = first(cs)\nsprint(c.v)"), "4\n")

    def test_a_method_returning_a_parameterised_container(self):
        decls = ("class B<T> {\n    items: List<T>\n    sfn all() -> List<T> {\n"
                 "        ret self.items\n    }\n}\n\n")
        self.assertRuns(decls + program('let b: B<String> = B(["a"])\n'
                                        "let xs: List<String> = b.all()\n"
                                        "sprint(xs[0])"), "a\n")

    def test_natives_work_on_parameterised_containers(self):
        self.assertRuns(program('let xs: List<Int> = [3, 1]\npush(xs, 2)\n'
                                'sprint(len(xs))\nsprint(xs)\n'
                                'let m: Map<String, Int> = {"a": 1}\n'
                                "sprint(keys(m))"), '3\n[3, 1, 2]\n["a"]\n')

    def test_a_generic_class_inside_a_bare_list(self):
        decls = "class C<T> {\n    v: T\n}\n\n"
        self.assertRuns(decls + program('let xs: List = [C(1), C("a")]\n'
                                        "sprint(len(xs))"), "2\n")


if __name__ == "__main__":
    unittest.main()
