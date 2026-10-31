"""Generics: syntax, inference, constraints, erasure and runtime behaviour.

Phase 3 keeps Silica's type-as-a-string representation and adds a parameterised
form (`List<Int>`, `Box<T>`). Type arguments are checked statically and erased at
run time, so `type_of(Box(1))` is `"Box"` — that is asserted here rather than
left implicit.
"""

import io
import unittest

from silica import ast, types
from silica.checker import Checker
from silica.errors import SilicaTypeError, VerifyError
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

    def test_unify_binds_and_conflicts(self):
        mapping = {}
        self.assertTrue(types.unify("List<T>", "List<Int>", mapping))
        self.assertEqual(mapping["T"], "Int")
        self.assertFalse(types.unify("T", "String", mapping))
        self.assertEqual(mapping["T"], "Int")

    def test_unify_accepts_a_bare_actual(self):
        mapping = {}
        self.assertTrue(types.unify("List<T>", "List", mapping))
        self.assertEqual(mapping, {})

    def test_constraints(self):
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

    def test_type_parameters_on_declarations(self):
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
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0][0], "T")
        self.assertEqual(params[0][1], "Orderable")

    def test_multiple_parameters(self):
        prog = self.parse("class Pair<K, V> {\n    key: K\n    value: V\n}\n")
        self.assertEqual([p[0] for p in prog.stmts[0].type_params], ["K", "V"])

    def test_nested_type_arguments_in_annotations(self):
        prog = self.parse("sfn main() {\n"
                          '    let m: Map<String, List<Int>> = {"a": [1]}\n}\n')
        self.assertEqual(prog.stmts[0].body.stmts[0].type_ann,
                         "Map<String, List<Int>>")

    def test_unbalanced_type_parameters(self):
        from silica.errors import ParseError
        with self.assertRaises(ParseError):
            self.parse("struct Box<T {\n    value: T\n}\n")

    def test_formatter_round_trips_generics(self):
        source = ("struct Box<T> {\n    value: T\n}\n\n"
                  "class Stack<T> {\n    items: List<T>\n\n"
                  "    sfn peek() -> T {\n        ret self.items[0]\n    }\n}\n\n"
                  "sfn biggest<T: Orderable>(a: T, b: T) -> T {\n"
                  "    ret a\n}\n")
        once = format_program(self.parse(source))
        twice = format_program(self.parse(once))
        self.assertEqual(once, twice)
        self.assertIn("struct Box<T>", once)
        self.assertIn("sfn biggest<T: Orderable>(a: T, b: T) -> T", once)


