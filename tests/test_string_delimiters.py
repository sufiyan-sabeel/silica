"""String delimiters: double, single, and the two triple-quoted forms.

Silica accepts four delimiters. The single-character forms are single-line; the
triple-quoted forms are multiline and keep raw newlines in the value. These tests
cover the lexer, the runtime and the formatter, because a delimiter that lexes
but does not survive formatting is a trap rather than a feature.
"""

import unittest

from silica.errors import LexError
from silica.fmt import format_source
from silica.lexer import tokenize

from .helpers import expect_error, run


def out(source, stdin=""):
    return run(source, stdin=stdin)[1]


def program(body):
    return "sfn main() {\n" + body + "\n}\n"


def first_string(source):
    tokens, _ = tokenize(source)
    for token in tokens:
        if token.kind == "string":
            return token
    raise AssertionError("no string token in %r" % source)


class DelimiterEquivalenceTests(unittest.TestCase):
    def test_all_four_delimiters_produce_the_same_value(self):
        forms = ['"silica"', "'silica'", '"""silica"""', "'''silica'''"]
        values = {first_string(form).value for form in forms}
        self.assertEqual(values, {"silica"})

    def test_all_four_delimiters_run_the_same_way(self):
        for form in ['"silica"', "'silica'", '"""silica"""', "'''silica'''"]:
            with self.subTest(form=form):
                self.assertEqual(out(program("    sprint(%s)" % form)), "silica\n")

    def test_single_quotes_allow_embedded_double_quotes(self):
        self.assertEqual(first_string("'he said \"hi\"'").value, 'he said "hi"')
        self.assertEqual(out(program("    sprint('say \"hi\"')")), 'say "hi"\n')

    def test_double_quotes_allow_embedded_single_quotes(self):
        # single quotes used to be a hard lexer error, even inside a string
        self.assertEqual(out(program("    sprint(\"it's fine\")")), "it's fine\n")

    def test_triple_forms_allow_the_other_quote_unescaped(self):
        self.assertEqual(first_string('"""it\'s"""').value, "it's")
        self.assertEqual(first_string("'''say \"hi\"'''").value, 'say "hi"')

    def test_empty_strings_in_every_form(self):
        for form in ['""', "''", '""""""', "''''''"]:
            with self.subTest(form=form):
                self.assertEqual(first_string(form).value, "")
                self.assertEqual(out(program("    sprint(%s)" % form)), "\n")


class MultilineTests(unittest.TestCase):
    def test_triple_double_keeps_raw_newlines(self):
        source = '"""line one\nline two"""'
        self.assertEqual(first_string(source).value, "line one\nline two")

    def test_triple_single_keeps_raw_newlines(self):
        source = "'''a\nb\nc'''"
        self.assertEqual(first_string(source).value, "a\nb\nc")

    def test_multiline_string_prints_over_several_lines(self):
        source = program('    sprint("""one\ntwo""")')
        self.assertEqual(out(source), "one\ntwo\n")

    def test_multiline_string_length_counts_the_newline(self):
        source = program('    let text = """ab\ncd"""\n    sprint(len(text))')
        self.assertEqual(out(source), "5\n")

    def test_multiline_string_can_be_concatenated(self):
        source = program('    let text = """a\nb"""\n    sprint(text + "!")')
        self.assertEqual(out(source), "a\nb!\n")

    def test_source_locations_continue_after_a_multiline_string(self):
        tokens, _ = tokenize('sprint("""a\nb""")\nsprint(1)\n')
        self.assertEqual(tokens[0].line, 1)
        self.assertEqual(tokens[2].value, "a\nb")
        self.assertEqual(tokens[2].line, 1)
        second = [t for t in tokens if t.kind == "kw"][1]
        self.assertEqual(second.line, 3)

    def test_multiline_string_inside_a_function_body(self):
        source = program('    si oui {\n        sprint("""x\ny""")\n    }')
        self.assertEqual(out(source), "x\ny\n")


class EscapeTests(unittest.TestCase):
    def test_escapes_work_in_all_four_forms(self):
        expected = "a\tb\nc"
        for form in ['"a\\tb\\nc"', "'a\\tb\\nc'", '"""a\\tb\\nc"""',
                     "'''a\\tb\\nc'''"]:
            with self.subTest(form=form):
                self.assertEqual(first_string(form).value, expected)

    def test_escaped_quote_of_the_same_kind(self):
        self.assertEqual(first_string(r"'it\'s'").value, "it's")
        self.assertEqual(first_string(r'"a\"b"').value, 'a"b')

    def test_unicode_escape_works_in_a_single_quoted_string(self):
        self.assertEqual(first_string(r"'\u0041'").value, "A")


class ErrorTests(unittest.TestCase):
    def test_unterminated_single_quoted_string(self):
        expect_error(self, "sprint('abc)\n", LexError, "unterminated string")

    def test_unterminated_triple_quoted_string_hints_at_the_closing_triple(self):
        error = expect_error(self, 'sprint("""abc)\n', LexError,
                             "unterminated string literal")
        self.assertIn('"""', error.hint)

    def test_newline_in_a_single_quoted_string_is_rejected(self):
        error = expect_error(self, "sprint('a\nb')\n", LexError, "newline in string")
        self.assertIn("triple-quoted", error.hint)

    def test_unknown_escape_lists_the_quote_escape(self):
        error = expect_error(self, r"sprint('a\qb')" + "\n", LexError,
                             "unknown escape sequence")
        self.assertIn("\\'", error.hint)


class FormatterTests(unittest.TestCase):
    def test_formatter_normalises_to_double_quotes(self):
        formatted = format_source(program("    sprint('single')"))
        self.assertIn('sprint("single")', formatted)

    def test_formatter_escapes_a_multiline_value(self):
        formatted = format_source(program('    sprint("""a\nb""")'))
        self.assertIn('sprint("a\\nb")', formatted)
        self.assertEqual(format_source(formatted), formatted)

    def test_formatting_preserves_meaning(self):
        source = program("    sprint('say \"hi\"')")
        self.assertEqual(out(format_source(source)), out(source))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
