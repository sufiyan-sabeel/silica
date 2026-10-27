"""The `json` module: mapping, round trips, and the error cases that matter."""

import unittest

from silica.errors import SilicaRuntimeError

from .helpers import run


def out(body):
    return run("use json\nsfn main() {\n" + body + "\n}\n")[1]


def program(body):
    return "use json\nsfn main() {\n" + body + "\n}\n"


class ParseTests(unittest.TestCase):
    def test_scalars(self):
        self.assertEqual(out('sprint(json.parse("null"))'), "unit\n")
        self.assertEqual(out('sprint(json.parse("true"))'), "oui\n")
        self.assertEqual(out('sprint(json.parse("false"))'), "nein\n")
        self.assertEqual(out('sprint(json.parse("42"))'), "42\n")
        self.assertEqual(out('sprint(json.parse("-0"))'), "0\n")
        self.assertEqual(out('sprint(json.parse("2.5"))'), "2.5\n")
        self.assertEqual(out('sprint(json.parse("1e3"))'), "1000.0\n")
        self.assertEqual(out('sprint(json.parse("\\"hi\\""))'), "hi\n")

    def test_types_match_the_mapping_table(self):
        self.assertEqual(out('sprint(type_of(json.parse("42")))'), "Int\n")
        self.assertEqual(out('sprint(type_of(json.parse("42.0")))'), "Float\n")
        self.assertEqual(out('sprint(type_of(json.parse("null")))'), "Unit\n")
        self.assertEqual(out('sprint(type_of(json.parse("[]")))'), "List\n")
        self.assertEqual(out('sprint(type_of(json.parse("{}")))'), "Map\n")
        self.assertEqual(out('sprint(type_of(json.parse("true")))'), "Bool\n")

    def test_whole_float_stays_float(self):
        self.assertEqual(out('sprint(json.parse("1.0"))'), "1.0\n")

    def test_nested_structures(self):
        source = '"{\\"a\\": [1, {\\"b\\": null}], \\"c\\": {\\"d\\": [true]}}"'
        self.assertEqual(out("sprint(json.parse(%s))" % source),
                         '{"a": [1, {"b": unit}], "c": {"d": [oui]}}\n')

    def test_unicode_escapes_and_literals(self):
        self.assertEqual(out('sprint(json.parse("\\"\\\\u00e9t\\\\u00e9\\""))'), "été\n")
        self.assertEqual(out('sprint(json.parse("\\"café\\""))'), "café\n")
        self.assertEqual(out('sprint(json.parse("\\"\\\\ud83d\\\\ude00\\""))'), "😀\n")

    def test_escaped_quotes_and_control_characters(self):
        # the JSON document is: "a<TAB>b<LF>\"c\""  -> 7 characters
        document = '"a\\tb\\n\\"c\\""'
        self.assertEqual(out("sprint(len(json.parse(%s)))" % _quote(document)), "7\n")

    def test_duplicate_keys_keep_the_last_value(self):
        source = '"{\\"k\\": 1, \\"k\\": 2}"'
        self.assertEqual(out("sprint(json.parse(%s))" % source), '{"k": 2}\n')

    def test_integer_out_of_i64_range(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.parse("9223372036854775808"))'))
        self.assertIn("64-bit", str(ctx.exception))

    def test_float_overflow_is_rejected(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.parse("1e400"))'))
        self.assertIn("64-bit", str(ctx.exception))


class ParseErrorTests(unittest.TestCase):
    def test_invalid_json_reports_line_and_column(self):
        source = '"{\\"a\\": 1,}"'
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program("sprint(json.parse(%s))" % source))
        message = str(ctx.exception)
        self.assertIn("invalid JSON", message)
        self.assertIn("line 1", message)
        self.assertIn("column", message)

    def test_error_on_a_later_line(self):
        source = '"{\\n  \\"a\\": 1,\\n  \\"b\\":\\n}"'
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program("sprint(json.parse(%s))" % source))
        self.assertIn("line 4", str(ctx.exception))

    def test_error_hint_shows_the_offending_line(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.parse("{oops}"))'))
        self.assertIn("^", ctx.exception.hint)

    def test_nan_is_not_json(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.parse("NaN"))'))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_infinity_is_not_json(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.parse("Infinity"))'))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_empty_input(self):
        with self.assertRaises(SilicaRuntimeError):
            run(program('sprint(json.parse(""))'))

    def test_trailing_garbage(self):
        with self.assertRaises(SilicaRuntimeError):
            run(program('sprint(json.parse("{} extra"))'))

    def test_non_string_argument_is_a_type_error(self):
        from silica.errors import SilicaTypeError
        with self.assertRaises(SilicaTypeError):
            run(program("sprint(json.parse(42))"))


