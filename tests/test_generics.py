"""Generics: declarations, inference, constraints, parameterised containers.

Type arguments are checked statically and erased at run time, so `type_of` on a
`Box(1)` is `"Box"`. That is asserted here rather than left implicit.

`RegressionTests` holds one test for every defect the port onto the 0.9.3 struct
model uncovered, so none of them can come back silently.
"""

import io
import unittest

from silica import ast, types
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


BOX = "struct Box<T> {\n    value: T\n}\n\n"
STACK = ("class Stack<T> {\n    items: List<T>\n\n"
         "    sfn add_item(item: T) {\n        push(self.items, item)\n    }\n\n"
         "    sfn size() -> Int {\n        ret len(self.items)\n    }\n\n"
         "    sfn peek() -> T {\n        ret self.items[len(self.items) - 1]\n    }\n}\n\n")
FIRST = "sfn first<T>(items: List<T>) -> T {\n    ret items[0]\n}\n\n"
TWICE = "sfn twice<T: Numeric>(x: T) -> T {\n    ret x + x\n}\n\n"


class TypeExpressionTests(unittest.TestCase):
    def test_parse_nested(self):
        self.assertEqual(types.parse("Map<String, List<Int>>"),
                         ("Map", (("String", ()), ("List", (("Int", ()),)))))

    def test_base_and_args(self):
        self.assertEqual(types.base("List<Int>"), "List")
        self.assertEqual(types.args("Map<String, Int>"), ("String", "Int"))
        self.assertEqual(types.args("Int"), ())

    def test_render_round_trip(self):
        for text in ("Int", "List<Int>", "Map<String, List<Box<T>>>"):
            self.assertEqual(types.render(types.parse(text)), text)

    def test_substitute(self):
        self.assertEqual(types.substitute("Map<String, T>", {"T": "Int"}),
                         "Map<String, Int>")
        self.assertEqual(types.substitute("List<T>", {}), "List<T>")

    def test_unify_binds(self):
        mapping = {}
        self.assertTrue(types.unify("List<T>", "List<Int>", mapping))
        self.assertEqual(mapping["T"], "Int")

    def test_unify_conflicts(self):
        mapping = {"T": "Int"}
        self.assertFalse(types.unify("T", "String", mapping))
        self.assertEqual(mapping["T"], "Int")

    def test_unify_accepts_a_bare_actual(self):
        mapping = {}
        self.assertTrue(types.unify("List<T>", "List", mapping))
        self.assertEqual(mapping, {})

    def test_constraint_kinds(self):
        self.assertTrue(types.satisfies("Int", "Numeric"))
        self.assertTrue(types.satisfies("String", "Orderable"))
        self.assertFalse(types.satisfies("Bool", "Numeric"))
        self.assertTrue(types.satisfies("Anything", None))

    def test_malformed_types_are_rejected(self):
        for text in ("", "List<", "Map<String", "List<>"):
            with self.assertRaises(types.TypeError_, msg=text):
                types.parse(text)


