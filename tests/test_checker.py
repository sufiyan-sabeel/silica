"""Semantic analysis and type-checker tests."""

import unittest

from silica.checker import Checker
from silica.errors import SilicaTypeError
from silica.lexer import tokenize
from silica.parser import parse


def check(source, require_main=True):
    tokens, _ = tokenize(source)
    program = parse(tokens)
    checker = Checker(program, "<test>", require_main=require_main)
    checker.check()
    return checker


class CheckerTests(unittest.TestCase):
    def assertTypeError(self, source, fragment, require_main=True):
        with self.assertRaises(SilicaTypeError) as ctx:
            check(source, require_main)
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    # -- declarations --------------------------------------------------------
    def test_records_function_signatures(self):
        checker = check("sfn add(a: Int, b: Int) -> Int {\n ret a + b\n}\n"
                        "sfn main() {\n sprint(add(1, 2))\n}\n")
        info = checker.functions["add"]
        self.assertEqual(info.params, [("a", "Int"), ("b", "Int")])
        self.assertEqual(info.ret, "Int")

    def test_duplicate_function(self):
        self.assertTypeError("sfn f() {\n}\nsfn f() {\n}\nsfn main() {\n}\n",
                             "already declared")

    def test_duplicate_parameter(self):
        self.assertTypeError("sfn f(a: Int, a: Int) {\n}\nsfn main() {\n}\n",
                             "duplicate parameter")

    def test_duplicate_local(self):
        self.assertTypeError("sfn main() {\n let x: Int = 1\n let x: Int = 2\n}\n",
                             "already declared")

    def test_reserved_builtin_name(self):
        # `sprint` is a keyword, so it cannot even be parsed as a function name
        from silica.errors import ParseError
        with self.assertRaises(ParseError):
            check("sfn sprint() {\n}\nsfn main() {\n}\n")

    def test_nested_function_rejected(self):
        self.assertTypeError("sfn main() {\n sfn inner() {\n }\n}\n",
                             "not allowed inside a block")

    def test_use_inside_block_rejected(self):
        self.assertTypeError("sfn main() {\n use math\n}\n", "not allowed inside a block")

    # -- entry point ---------------------------------------------------------
    def test_missing_main(self):
        self.assertTypeError("sfn other() {\n}\n", "no entry point")

    def test_main_with_parameters(self):
        self.assertTypeError("sfn main(a: Int) {\n}\n", "must not take parameters")

    def test_top_level_statement_rejected(self):
        self.assertTypeError("sprint(1)\n", "top level")

    # -- names ---------------------------------------------------------------
    def test_unknown_name(self):
        self.assertTypeError("sfn main() {\n sprint(nope)\n}\n", "unknown name")

    def test_unknown_function(self):
        self.assertTypeError("sfn main() {\n nope(1)\n}\n", "unknown function")

    def test_function_used_as_value(self):
        self.assertTypeError("sfn f() {\n}\nsfn main() {\n sprint(f)\n}\n",
                             "must be called")

    def test_assign_unknown(self):
        self.assertTypeError("sfn main() {\n y = 1\n}\n", "unknown name")

    # -- types ---------------------------------------------------------------
    def test_int_from_float_rejected(self):
        self.assertTypeError("sfn main() {\n let x: Int = 1.5\n}\n", "cannot initialise")

    def test_int_to_float_promotion_allowed(self):
        check("sfn main() {\n let x: Float = 1\n}\n")

    def test_assign_wrong_type(self):
        self.assertTypeError("sfn main() {\n let x: Int = 1\n x = \"s\"\n}\n",
                             "cannot assign")

    def test_assign_to_const(self):
        self.assertTypeError("sfn main() {\n const x: Int = 1\n x = 2\n}\n", "constant")

    def test_condition_must_be_bool(self):
        self.assertTypeError("sfn main() {\n let x: Int = 1\n si x {\n }\n}\n",
                             "must be Bool")

    def test_while_condition_must_be_bool(self):
        self.assertTypeError("sfn main() {\n tant 1 {\n }\n}\n", "must be Bool")

    def test_logical_operators_need_bools(self):
        self.assertTypeError("sfn main() {\n let b: Bool = 1 und oui\n}\n", "expects Bool")

    def test_ordering_mismatched_types(self):
        self.assertTypeError('sfn main() {\n let b: Bool = 1 < "a"\n}\n', "cannot order")

    def test_add_mismatched_types(self):
        self.assertTypeError('sfn main() {\n let s: String = "a" + 1\n}\n', "cannot add")

    def test_string_ordering_allowed(self):
        check('sfn main() {\n let b: Bool = "a" < "b"\n}\n')

    def test_index_requires_int(self):
        self.assertTypeError('sfn main() {\n let xs: List = [1]\n sprint(xs["a"])\n}\n',
                             "list index must be Int")

    def test_map_key_must_be_string(self):
        from silica.errors import ParseError
        with self.assertRaises(ParseError):
            check("sfn main() {\n let m: Map = {1: 2}\n}\n")

    def test_index_unknown_type(self):
        self.assertTypeError("sfn main() {\n let x: Int = 1\n sprint(x[0])\n}\n",
                             "cannot index")

    def test_integer_literal_must_fit_in_64_bits(self):
        err = self.assertTypeError(
            "sfn main() {\n let x: Int = 99999999999999999999\n}\n", "does not fit in Int")
        self.assertIn("64-bit", err.hint or "")

    def test_largest_int_literal_is_accepted(self):
        check("sfn main() {\n let x: Int = 9223372036854775807\n}\n")

    def test_list_elements_check_as_any(self):
        check("sfn main() {\n let xs: List = [1, 2]\n sprint(xs[0] + 1)\n}\n")

    # -- calls ---------------------------------------------------------------
    def test_user_arity(self):
        self.assertTypeError("sfn f(a: Int) {\n}\nsfn main() {\n f()\n}\n",
                             "expects 1 argument")

    def test_user_argument_type(self):
        self.assertTypeError('sfn f(a: Int) {\n}\nsfn main() {\n f("s")\n}\n',
                             "must be Int")

    def test_native_arity(self):
        self.assertTypeError("sfn main() {\n sprint(math.abs())\n}\n", "not imported")

    def test_native_arity_with_import(self):
        self.assertTypeError("use math\nsfn main() {\n sprint(math.abs())\n}\n",
                             "expects 1 argument")

    def test_native_argument_type(self):
        self.assertTypeError('sfn main() {\n sprint(string.trim(1))\n}\n', "not imported")

    def test_assert_optional_message(self):
        check('sfn main() {\n assert(oui)\n assert(oui, "why")\n}\n')

    # -- returns -------------------------------------------------------------
    def test_return_at_top_level(self):
        self.assertTypeError("ret 1\n", "top level")

    def test_bare_return_in_unit_function_is_fine(self):
        check("sfn main() {\n ret\n}\n")

    def test_missing_return_path(self):
        self.assertTypeError("sfn f(n: Int) -> Int {\n si n > 0 {\n  ret 1\n }\n}\n"
                             "sfn main() {\n}\n", "can finish without returning")

    def test_return_value_in_unit_function(self):
        self.assertTypeError("sfn f() {\n ret 1\n}\nsfn main() {\n}\n",
                             "returns Unit")

    def test_return_type_mismatch(self):
        self.assertTypeError('sfn f() -> Int {\n ret "s"\n}\nsfn main() {\n}\n',
                             "must return Int")

    def test_if_else_both_returning_is_accepted(self):
        check("sfn f(n: Int) -> Int {\n si n > 0 {\n  ret 1\n } sino {\n  ret 2\n }\n}\n"
              "sfn main() {\n}\n")

    # -- loops ---------------------------------------------------------------
    def test_per_over_non_iterable(self):
        self.assertTypeError("sfn main() {\n per x in 5 {\n }\n}\n", "needs a List, Map or String")

    def test_per_loop_variable_is_immutable(self):
        self.assertTypeError("sfn main() {\n per x in [1] {\n  x = 2\n }\n}\n", "constant")

    def test_halt_code_must_be_int(self):
        self.assertTypeError('sfn main() {\n halt("x")\n}\n', "must be Int")

    # -- modules -------------------------------------------------------------
    def test_unknown_module(self):
        self.assertTypeError("use nope\nsfn main() {\n}\n", "unknown module")

    def test_planned_module(self):
        self.assertTypeError("use json\nsfn main() {\n}\n", "not implemented yet")

    def test_module_member_requires_import(self):
        self.assertTypeError("sfn main() {\n sprint(math.abs(1))\n}\n", "not imported")

    def test_unknown_member(self):
        self.assertTypeError("use math\nsfn main() {\n sprint(math.nope(1))\n}\n",
                             "has no function")

    def test_constant_used_as_function(self):
        self.assertTypeError("use math\nsfn main() {\n sprint(math.pi())\n}\n",
                             "is a constant")

    def test_function_used_without_call(self):
        self.assertTypeError("use math\nsfn main() {\n sprint(math.abs)\n}\n",
                             "must be called")

    def test_module_constant_type(self):
        checker = check("use math\nsfn main() {\n let x: Float = math.pi\n}\n")
        self.assertIn("math", checker.modules)


if __name__ == "__main__":
    unittest.main()
