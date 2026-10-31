"""Structs: declaration, construction, field access, mutability, equality.

Structs touch every stage — lexer, parser, checker, compiler, bytecode and VM —
so these tests are grouped by the stage whose contract is being pinned down.
A parser test that only checks "it did not crash" is worthless, so the runtime
tests run real programs and assert on real output.
"""

import io
import os
import tempfile
import unittest

from silica import ast
from silica.bytecode import OPS, OPERANDS, STACK_EFFECT
from silica.capabilities import CapabilitySet
from silica.checker import check
from silica.compiler import compile_program
from silica.engine import compile_source, run_chunk
from silica.errors import SilicaError
from silica.lexer import tokenize
from silica.parser import parse_source
from silica.vm import VM


def run(source):
    """Run a program and return its stdout, or the exception it raised."""
    out = io.StringIO()
    try:
        chunk = compile_source(source, "<test>").chunk
        run_chunk(chunk, "<test>", stdin=io.StringIO(), stdout=out,
                  stderr=io.StringIO(), capabilities=CapabilitySet.empty())
    except Exception as exc:  # noqa: BLE001
        return exc
    return out.getvalue()


POINT = """struct Point {
    x: Int
    y: Int
}

"""


class DeclarationTests(unittest.TestCase):
    def test_a_struct_declaration_parses(self):
        program, _diagnostics = parse_source(POINT + "sfn main() { }\n")
        decls = [s for s in program.stmts if isinstance(s, ast.StructDecl)]
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0].name, "Point")
        self.assertEqual([f[0] for f in decls[0].fields], ["x", "y"])
        self.assertEqual([f[1] for f in decls[0].fields], ["Int", "Int"])

    def test_struct_is_a_keyword(self):
        tokens, _diagnostics = tokenize("struct Point { x: Int }\n")
        kinds = [(t.kind, t.value) for t in tokens]
        self.assertIn(("kw", "struct"), kinds)

    def test_an_empty_struct_is_refused(self):
        error = run("struct Empty { }\n\nsfn main() { }\n")
        self.assertIn("no fields", str(error))

    def test_a_duplicate_field_is_refused(self):
        error = run("struct Bad {\n    x: Int\n    x: Int\n}\n\nsfn main() { }\n")
        self.assertIn("duplicate field", str(error))

    def test_a_duplicate_struct_name_is_refused(self):
        error = run(POINT + POINT + "sfn main() { }\n")
        self.assertIn("already declared", str(error))

    def test_an_unknown_field_type_is_refused(self):
        error = run("struct Bad {\n    x: Nope\n}\n\nsfn main() { }\n")
        self.assertIn("unknown type", str(error))

    def test_a_struct_cannot_contain_itself(self):
        error = run("struct Loop {\n    self: Loop\n}\n\nsfn main() { }\n")
        self.assertIn("cannot contain itself", str(error))

    def test_a_struct_may_contain_another_struct(self):
        source = POINT + """struct Line {
    start: Point
    end: Point
}

sfn main() {
    let l = Line(start: Point(x: 0, y: 0), end: Point(x: 1, y: 1))
    sprint(l.end.x)
}
"""
        self.assertEqual(run(source).strip(), "1")