class CheckerTests(unittest.TestCase):
    def assertTypeError(self, source, fragment):
        with self.assertRaises(SilicaTypeError) as ctx:
            check(source)
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    def test_container_arity(self):
        self.assertTypeError("sfn main() {\n    let xs: List<Int, Int> = [1]\n}\n",
                             "List expects 0 or 1 type argument(s)")
        self.assertTypeError("sfn main() {\n    let m: Map<Int> = {}\n}\n",
                             "Map expects 0 or 2 type argument(s)")

    def test_unknown_type_argument(self):
        self.assertTypeError("sfn main() {\n    let xs: List<Nope> = [1]\n}\n",
                             "unknown type 'Nope'")

    def test_user_type_arity(self):
        self.assertTypeError(BOX + "sfn main() {\n    let b: Box<Int, Int> = Box(1)\n}\n",
                             "Box expects 1 type argument(s)")

    def test_element_type_of_a_parameterised_list(self):
        check(program("let xs: List<String> = [\"a\"]\nlet s: String = xs[0]"))
        self.assertTypeError(
            program("let xs: List<String> = [\"a\"]\nlet n: Int = xs[0]"),
            "cannot initialise Int with a value of type String")

    def test_iteration_uses_the_element_type(self):
        check(program("let xs: List<Int> = [1]\nper x in xs {\n let n: Int = x\n}"))
        self.assertTypeError(
            program("let xs: List<Int> = [1]\nper x in xs {\n let s: String = x\n}"),
            "cannot initialise String")

    def test_type_arguments_are_invariant(self):
        self.assertTypeError(
            program("let xs: List<Int> = [1]\nlet ys: List<Float> = xs"),
            "cannot initialise List<Float>")

    def test_a_bare_container_accepts_any_parameterisation(self):
        check(program("let xs: List<Int> = [1]\nlet ys: List = xs\nlet zs: List = xs"))

    def test_inference_from_a_generic_function(self):
        check(FIRST + program("let xs: List<Int> = [1]\nlet n: Int = first(xs)"))

    def test_inference_from_a_literal(self):
        check(FIRST + program("sprint(first([1, 2]))"))

    def test_conflicting_inference(self):
        decls = "sfn same<T>(a: T, b: T) -> T {\n    ret a\n}\n\n"
        self.assertTypeError(decls + program('sprint(same(1, "x"))'),
                             "argument 2 of 'same' must be T, found String")

    def test_inference_from_the_annotation(self):
        # an empty list cannot bind T, so the binding's annotation supplies it
        check(STACK + program('let s: Stack<String> = Stack([])\ns.add_item("a")'))

    def test_cannot_infer_without_help(self):
        decls = "sfn make<T>() -> List<T> {\n    ret []\n}\n\n"
        self.assertTypeError(decls + program("let xs: List = make()"),
                             "cannot infer type parameter")

    def test_constraint_satisfied_at_the_call_site(self):
        decls = "sfn twice<T: Numeric>(x: T) -> T {\n    ret x + x\n}\n\n"
        check(decls + program("sprint(twice(2))\nsprint(twice(1.5))"))
        self.assertTypeError(decls + program('sprint(twice("a"))'),
                             "does not satisfy Numeric")

    def test_unconstrained_parameter_cannot_be_operated_on(self):
        decls = "sfn twice<T>(x: T) -> T {\n    ret x + x\n}\n\n"
        self.assertTypeError(decls + program("sprint(twice(2))"),
                             "is unconstrained")

    def test_constraint_does_not_permit_another_kind(self):
        decls = "sfn big<T: Numeric>(a: T, b: T) -> T {\n    si a > b {\n        ret a\n    }\n    ret b\n}\n\n"
        self.assertTypeError(decls + program("sprint(big(1, 2))"),
                             "needs a Orderable value")

    def test_unknown_constraint(self):
        self.assertTypeError("sfn f<T: Fancy>(x: T) -> T {\n    ret x\n}\n" + program(""),
                             "unknown constraint 'Fancy'")

    def test_duplicate_type_parameter(self):
        self.assertTypeError("struct B<T, T> {\n    x: T\n}\n" + program(""),
                             "duplicate type parameter")

    def test_method_signature_uses_the_receiver_argument(self):
        # peek() -> T becomes -> String for a Stack<String>
        check(STACK + program('let s: Stack<String> = Stack([])\n'
                              'let v: String = s.peek()'))
        self.assertTypeError(
            STACK + program('let s: Stack<String> = Stack([])\nlet v: Int = s.peek()'),
            "cannot initialise Int with a value of type String")

    def test_method_argument_type_follows_the_receiver(self):
        self.assertTypeError(
            STACK + program('let s: Stack<Int> = Stack([])\ns.add_item("a")'),
            "must be Int, found String")

    def test_static_method_cannot_use_a_class_type_parameter(self):
        decls = ("class Box<T> {\n    value: T\n\n"
                 "    static sfn empty() -> T {\n        ret self.value\n    }\n}\n\n")
        with self.assertRaises(SilicaTypeError) as ctx:
            check(decls + program(""))
        self.assertIn("static", ctx.exception.message)

    def test_generic_type_inside_a_generic_function(self):
        decls = (BOX + "sfn wrap<T>(x: T) -> Box<T> {\n    ret Box(x)\n}\n\n")
        check(decls + program("let b: Box<Int> = wrap(1)\nsprint(b.value)"))