class StringifyTests(unittest.TestCase):
    def test_compact_form(self):
        self.assertEqual(out('sprint(json.stringify({"a": 1, "b": [1, 2]}))'),
                         '{"a":1,"b":[1,2]}\n')

    def test_scalars(self):
        self.assertEqual(out('sprint(json.stringify(json.parse("null")))'), "null\n")
        self.assertEqual(out("sprint(json.stringify(oui))"), "true\n")
        self.assertEqual(out("sprint(json.stringify(42))"), "42\n")
        self.assertEqual(out("sprint(json.stringify(2.5))"), "2.5\n")
        self.assertEqual(out('sprint(json.stringify("hi"))'), '"hi"\n')

    def test_indent(self):
        self.assertEqual(out('sprint(json.stringify({"a": [1]}, 2))'),
                         '{\n  "a":[\n    1\n  ]\n}\n')

    def test_indent_zero_is_compact(self):
        self.assertEqual(out('sprint(json.stringify({"a": 1}, 0))'), '{"a":1}\n')

    def test_indent_out_of_range(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.stringify({"a": 1}, 99))'))
        self.assertIn("between 0 and 8", str(ctx.exception))

    def test_indent_wrong_type_is_a_type_error(self):
        from silica.errors import SilicaTypeError
        with self.assertRaises(SilicaTypeError):
            run(program('sprint(json.stringify({"a": 1}, "2"))'))

    def test_empty_containers(self):
        self.assertEqual(out("sprint(json.stringify([]))"), "[]\n")
        self.assertEqual(out("sprint(json.stringify({}))"), "{}\n")

    def test_unicode_is_not_escaped(self):
        self.assertEqual(out('sprint(json.stringify("café"))'), '"café"\n')

    def test_quotes_and_newlines_are_escaped(self):
        self.assertEqual(out('sprint(json.stringify("a\\"b\\nc"))'), '"a\\"b\\nc"\n')

    def test_non_string_key_is_rejected_by_the_parser(self):
        from silica.errors import ParseError
        with self.assertRaises(ParseError) as ctx:
            run(program("sprint(json.stringify({1: 2}))"))
        self.assertIn("map keys must be strings", str(ctx.exception))

    def test_encoder_refuses_a_non_string_key_at_runtime(self):
        # The checker rejects a literal Int key; this asserts the runtime guard
        # that protects values built some other way.
        from silica.stdlib_json import _encode
        with self.assertRaises(SilicaRuntimeError) as ctx:
            _encode({1: 2}, None, 0)
        self.assertIn("keys must be Strings", str(ctx.exception))

    def test_nan_has_no_json_form(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            run(program('sprint(json.stringify(float("nan")))'))
        self.assertIn("no JSON representation", str(ctx.exception))

    def test_one_argument_form(self):
        self.assertEqual(out('sprint(json.stringify([1, 2]))'), "[1,2]\n")


class RoundTripTests(unittest.TestCase):
    CASES = [
        'null',
        'true',
        'false',
        '0',
        '-9223372036854775808',
        '9223372036854775807',
        '1.5',
        '"plain"',
        '"café \\u00e9"',
        '[]',
        '{}',
        '[1, [2, [3]]]',
        '{"a": {"b": {"c": [1, null, true]}}}',
        '{"emoji": "😀", "quote": "\\""}',
    ]

    def test_parse_then_stringify_is_stable(self):
        for document in self.CASES:
            with self.subTest(document=document):
                once = out("sprint(json.stringify(json.parse(%s)))" % _quote(document))
                twice = out("sprint(json.stringify(json.parse(%s)))" % _quote(once.strip()))
                self.assertEqual(once, twice)

    def test_build_then_round_trip(self):
        body = ('let m: Map = {"name": "silica", "nums": [1, 2.5, -3], '
                '"ok": oui, "none": json.parse("null")}\n'
                'let text: String = json.stringify(m)\n'
                'sprint(json.stringify(json.parse(text)) == text)')
        self.assertEqual(out(body), "oui\n")


def _quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    unittest.main()