class ParserTests(unittest.TestCase):
    def parse(self, source):
        return parse(tokenize(source)[0])

    def test_type_parameters_on_all_three_declarations(self):
        prog = self.parse("struct Box<T> {\n    value: T\n}\n"
                          "class Stack<T> {\n    items: List<T>\n}\n"
                          "sfn first<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n")
        self.assertEqual([p[0] for p in prog.stmts[0].type_params], ["T"])
        self.assertEqual([p[0] for p in prog.stmts[1].type_params], ["T"])
        self.assertEqual([p[0] for p in prog.stmts[2].type_params], ["T"])

    def test_constraints_are_parsed(self):
        prog = self.parse("sfn biggest<T: Orderable>(a: T, b: T) -> T {\n"
                          "    ret a\n}\n")
        params = prog.stmts[0].type_params
        self.assertEqual(params[0][0], "T")
        self.assertEqual(params[0][1], "Orderable")

    def test_two_parameters(self):
        prog = self.parse("class Pair<K, V> {\n    key: K\n    value: V\n}\n")
        self.assertEqual([p[0] for p in prog.stmts[0].type_params], ["K", "V"])

    def test_nested_type_arguments(self):
        prog = self.parse('sfn main() {\n'
                          '    let m: Map<String, List<Int>> = {"a": [1]}\n}\n')
        self.assertEqual(prog.stmts[0].body.stmts[0].type_ann,
                         "Map<String, List<Int>>")

    def test_a_parameter_may_name_its_own_type(self):
        prog = self.parse("class C {\n    v: Int\n"
                          "    sfn me() -> C {\n        ret self\n    }\n}\n")
        self.assertEqual(prog.stmts[0].methods[0].ret_type, "C")

    def test_unknown_type_is_still_rejected_at_parse_time(self):
        with self.assertRaises(ParseError) as ctx:
            self.parse("sfn main() {\n    let x: Piont = 1\n}\n")
        self.assertIn("unknown type", ctx.exception.message)

    def test_duplicate_type_parameter(self):
        with self.assertRaises(ParseError) as ctx:
            self.parse("struct B<T, T> {\n    x: T\n}\n")
        self.assertIn("duplicate type parameter", ctx.exception.message)

    def test_unbalanced_type_parameter_list(self):
        with self.assertRaises(ParseError):
            self.parse("struct Box<T {\n    value: T\n}\n")

    def test_formatter_round_trips_generics(self):
        source = ("struct Box<T> {\n    value: T\n}\n\n"
                  "class Bag<T> {\n    items: List<T>\n\n"
                  "    sfn peek() -> T {\n        ret self.items[0]\n    }\n}\n\n"
                  "sfn biggest<T: Orderable>(a: T, b: T) -> T {\n    ret a\n}\n")
        once = format_program(self.parse(source))
        self.assertEqual(once, format_program(self.parse(once)))


class CheckerTests(unittest.TestCase):
    def assertTypeError(self, source, fragment):
        with self.assertRaises(SilicaTypeError) as ctx:
            check(source)
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    # -- arity and names ---------------------------------------------------
    def test_container_arity(self):
        self.assertTypeError("sfn main() {\n    let xs: List<Int, Int> = [1]\n}\n",
                             "List expects 0 or 1 type argument(s)")
        self.assertTypeError("sfn main() {\n    let m: Map<Int> = {}\n}\n",
                             "Map expects 0 or 2 type argument(s)")

    def test_user_type_arity(self):
        self.assertTypeError(BOX + program("let b: Box<Int, Int> = Box(1)"),
                             "Box expects 0 or 1 type argument(s)")

    def test_unknown_constraint(self):
        self.assertTypeError("sfn f<T: Fancy>(x: T) -> T {\n    ret x\n}\n" + program(""),
                             "unknown constraint 'Fancy'")

    # -- parameterised containers -----------------------------------------
    def test_element_type_flows_through_indexing(self):
        check(program('let xs: List<String> = ["a"]\nlet s: String = xs[0]'))
        self.assertTypeError(
            program('let xs: List<String> = ["a"]\nlet n: Int = xs[0]'),
            "cannot initialise Int with a value of type String")

    def test_element_type_flows_through_iteration(self):
        check(program("let xs: List<Int> = [1]\nper x in xs {\n let n: Int = x\n}"))
        self.assertTypeError(
            program("let xs: List<Int> = [1]\nper x in xs {\n let s: String = x\n}"),
            "cannot initialise String")

    def test_map_value_type_flows_through_indexing(self):
        check(program('let m: Map<String, Int> = {"a": 1}\nlet n: Int = m["a"]'))
        self.assertTypeError(
            program('let m: Map<String, Int> = {"a": 1}\nlet s: String = m["a"]'),
            "cannot initialise String")

    def test_nested_containers(self):
        check(program('let m: Map<String, List<Int>> = {"a": [1]}\n'
                      'sprint(m["a"][0])'))

    def test_type_arguments_are_invariant(self):
        self.assertTypeError(program("let xs: List<Int> = [1]\nlet ys: List<Float> = xs"),
                             "cannot initialise List<Float>")

    # -- inference ---------------------------------------------------------
    def test_inference_from_a_generic_function(self):
        check(FIRST + program("let xs: List<Int> = [1]\nlet n: Int = first(xs)"))

    def test_inference_from_a_literal(self):
        check(FIRST + program("sprint(first([1, 2]))"))

    def test_inference_from_the_binding_annotation(self):
        check(STACK + program('let s: Stack<String> = Stack([])\ns.add_item("a")'))

    def test_conflicting_inference(self):
        decls = "sfn same<T>(a: T, b: T) -> T {\n    ret a\n}\n\n"
        self.assertTypeError(decls + program('sprint(same(1, "x"))'),
                             "argument 2 of 'same' must be T, found String")

    def test_cannot_infer_without_help(self):
        decls = "sfn make<T>() -> List<T> {\n    ret []\n}\n\n"
        self.assertTypeError(decls + program("let xs: List = make()"),
                             "cannot infer type parameter")

    # -- constraints -------------------------------------------------------
    def test_constraint_satisfied_at_the_call_site(self):
        check(TWICE + program("sprint(twice(2))\nsprint(twice(1.5))"))
        self.assertTypeError(TWICE + program('sprint(twice("a"))'),
                             "does not satisfy Numeric")

    def test_unconstrained_parameter_cannot_be_operated_on(self):
        decls = "sfn twice<T>(x: T) -> T {\n    ret x + x\n}\n\n"
        self.assertTypeError(decls + program("sprint(twice(2))"),
                             "is unconstrained")

    def test_constraint_does_not_permit_another_kind(self):
        decls = ("sfn big<T: Numeric>(a: T, b: T) -> T {\n    si a > b {\n"
                 "        ret a\n    }\n    ret b\n}\n\n")
        self.assertTypeError(decls + program("sprint(big(1, 2))"),
                             "needs a Orderable value")

    # -- methods -----------------------------------------------------------
    def test_method_signature_follows_the_receiver(self):
        check(STACK + program('let s: Stack<String> = Stack([])\n'
                              'let v: String = s.peek()'))
        self.assertTypeError(
            STACK + program('let s: Stack<String> = Stack([])\nlet v: Int = s.peek()'),
            "cannot initialise Int with a value of type String")

    def test_method_argument_type_follows_the_receiver(self):
        self.assertTypeError(
            STACK + program('let s: Stack<Int> = Stack([])\ns.add_item("a")'),
            "must be Int, found String")