class RuntimeTests(unittest.TestCase):
    def test_generic_struct(self):
        code, out = run(program("let b: Box<Int> = Box(7)\nsprint(b.value)", BOX))
        self.assertEqual((code, out), (0, "7\n"))

    def test_generic_class(self):
        source = STACK + program('let s: Stack<String> = Stack([])\n'
                                 's.add_item("a")\ns.add_item("b")\n'
                                 'sprint(s.size())\nsprint(s.peek())')
        code, out = run(source)
        self.assertEqual(out, "2\nb\n")

    def test_generic_function(self):
        source = FIRST + program("let xs: List<Int> = [4, 5]\nsprint(first(xs))")
        self.assertEqual(run(source)[1], "4\n")

    def test_generic_function_with_a_constraint(self):
        decls = "sfn twice<T: Numeric>(x: T) -> T {\n    ret x + x\n}\n\n"
        code, out = run(decls + program("sprint(twice(21))\nsprint(twice(1.5))"))
        self.assertEqual(out, "42\n3.0\n")

    def test_nested_generic_types(self):
        source = BOX + program("let boxes: List<Box<Int>> = [Box(1), Box(2)]\n"
                               "sprint(boxes[1].value)\n"
                               "per b in boxes {\n dit(b.value)\n}\nsprint(\"\")")
        self.assertEqual(run(source)[1], "2\n12\n")

    def test_type_arguments_are_erased_at_run_time(self):
        # documented behaviour: erasure means the base name is what exists
        source = BOX + program("let b: Box<Int> = Box(1)\nsprint(type_of(b))")
        self.assertEqual(run(source)[1], "Box\n")

    def test_two_instantiations_share_one_runtime_type(self):
        source = BOX + program('let a: Box<Int> = Box(1)\nlet b: Box<String> = Box("x")\n'
                               "sprint(type_of(a) == type_of(b))")
        self.assertEqual(run(source)[1], "oui\n")

    def test_map_with_typed_values(self):
        source = program('let m: Map<String, List<Int>> = {"a": [1, 2]}\n'
                         "sprint(m[\"a\"][1])")
        self.assertEqual(run(source)[1], "2\n")

    def test_generic_types_erase_in_the_bytecode_type_table(self):
        from silica.bytecode import deserialize, serialize, verify_chunk
        from silica.engine import compile_source
        chunk = compile_source(BOX + program("let b: Box<Int> = Box(1)")).chunk
        back = deserialize(serialize(chunk))
        verify_chunk(back)
        self.assertEqual([info.name for info in back.types], ["Box"])
        self.assertEqual(back.types[0].fields, ["value"])


class EndToEndTests(unittest.TestCase):
    SOURCE = '''struct Pair<K, V> {
    key: K
    value: V
}

class Bag<T> {
    items: List<T>

    sfn add(item: T) {
        push(self.items, item)
    }

    sfn count() -> Int {
        ret len(self.items)
    }

    sfn at(index: Int) -> T {
        ret self.items[index]
    }
}

sfn repeat<T>(value: T, times: Int) -> List<T> {
    let out: List<T> = []
    let i: Int = 0
    tant i < times {
        push(out, value)
        i = i + 1
    }
    ret out
}

sfn largest<T: Orderable>(items: List<T>) -> T {
    let best: T = items[0]
    per item in items {
        si item > best {
            best = item
        }
    }
    ret best
}

sfn main() {
    let words: Bag<String> = Bag([])
    words.add("alpha")
    words.add("beta")
    sprint(words.count())
    sprint(words.at(1))

    let numbers: List<Int> = repeat(7, 3)
    sprint(numbers)
    sprint(largest(numbers))
    sprint(largest(["pear", "apple"]))

    let pair: Pair<String, Int> = Pair("age", 42)
    sprint(pair.key)
    sprint(pair.value)
}
'''

    def test_the_program_runs(self):
        code, out = run(self.SOURCE)
        self.assertEqual(code, 0)
        self.assertEqual(out, "2\nbeta\n[7, 7, 7]\n7\npear\nage\n42\n")

    def test_it_compiles_to_bytecode_and_back(self):
        from silica.bytecode import deserialize, serialize, verify_chunk
        from silica.engine import compile_source, run_chunk
        chunk = compile_source(self.SOURCE).chunk
        back = deserialize(serialize(chunk))
        verify_chunk(back)
        out = io.StringIO()
        run_chunk(back, "<sbc>", stdin=io.StringIO(""), stdout=out)
        self.assertTrue(out.getvalue().startswith("2\nbeta\n"))


if __name__ == "__main__":
    unittest.main()
