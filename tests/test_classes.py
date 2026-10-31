"""Structs and classes: syntax, semantics, bytecode and runtime.

The tests are grouped the way the phase was implemented — parser, checker,
bytecode, VM, then end-to-end programs — so a failure points at one stage.
"""

import struct
import unittest
import zlib

from silica import ast
from silica.bytecode import (FORMAT_MAJOR, FORMAT_MINOR, MAGIC, Chunk, Function,
                             deserialize, encode, serialize, verify_chunk,
                             write_varint)
from silica.natives import StructValue, format_value, type_name
from silica.checker import Checker
from silica.errors import (CompileError, ParseError, SilicaRuntimeError,
                           SilicaTypeError, VerifyError)
from silica.fmt import format_program
from silica.lexer import tokenize
from silica.parser import parse

from .helpers import run


def program(body, decls=""):
    return decls + "sfn main() {\n" + body + "\n}\n"


def check(source):
    prog = parse(tokenize(source)[0])
    Checker(prog).check()
    return prog


STRUCT_SOURCE = "struct Point {\n    x: Int\n    y: Int\n}\n"
CLASS_SOURCE = ("class Counter {\n    v: Int\n    private label: String\n\n"
                "    sfn add(n: Int) -> Int {\n        self.v = self.v + n\n"
                "        ret self.v\n    }\n\n"
                "    sfn describe() -> String {\n"
                "        ret self.label + \"=\" + str(self.v)\n    }\n\n"
                "    static sfn zero(label: String) -> Counter {\n"
                "        ret Counter(0, label)\n    }\n}\n")


class ParserTests(unittest.TestCase):
    def parse(self, source):
        return parse(tokenize(source)[0])

    def test_struct_shape(self):
        prog = self.parse("struct Point {\n x: Int\n y: Float\n}\n")
        decl = prog.stmts[0]
        self.assertIsInstance(decl, ast.StructDecl)
        self.assertEqual(decl.name, "Point")
        self.assertEqual([f[0] for f in decl.fields], ["x", "y"])
        self.assertEqual([f[1] for f in decl.fields], ["Int", "Float"])
        self.assertFalse(any(f[4] for f in decl.fields))

    def test_class_shape_with_modifiers(self):
        prog = self.parse(
            "class C {\n v: Int\n private s: String\n"
            " sfn m() -> Int {\n  ret self.v\n }\n"
            " private sfn secret() {\n }\n"
            " static sfn make() -> C {\n  ret C(0, \"\")\n }\n}\n")
        decl = prog.stmts[0]
        self.assertIsInstance(decl, ast.ClassDecl)
        self.assertEqual([f[0] for f in decl.fields], ["v", "s"])
        self.assertTrue(decl.fields[1][4])
        self.assertEqual([m.name for m in decl.methods], ["m", "secret", "make"])
        self.assertTrue(decl.methods[1].is_private)
        self.assertTrue(decl.methods[2].is_static)
        self.assertFalse(decl.methods[0].is_static)

    def test_method_in_a_struct_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            self.parse("struct P {\n x: Int\n sfn m() {\n }\n}\n")
        self.assertIn("cannot declare methods", ctx.exception.message)

    def test_private_struct_field_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            self.parse("struct P {\n private x: Int\n}\n")
        self.assertIn("cannot be private", ctx.exception.message)

    def test_field_needs_a_type(self):
        with self.assertRaises(ParseError) as ctx:
            self.parse("struct P {\n x = 1\n}\n")
        self.assertIn("expected ':'", ctx.exception.message)

    def test_missing_brace(self):
        with self.assertRaises(ParseError) as ctx:
            self.parse("struct P {\n x: Int\n")
        self.assertIn("end of file", ctx.exception.message)

    def test_field_assignment_parses(self):
        prog = self.parse("struct P {\n x: Int\n}\n"
                          "sfn main() {\n let p: P = P(1)\n p.x = 5\n}\n")
        stmt = prog.stmts[1].body.stmts[1]
        # 0.9.3 represents `obj.field = value` as a path assignment
        self.assertIsInstance(stmt, ast.MemberAssignStmt)
        self.assertEqual(stmt.target, "p")
        self.assertEqual(stmt.path, ["x"])

    def test_formatter_round_trips_declarations(self):
        source = ("struct Point {\n    x: Int\n    y: Int\n}\n\n"
                  "class C {\n    v: Int\n    private s: String\n\n"
                  "    sfn m() -> Int {\n        ret self.v\n    }\n\n"
                  "    static sfn make() -> C {\n        ret C(0, \"x\")\n    }\n}\n")
        prog = self.parse(source)
        once = format_program(prog)
        twice = format_program(self.parse(once))
        self.assertEqual(once, twice)
        self.assertIn("private s: String", once)
        self.assertIn("static sfn make() -> C", once)