class ConstructionTests(unittest.TestCase):
    def test_named_construction(self):
        output = run(POINT + "sfn main() {\n    let p = Point(x: 1, y: 2)\n    sprint(p.x)\n}\n")
        self.assertEqual(output.strip(), "1")

    def test_positional_construction(self):
        output = run(POINT + "sfn main() {\n    let p = Point(7, 8)\n    sprint(p.y)\n}\n")
        self.assertEqual(output.strip(), "8")

    def test_named_fields_may_be_given_in_any_order(self):
        output = run(POINT + "sfn main() {\n    let p = Point(y: 2, x: 1)\n    sprint(p.x)\n    sprint(p.y)\n}\n")
        self.assertEqual(output.split(), ["1", "2"])

    def test_a_missing_field_is_refused(self):
        error = run(POINT + "sfn main() {\n    let p = Point(x: 1)\n}\n")
        self.assertIn("missing", str(error))
        self.assertIn("'y'", str(error))

    def test_an_unknown_field_is_refused(self):
        error = run(POINT + "sfn main() {\n    let p = Point(x: 1, z: 2, y: 3)\n}\n")
        self.assertIn("no field 'z'", str(error))

    def test_a_duplicate_field_is_refused(self):
        error = run(POINT + "sfn main() {\n    let p = Point(x: 1, x: 2, y: 3)\n}\n")
        self.assertIn("twice", str(error))

    def test_a_wrong_field_type_is_refused(self):
        error = run(POINT + 'sfn main() {\n    let p = Point(x: "no", y: 2)\n}\n')
        self.assertIn("expects Int", str(error))

    def test_too_many_positional_values_are_refused(self):
        error = run(POINT + "sfn main() {\n    let p = Point(1, 2, 3)\n}\n")
        self.assertIn("takes 2 fields", str(error))

    def test_an_unknown_struct_is_refused(self):
        error = run("sfn main() {\n    let p = Missing(x: 1)\n}\n")
        self.assertIn("unknown struct", str(error))

    def test_a_struct_and_a_function_cannot_share_a_name(self):
        error = run(POINT + "sfn Point(a: Int) -> Int {\n    ret a\n}\n\nsfn main() { }\n")
        self.assertIn("already a struct", str(error))
        self.assertIn("cannot share a name", str(getattr(error, "hint", "") or ""))


class FieldAccessTests(unittest.TestCase):
    def test_reading_a_field(self):
        output = run(POINT + "sfn main() {\n    let p = Point(3, 4)\n    sprint(p.y)\n}\n")
        self.assertEqual(output.strip(), "4")

    def test_an_unknown_field_read_is_refused(self):
        error = run(POINT + "sfn main() {\n    let p = Point(1, 2)\n    sprint(p.z)\n}\n")
        self.assertIn("no field 'z'", str(error))

    def test_a_field_of_a_non_struct_is_refused(self):
        error = run("sfn main() {\n    let n = 5\n    sprint(n.x)\n}\n")
        self.assertIn("not a struct", str(error))

    def test_structs_can_be_passed_and_returned(self):
        source = POINT + """sfn move(p: Point, dx: Int) -> Point {
    ret Point(x: p.x + dx, y: p.y)
}

sfn main() {
    let a = Point(1, 2)
    let b = move(a, 10)
    sprint(b.x)
    sprint(a.x)
}
"""
        self.assertEqual(run(source).split(), ["11", "1"])


class MutabilityTests(unittest.TestCase):
    def test_a_let_struct_can_be_modified(self):
        output = run(POINT + "sfn main() {\n    let p = Point(1, 2)\n    p.x = 99\n    sprint(p.x)\n}\n")
        self.assertEqual(output.strip(), "99")

    def test_a_const_struct_cannot_be_modified(self):
        error = run(POINT + "sfn main() {\n    const p = Point(1, 2)\n    p.x = 99\n}\n")
        self.assertIn("constant", str(error))

    def test_a_const_struct_is_frozen_against_aliases_too(self):
        """The checker sees the direct case; only the VM can catch an alias."""
        source = POINT + """sfn main() {
    const origin = Point(0, 0)
    let alias = origin
    alias.x = 42
    sprint(origin.x)
}
"""
        error = run(source)
        self.assertIn("constant struct", str(error))

    def test_assigning_the_wrong_type_is_refused(self):
        error = run(POINT + 'sfn main() {\n    let p = Point(1, 2)\n    p.x = "no"\n}\n')
        self.assertIn("expects Int", str(error))

    def test_assigning_an_unknown_field_is_refused(self):
        error = run(POINT + "sfn main() {\n    let p = Point(1, 2)\n    p.z = 1\n}\n")
        self.assertIn("no field 'z'", str(error))

    def test_a_map_field_assignment_points_at_maps(self):
        error = run('sfn main() {\n    let m = {"a": 1}\n    m.a = 2\n}\n')
        self.assertIn("not a struct", str(error))


