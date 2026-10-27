"""Parser tests: statement forms, precedence, literals, and error messages."""

import unittest

from silica import ast
from silica.errors import ParseError
from silica.lexer import tokenize
from silica.parser import parse


def parse_source(source):
    tokens, _ = tokenize(source)
    return parse(tokens)


class ParserTests(unittest.TestCase):
    def test_function_declaration_shape(self):
        program = parse_source("sfn square(n: Int) -> Int {\n ret n * n\n}\n")
        decl = program.stmts[0]
        self.assertIsInstance(decl, ast.FuncDecl)
        self.assertEqual(decl.name, "square")
        self.assertEqual(decl.params[0][0], "n")
        self.assertEqual(decl.params[0][1], "Int")
        self.assertEqual(decl.ret_type, "Int")
        self.assertIsInstance(decl.body.stmts[0], ast.ReturnStmt)

    def test_precedence_matches_specification(self):
        program = parse_source("sfn main() {\n let x: Int = 1 + 2 * 3\n}\n")
        init = program.stmts[0].body.stmts[0].init
        self.assertIsInstance(init, ast.Binary)
        self.assertEqual(init.op, "+")
        self.assertEqual(init.right.op, "*")

    def test_logical_precedence_is_lowest(self):
        program = parse_source("sfn main() {\n let b: Bool = oui und nein ou oui\n}\n")
        init = program.stmts[0].body.stmts[0].init
        self.assertEqual(init.op, "ou")
        self.assertEqual(init.left.op, "und")

    def test_unary_binds_tighter_than_binary(self):
        program = parse_source("sfn main() {\n let b: Bool = non oui und oui\n}\n")
        init = program.stmts[0].body.stmts[0].init
        self.assertEqual(init.op, "und")
        self.assertIsInstance(init.left, ast.Unary)

    def test_if_else_and_fin(self):
        program = parse_source(
            "sfn main() {\n si oui {\n  sprint(1)\n } sino {\n  sprint(2)\n }\n fin\n}\n")
        body = program.stmts[0].body
        self.assertIsInstance(body.stmts[0], ast.IfStmt)
        self.assertIsNotNone(body.stmts[0].else_block)
        self.assertIsInstance(body.stmts[-1], ast.FinStmt)

    def test_fin_must_be_the_last_element_of_a_block(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("sfn main() {\n sprint(1)\n fin\n sprint(2)\n}\n")
        self.assertIn("last element of a block", ctx.exception.message)

    def test_for_loop_requires_in(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("sfn main() {\n per x range(3) {\n }\n}\n")
        self.assertIn("expected 'in'", ctx.exception.message)

    def test_assignment_statement(self):
        program = parse_source("sfn main() {\n let x: Int = 1\n x = 2\n}\n")
        stmt = program.stmts[0].body.stmts[1]
        self.assertIsInstance(stmt, ast.AssignStmt)
        self.assertEqual(stmt.name, "x")

    def test_list_and_map_literals(self):
        program = parse_source(
            'sfn main() {\n let a: List = [1, 2]\n let m: Map = {"k": 1}\n}\n')
        body = program.stmts[0].body
        self.assertIsInstance(body.stmts[0].init, ast.ListLit)
        self.assertIsInstance(body.stmts[1].init, ast.MapLit)

    def test_index_and_member_expressions(self):
        program = parse_source("sfn main() {\n let x: Int = range(3)[0]\n}\n")
        init = program.stmts[0].body.stmts[0].init
        self.assertIsInstance(init, ast.Index)

    def test_sprint_is_a_call_expression(self):
        program = parse_source("sfn main() {\n sprint(1)\n}\n")
        stmt = program.stmts[0].body.stmts[0]
        self.assertIsInstance(stmt, ast.ExprStmt)
        self.assertIsInstance(stmt.expr, ast.Call)
        self.assertEqual(stmt.expr.callee.name, "sprint")

    def test_missing_brace_reports_opening_line(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("sfn main() {\n sprint(1)\n")
        self.assertIn("missing '}'", ctx.exception.message)

    def test_sino_without_si(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("sfn main() {\n sino {\n }\n}\n")
        self.assertIn("without a matching 'si'", ctx.exception.message)

    def test_two_statements_on_one_line_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_source("sfn main() {\n sprint(1) sprint(2)\n}\n")

    def test_unknown_type_name(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("sfn main() {\n let x: Integer = 1\n}\n")
        self.assertIn("unknown type", ctx.exception.message)

    def test_keyword_as_identifier_is_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("sfn main() {\n let si = 1\n}\n")
        self.assertIn("reserved", ctx.exception.hint or "")

    def test_multiline_argument_list(self):
        program = parse_source("sfn main() {\n sprint(\n  1\n )\n}\n")
        call = program.stmts[0].body.stmts[0].expr
        self.assertEqual(len(call.args), 1)

    def test_halt_with_and_without_code(self):
        program = parse_source("sfn main() {\n halt(2)\n}\n")
        self.assertIsNotNone(program.stmts[0].body.stmts[0].code)
        program = parse_source("sfn main() {\n halt\n}\n")
        self.assertIsNone(program.stmts[0].body.stmts[0].code)


if __name__ == "__main__":
    unittest.main()