class CheckerTests(unittest.TestCase):
    DECLS = ("struct Point {\n x: Int\n y: Int\n}\n\n"
             "class Counter {\n v: Int\n private label: String\n"
             " sfn add(n: Int) -> Int {\n  self.v = self.v + n\n  ret self.v\n }\n"
             " static sfn zero() -> Counter {\n  ret Counter(0, \"z\")\n }\n}\n")

    def assertTypeError(self, body, fragment, decls=DECLS):
        with self.assertRaises(SilicaTypeError) as ctx:
            check(program(body, decls))
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    def test_valid_program(self):
        check(program('let p: Point = Point(1, 2)\n'
                      'let c: Counter = Counter.zero()\n'
                      'sprint(c.add(1))\n'
                      'sprint(p.x + p.y)', self.DECLS))

    def test_unknown_type_is_named(self):
        # the parser resolves type names (it pre-scans declarations), so an
        # unknown one is a parse error with the same message
        with self.assertRaises((SilicaTypeError, ParseError)) as ctx:
            check(program("let p: Piont = Point(1, 2)", self.DECLS))
        self.assertIn("unknown type", str(ctx.exception))

    def test_construction_arity(self):
        self.assertTypeError("let p: Point = Point(1)", "is missing 'y'")

    def test_construction_argument_type(self):
        self.assertTypeError('let p: Point = Point(1, "two")', "expects Int")

    def test_unknown_field_is_named(self):
        self.assertTypeError("let p: Point = Point(1, 2)\nsprint(p.z)",
                             "has no field 'z'")

    def test_the_error_lists_the_real_fields(self):
        error = self.assertTypeError("let p: Point = Point(1, 2)\nsprint(p.xx)",
                                     "has no field 'xx'")
        self.assertIn("x", error.hint or "")

    def test_private_field_outside_the_class(self):
        self.assertTypeError('let c: Counter = Counter(0, "a")\nsprint(c.label)',
                             "is private to Counter")

    def test_private_field_inside_the_class_is_fine(self):
        check("class C {\n private s: String\n"
              " sfn reveal() -> String {\n  ret self.s\n }\n}\n"
              "sfn main() {\n let c: C = C(\"x\")\n sprint(c.reveal())\n}\n")

    def test_static_method_called_on_an_instance(self):
        self.assertTypeError("let c: Counter = Counter(0, \"a\")\nc.zero()",
                             "is a static method")

    def test_instance_method_called_on_the_type(self):
        self.assertTypeError("sprint(Counter.add(1))", "is an instance method")

    def test_method_arity(self):
        self.assertTypeError('let c: Counter = Counter(0, "a")\nsprint(c.add())',
                             "expects 1 argument(s)")

    def test_self_outside_a_method(self):
        self.assertTypeError("sprint(self)", "only available inside a method")

    def test_self_in_a_static_method(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            check("class C {\n v: Int\n static sfn make() -> C {\n  ret self.v\n }\n}\n"
                  "sfn main() {\n}\n")
        self.assertIn("static method cannot use 'self'", ctx.exception.message)

    def test_type_name_is_not_a_value(self):
        self.assertTypeError("sprint(Point)", "is a type, not a value")

    def test_assigning_the_wrong_type_to_a_field(self):
        self.assertTypeError('let p: Point = Point(1, 2)\np.x = "ten"',
                             "expects Int")

    def test_assigning_to_an_unknown_field(self):
        self.assertTypeError("let p: Point = Point(1, 2)\np.z = 1",
                             "has no field 'z'")

    def test_duplicate_field(self):
        # 0.9.3 rejects a duplicate field at parse time, before checking
        with self.assertRaises((SilicaTypeError, ParseError)) as ctx:
            check("struct P {\n x: Int\n x: Int\n}\nsfn main() {\n}\n")
        self.assertIn("duplicate field", str(ctx.exception))

    def test_field_and_method_with_the_same_name(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            check("class C {\n v: Int\n sfn v() -> Int {\n  ret 1\n }\n}\n"
                  "sfn main() {\n}\n")
        self.assertIn("both a field and a method", ctx.exception.message)

    def test_type_cannot_shadow_a_builtin(self):
        with self.assertRaises((SilicaTypeError, ParseError)) as ctx:
            check("struct Int {\n x: Int\n}\nsfn main() {\n}\n")
        self.assertIn("built-in", str(ctx.exception))

    def test_type_and_function_cannot_share_a_name(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            check("struct P {\n x: Int\n}\nsfn P() {\n}\nsfn main() {\n}\n")
        self.assertIn("already", str(ctx.exception))

    def test_a_method_may_return_its_own_type(self):
        check("class C {\n v: Int\n sfn me() -> C {\n  ret self\n }\n}\n"
              "sfn main() {\n let c: C = C(1)\n sprint(c.me().v)\n}\n")


class BytecodeTests(unittest.TestCase):
    """The merged design uses 0.9.3's opcodes plus CALL_METHOD."""

    STRUCT = STRUCT_SOURCE
    CLASS = CLASS_SOURCE

    def compiled(self, source):
        from silica.engine import compile_source
        return compile_source(source).chunk

    def test_class_construction_marks_the_descriptor(self):
        chunk = self.compiled(program("let c: C = C(1)", "class C {\n    v: Int\n}\n"))
        descriptors = [c for c in chunk.constants
                       if isinstance(c, str) and c.startswith("C:")]
        self.assertTrue(descriptors)
        self.assertTrue(descriptors[0].endswith("#class"), descriptors[0])

    def test_struct_construction_has_no_marker(self):
        chunk = self.compiled(program("let p: Point = Point(1, 2)", self.STRUCT))
        descriptors = [c for c in chunk.constants
                       if isinstance(c, str) and c.startswith("Point:")]
        self.assertTrue(descriptors)
        self.assertFalse(descriptors[0].endswith("#class"))

    def test_methods_are_functions_named_type_method(self):
        chunk = self.compiled(program("let c: Counter = Counter(0, \"a\")\n"
                                      "sprint(c.add(1))", self.CLASS))
        names = [fn.name for fn in chunk.functions]
        self.assertIn("Counter.add", names)
        self.assertIn("Counter.describe", names)

    def test_a_method_call_emits_call_method(self):
        from silica.bytecode import decode
        chunk = self.compiled(program("let c: Counter = Counter(0, \"a\")\n"
                                      "sprint(c.add(1))", self.CLASS))
        main = next(fn for fn in chunk.functions if fn.name == "main")
        opcodes = [ins.name for ins in decode(main.code)]
        self.assertIn("CALL_METHOD", opcodes)

    def test_verifier_rejects_an_unknown_method(self):
        code = encode("UNIT") + encode("CALL_METHOD", 0, 0) + encode("RET")
        fn = Function("main", 0, 1, 4, "Unit", code, [])
        chunk = Chunk(["nope"], [], [fn], entry=0)
        with self.assertRaises(VerifyError) as ctx:
            verify_chunk(chunk)
        self.assertIn("no declared method", ctx.exception.message)

    def test_verifier_rejects_a_wrong_arity(self):
        # a method that takes one argument (plus the receiver) called with none
        code = encode("UNIT") + encode("CALL_METHOD", 0, 0) + encode("RET")
        fn = Function("main", 0, 1, 4, "Unit", code, [])
        method = Function("C.add", 2, 2, 4, "Unit", encode("RET"), [])
        chunk = Chunk(["add"], [], [fn, method], entry=0)
        with self.assertRaises(VerifyError) as ctx:
            verify_chunk(chunk)
        self.assertIn("CALL_METHOD", ctx.exception.message)

    def test_verifier_rejects_a_non_string_method_name(self):
        code = encode("UNIT") + encode("CALL_METHOD", 0, 0) + encode("RET")
        fn = Function("main", 0, 1, 4, "Unit", code, [])
        chunk = Chunk([7], [], [fn], entry=0)
        with self.assertRaises(VerifyError) as ctx:
            verify_chunk(chunk)
        self.assertIn("String method-name", ctx.exception.message)

    def test_format_major_stays_1(self):
        # adding CALL_METHOD did not change the payload layout, so a 1.0 file
        # still loads; the major version is what a reader refuses
        self.assertEqual(FORMAT_MAJOR, 1)

    def test_a_format_1_0_payload_still_loads(self):
        """The compatibility promise: an old .sbc file keeps working."""
        payload = bytearray()
        write_varint(payload, 0)                    # constants
        write_varint(payload, 0)                    # globals
        write_varint(payload, 1)                    # functions
        name = b"main"
        write_varint(payload, len(name))
        payload.extend(name)
        write_varint(payload, 0)                    # arity
        write_varint(payload, 1)                    # locals
        write_varint(payload, 1)                    # max stack
        payload.append(0)                           # return type: Unit
        code = bytes([0x02, 0x1B])                  # UNIT, RET
        write_varint(payload, len(code))
        payload.extend(code)
        write_varint(payload, 0)                    # line table
        payload.append(0)                           # no init
        payload.append(1)                           # has entry
        write_varint(payload, 0)
        header = bytearray()
        header.extend(MAGIC)
        header.extend(struct.pack("<H", 1))
        header.extend(struct.pack("<H", 0))         # a 1.0 file
        header.append(0)
        header.extend(struct.pack("<I", zlib.crc32(bytes(payload)) & 0xFFFFFFFF))
        chunk = deserialize(bytes(header) + bytes(payload))
        verify_chunk(chunk)
        from silica.engine import run_chunk
        import io
        out = io.StringIO()
        self.assertEqual(run_chunk(chunk, "<1.0>", stdin=io.StringIO(""),
                                   stdout=out), 0)


class VmTests(unittest.TestCase):
    STRUCT = "struct Point {\n x: Int\n y: Int\n}\n"
    CLASS = ("class Counter {\n v: Int\n private label: String\n"
             " sfn add(n: Int) -> Int {\n  self.v = self.v + n\n  ret self.v\n }\n"
             " sfn describe() -> String {\n  ret self.label + \"=\" + str(self.v)\n }\n"
             " static sfn zero(label: String) -> Counter {\n  ret Counter(0, label)\n }\n}\n")

    def test_construction_and_fields(self):
        code, out = run(program("let p: Point = Point(3, 4)\n"
                                "sprint(p.x)\nsprint(p.y)", self.STRUCT))
        self.assertEqual((code, out), (0, "3\n4\n"))

    def test_field_write(self):
        code, out = run(program("let p: Point = Point(3, 4)\np.x = 10\nsprint(p)",
                                self.STRUCT))
        self.assertEqual(out, "Point(x: 10, y: 4)\n")

    def test_method_mutates_state(self):
        code, out = run(program('let c: Counter = Counter(0, "hits")\n'
                                'sprint(c.add(2))\nsprint(c.add(3))', self.CLASS))
        self.assertEqual(out, "2\n5\n")

    def test_private_field_read_inside_the_class(self):
        code, out = run(program('let c: Counter = Counter(0, "hits")\n'
                                'sprint(c.describe())', self.CLASS))
        self.assertEqual(out, "hits=0\n")

    def test_static_construction(self):
        code, out = run(program('let c: Counter = Counter.zero("z")\n'
                                'sprint(c.add(1))', self.CLASS))
        self.assertEqual(out, "1\n")

    def test_type_of_an_instance(self):
        code, out = run(program("let p: Point = Point(1, 2)\nsprint(type_of(p))",
                                self.STRUCT))
        self.assertEqual(out, "Point\n")

    def test_struct_equality_is_structural(self):
        code, out = run(program("sprint(Point(1, 2) == Point(1, 2))\n"
                                "sprint(Point(1, 2) == Point(1, 3))", self.STRUCT))
        self.assertEqual(out, "oui\nnein\n")

    def test_class_equality_is_identity(self):
        code, out = run(program('let a: Counter = Counter(0, "a")\n'
                                'let b: Counter = Counter(0, "a")\n'
                                'let c: Counter = a\n'
                                "sprint(a == b)\nsprint(a == c)", self.CLASS))
        self.assertEqual(out, "nein\noui\n")

    def test_instances_in_collections(self):
        code, out = run(program("let points: List = [Point(1, 2), Point(3, 4)]\n"
                                "sprint(len(points))\nsprint(points[1].y)\n"
                                "per p in points {\n dit(p.x)\n}\nsprint(\"\")",
                                self.STRUCT))
        self.assertEqual(out, "2\n4\n13\n")

    def test_nested_instances_print_recursively(self):
        decls = "struct Node {\n value: Int\n next: Point\n}\n" + self.STRUCT
        code, out = run(program("let n: Node = Node(1, Point(2, 3))\nsprint(n)", decls))
        self.assertEqual(out, "Node(value: 1, next: Point(x: 2, y: 3))\n")

    def test_method_calling_method(self):
        decls = ("class Calc {\n base: Int\n"
                 " sfn double() -> Int {\n  ret self.base * 2\n }\n"
                 " sfn quadruple() -> Int {\n  ret self.double() * 2\n }\n}\n")
        code, out = run(program("let c: Calc = Calc(3)\nsprint(c.quadruple())", decls))
        self.assertEqual(out, "12\n")

    def test_instance_as_a_function_argument(self):
        decls = self.STRUCT + "sfn area(p: Point) -> Int {\n ret p.x * p.y\n}\n"
        code, out = run(program("sprint(area(Point(3, 4)))", decls))
        self.assertEqual(out, "12\n")

    def test_instances_survive_bytecode_serialisation(self):
        from silica.bytecode import serialize, deserialize
        from silica.engine import compile_source, run_chunk
        import io
        source = program("let p: Point = Point(7, 8)\nsprint(p.x)", self.STRUCT)
        chunk = compile_source(source).chunk
        back = deserialize(serialize(chunk))
        verify_chunk(back)
        out = io.StringIO()
        run_chunk(back, "<sbc>", stdin=io.StringIO(""), stdout=out)
        self.assertEqual(out.getvalue(), "7\n")

    def test_arithmetic_on_an_instance_is_rejected_statically(self):
        # the checker knows `p` is a Point, so this never reaches the VM
        with self.assertRaises(SilicaTypeError) as ctx:
            run(program("let p: Point = Point(1, 2)\nsprint(p + 1)", self.STRUCT))
        self.assertIn("Point", str(ctx.exception))

    def test_indexing_an_instance_is_rejected_statically(self):
        with self.assertRaises(SilicaTypeError):
            run(program("let p: Point = Point(1, 2)\nsprint(p[0])", self.STRUCT))


class ObjectModelTests(unittest.TestCase):
    """The runtime value model: one StructValue, two equality rules."""

    def test_struct_equality_recurses(self):
        a = StructValue("Point", {"x": 1, "y": 2})
        b = StructValue("Point", {"x": 1, "y": 2})
        self.assertTrue(a == b)
        b.fields["y"] = 3
        self.assertFalse(a == b)

    def test_class_equality_is_identity(self):
        a = StructValue("C", {"v": 1}, is_struct=False)
        b = StructValue("C", {"v": 1}, is_struct=False)
        self.assertFalse(a == b)
        self.assertTrue(a == a)

    def test_different_types_are_never_equal(self):
        a = StructValue("A", {"v": 1})
        b = StructValue("B", {"v": 1})
        self.assertFalse(a == b)

    def test_a_struct_never_equals_a_class(self):
        plain = StructValue("A", {"v": 1})
        object_ = StructValue("A", {"v": 1}, is_struct=False)
        self.assertFalse(plain == object_)

    def test_render_uses_declaration_order(self):
        instance = StructValue("P", {"b": 2, "a": 1})
        self.assertEqual(format_value(instance), "P(b: 2, a: 1)")

    def test_type_name_reports_the_declared_type(self):
        self.assertEqual(type_name(StructValue("Point", {"x": 1})), "Point")
        self.assertEqual(type_name(StructValue("C", {}, is_struct=False)), "C")


class IntegrationTests(unittest.TestCase):
    """A small program that models something real, end to end."""

    SOURCE = '''struct Ticket {
    id: Int
    title: String
    open: Bool
}

class Queue {
    tickets: List
    private next_id: Int

    sfn push(title: String) -> Int {
        self.next_id = self.next_id + 1
        push(self.tickets, Ticket(self.next_id, title, oui))
        ret self.next_id
    }

    sfn close(id: Int) {
        # A loop variable is a constant binding, and a const struct is frozen;
        # binding the ticket with `let` gives a mutable alias of the same value.
        let i: Int = 0
        tant i < len(self.tickets) {
            let ticket: Ticket = self.tickets[i]
            si ticket.id == id {
                ticket.open = nein
            }
            i = i + 1
        }
    }

    sfn open_count() -> Int {
        let count: Int = 0
        per ticket in self.tickets {
            si ticket.open {
                count = count + 1
            }
        }
        ret count
    }
}

sfn main() {
    let queue: Queue = Queue([], 0)
    sprint(queue.push("write the docs"))
    sprint(queue.push("fix the bug"))
    sprint(queue.open_count())
    queue.close(1)
    sprint(queue.open_count())
    sprint(queue.tickets[0].title)
}
'''

    def test_the_queue_program(self):
        code, out = run(self.SOURCE)
        self.assertEqual(code, 0)
        self.assertEqual(out, "1\n2\n2\n1\nwrite the docs\n")

    def test_it_survives_compilation_to_bytecode(self):
        from silica.bytecode import deserialize, serialize, verify_chunk
        from silica.engine import compile_source
        chunk = compile_source(self.SOURCE).chunk
        back = deserialize(serialize(chunk))
        verify_chunk(back)
        names = [fn.name for fn in back.functions]
        for method in ("Queue.push", "Queue.close", "Queue.open_count"):
            self.assertIn(method, names)
        descriptors = [c for c in back.constants
                       if isinstance(c, str) and c.startswith("Queue:")]
        self.assertTrue(descriptors)
        self.assertTrue(descriptors[0].endswith("#class"))


if __name__ == "__main__":
    unittest.main()