class EqualityAndDisplayTests(unittest.TestCase):
    def test_equal_structs_compare_equal(self):
        output = run(POINT + "sfn main() {\n    sprint(Point(1, 2) == Point(1, 2))\n}\n")
        self.assertEqual(output.strip(), "oui")

    def test_different_structs_compare_unequal(self):
        output = run(POINT + "sfn main() {\n    sprint(Point(1, 2) == Point(1, 3))\n}\n")
        self.assertEqual(output.strip(), "nein")

    def test_a_struct_does_not_equal_a_map_with_the_same_contents(self):
        # Silica refuses == between different types rather than returning nein,
        # which is consistent with `1 == "a"` and catches real mistakes
        error = run(POINT + 'sfn main() {\n    sprint(Point(1, 2) == {"x": 1, "y": 2})\n}\n')
        self.assertIn("Map", str(error))

    def test_two_different_struct_types_are_not_equal(self):
        source = POINT + """struct Pair {
    x: Int
    y: Int
}

sfn main() {
    sprint(Point(1, 2) == Pair(x: 1, y: 2))
}
"""
        error = run(source)
        self.assertIn("Pair", str(error))

    def test_sprint_shows_the_type_and_fields(self):
        output = run(POINT + "sfn main() {\n    sprint(Point(1, 2))\n}\n")
        self.assertEqual(output.strip(), "Point(x: 1, y: 2)")

    def test_a_struct_inside_a_list_renders(self):
        output = run(POINT + "sfn main() {\n    let ps = [Point(1, 2)]\n    sprint(ps)\n}\n")
        self.assertIn("Point(x: 1, y: 2)", output)


class BytecodeTests(unittest.TestCase):
    def test_the_new_opcodes_are_declared_consistently(self):
        for name in ("MAKE_STRUCT", "GET_FIELD", "SET_FIELD", "FREEZE"):
            with self.subTest(opcode=name):
                self.assertIn(name, OPS)
                self.assertIn(name, OPERANDS)
                self.assertIn(name, STACK_EFFECT)

    def test_opcode_codes_are_unique(self):
        codes = list(OPS.values())
        self.assertEqual(len(codes), len(set(codes)))

    def test_structs_survive_a_compile_and_reload(self):
        from silica.bytecode import deserialize, serialize
        source = POINT + "sfn main() {\n    let p = Point(5, 6)\n    sprint(p.x + p.y)\n}\n"
        chunk = compile_source(source, "<test>").chunk
        data = serialize(chunk)
        restored = deserialize(data, "<test>")
        # VM.run() writes to real stdout, so capture it rather than guessing
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            VM(restored).run()
        self.assertEqual(out.getvalue().strip(), "11")


class ErrorMessageTests(unittest.TestCase):
    """A diagnostic that does not help is a bug of its own."""

    def test_unknown_field_lists_the_real_fields(self):
        error = run(POINT + "sfn main() {\n    let p = Point(1, 2)\n    sprint(p.nope)\n}\n")
        self.assertIn("no field 'nope'", str(error))
        self.assertIn("x, y", str(getattr(error, "hint", "") or ""))

    def test_missing_field_shows_the_full_signature(self):
        error = run(POINT + "sfn main() {\n    let p = Point(x: 1)\n}\n")
        self.assertIn("missing", str(error))
        self.assertIn("x: Int", str(getattr(error, "hint", "") or ""))

    def test_the_error_is_located(self):
        error = run(POINT + "sfn main() {\n    let p = Point(x: 1)\n}\n")
        self.assertEqual(error.line, 7)
        self.assertEqual(error.filename, "<test>")


if __name__ == "__main__":
    unittest.main()