class RegressionTests(unittest.TestCase):
    """One test per defect found while porting generics onto 0.9.3."""

    def test_field_access_on_a_parameterised_receiver(self):
        # was: "'b' is Box<Int>, not a struct, so it has no fields"
        code, out = run(program("let b: Box<Int> = Box(7)\nsprint(b.value)", BOX))
        self.assertEqual((code, out), (0, "7\n"))

    def test_member_access_on_an_indexed_parameterised_element(self):
        # was: "cannot index a List<Box<Int>>, so it has no fields"
        source = BOX + program("let boxes: List<Box<Int>> = [Box(1), Box(2)]\n"
                               "sprint(boxes[1].value)")
        self.assertEqual(run(source)[1], "2\n")

    def test_method_call_on_a_generic_class_receiver(self):
        # was: "unknown module 'words'"
        source = STACK + program('let s: Stack<String> = Stack([])\n'
                                 's.add_item("a")\nsprint(s.peek())')
        self.assertEqual(run(source)[1], "a\n")

    def test_static_call_is_not_read_as_a_value(self):
        # was: "'Counter' is a type, not a value" (a diagnostic firing on the
        # static-call path, where the object is a type name)
        decls = ("class Counter {\n    v: Int\n\n"
                 "    static sfn make(n: Int) -> Counter {\n"
                 "        ret Counter(n)\n    }\n}\n\n")
        code, out = run(decls + program("let c: Counter = Counter.make(3)\nsprint(c.v)"))
        self.assertEqual((code, out), (0, "3\n"))

    def test_literal_argument_determines_a_type_parameter(self):
        # was: "cannot infer type parameter(s) T for 'first'"
        self.assertEqual(run(FIRST + program("sprint(first([1, 2]))"))[1], "1\n")

    def test_struct_self_containment_survives_type_parameters(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            check("struct P<T> {\n    p: P<T>\n}\n" + program(""))
        self.assertIn("cannot contain itself", ctx.exception.message)

    def test_a_const_binding_still_freezes_a_generic_struct(self):
        # 0.9.3 semantics: freezing is unchanged by generics
        source = BOX + program("const b: Box<Int> = Box(1)\nb.value = 2")
        with self.assertRaises(SilicaTypeError) as ctx:
            check(source)
        self.assertIn("constant", ctx.exception.message)


class PreservationTests(unittest.TestCase):
    """The generics work must not change how non-generic code behaves."""

    def test_a_bare_list_still_works_and_still_holds_anything(self):
        code, out = run(program('let xs: List = [1, "a", oui]\nsprint(len(xs))'))
        self.assertEqual((code, out), (0, "3\n"))

    def test_a_bare_container_accepts_a_parameterisation(self):
        check(program("let xs: List<Int> = [1]\nlet ys: List = xs\nlet zs: List = xs"))

    def test_heterogeneous_literals_stay_bare(self):
        code, out = run(program('let xs = [1, "a"]\nsprint(type_of(xs))'))
        self.assertEqual((code, out), (0, "List\n"))

    def test_list_concatenation_still_works(self):
        code, out = run(program("let a: List<Int> = [1]\n"
                                "let b: List<Int> = [2]\nsprint(a + b)"))
        self.assertEqual((code, out), (0, "[1, 2]\n"))

    def test_struct_equality_is_still_structural(self):
        decls = "struct P {\n    x: Int\n}\n\n"
        self.assertEqual(run(decls + program("sprint(P(1) == P(1))"))[1], "oui\n")

    def test_class_equality_is_still_identity(self):
        decls = "class C {\n    v: Int\n}\n\n"
        self.assertEqual(run(decls + program("sprint(C(1) == C(1))"))[1], "nein\n")


class RuntimeTests(unittest.TestCase):
    def test_generic_struct(self):
        self.assertEqual(run(program("let b: Box<Int> = Box(7)\nsprint(b.value)", BOX))[1],
                         "7\n")

    def test_generic_class(self):
        source = STACK + program('let s: Stack<String> = Stack([])\n'
                                 's.add_item("a")\ns.add_item("b")\n'
                                 'sprint(s.size())\nsprint(s.peek())')
        self.assertEqual(run(source)[1], "2\nb\n")

    def test_generic_function(self):
        self.assertEqual(run(FIRST + program("sprint(first([4, 5]))"))[1], "4\n")

    def test_constrained_generic_function(self):
        self.assertEqual(run(TWICE + program("sprint(twice(21))\nsprint(twice(1.5))"))[1],
                         "42\n3.0\n")

    def test_two_type_parameters(self):
        decls = "struct Pair<K, V> {\n    key: K\n    value: V\n}\n\n"
        source = decls + program('let p: Pair<String, Int> = Pair("age", 42)\n'
                                 "sprint(p.key)\nsprint(p.value)")
        self.assertEqual(run(source)[1], "age\n42\n")

    def test_type_arguments_are_erased(self):
        self.assertEqual(run(program("let b: Box<Int> = Box(1)\nsprint(type_of(b))",
                                     BOX))[1], "Box\n")

    def test_two_instantiations_share_one_runtime_type(self):
        source = BOX + program('let a: Box<Int> = Box(1)\nlet b: Box<String> = Box("x")\n'
                               "sprint(type_of(a) == type_of(b))")
        self.assertEqual(run(source)[1], "oui\n")

    def test_bytecode_round_trip_with_generics(self):
        from silica.bytecode import deserialize, serialize, verify_chunk
        from silica.engine import compile_source, run_chunk
        source = STACK + program('let s: Stack<String> = Stack([])\n'
                                 's.add_item("a")\nsprint(s.peek())')
        chunk = compile_source(source).chunk
        back = deserialize(serialize(chunk))
        verify_chunk(back)
        out = io.StringIO()
        run_chunk(back, "<sbc>", stdin=io.StringIO(""), stdout=out)
        self.assertEqual(out.getvalue(), "a\n")


if __name__ == "__main__":
    unittest.main()
