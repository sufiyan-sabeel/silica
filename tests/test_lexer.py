"""Lexer tests: tokens, locations, literals, comments, newline handling."""

import unittest

from silica.errors import LexError
from silica.lexer import tokenize
from silica.tokens import KEYWORDS


def kinds(source):
    tokens, _comments = tokenize(source)
    return [(t.kind, t.value) for t in tokens]


class LexerTests(unittest.TestCase):
    def test_keywords_are_reserved(self):
        for word in ("sprint", "input", "dit", "si", "sino", "und", "ou", "non",
                     "oui", "nein", "tant", "per", "sfn", "ret", "use", "fin", "halt"):
            self.assertIn(word, KEYWORDS)
            tokens, _ = tokenize(word)
            self.assertEqual(tokens[0].kind, "kw", word)
            self.assertEqual(tokens[0].value, word)

    def test_identifiers_are_not_keywords(self):
        tokens, _ = tokenize("square Sfn if else fn return")
        self.assertTrue(all(t.kind == "ident" for t in tokens[:-1]))

    def test_integer_and_float_literals(self):
        tokens, _ = tokenize("0 42 3.5 1e3 2.5e-2")
        values = [(t.kind, t.value) for t in tokens[:-1]]
        self.assertEqual(values, [("int", 0), ("int", 42), ("float", 3.5),
                                  ("float", 1000.0), ("float", 0.025)])

    def test_string_escapes(self):
        tokens, _ = tokenize(r'"a\nb\tc\"d\\e\u0041"')
        self.assertEqual(tokens[0].value, 'a\nb\tc"d\\eA')

    def test_operators_are_maximally_munched(self):
        tokens, _ = tokenize("== != <= >= -> < > = + - * / %")
        values = [t.value for t in tokens[:-1]]
        self.assertEqual(values, ["==", "!=", "<=", ">=", "->", "<", ">", "=",
                                  "+", "-", "*", "/", "%"])

    def test_locations_track_lines_and_columns(self):
        tokens, _ = tokenize("let a = 1\nlet b = 2\n")
        b_token = [t for t in tokens if t.value == "b"][0]
        self.assertEqual((b_token.line, b_token.col), (2, 5))

    def test_newlines_are_significant(self):
        tokens, _ = tokenize("let a = 1\nlet b = 2")
        self.assertEqual([t.kind for t in tokens].count("newline"), 1)

    def test_newlines_inside_parentheses_are_ignored(self):
        tokens, _ = tokenize("sprint(\n  1\n)\n")
        self.assertEqual([t.kind for t in tokens].count("newline"), 1)

    def test_comments_are_recorded_not_emitted(self):
        tokens, comments = tokenize("# first\nlet a = 1 // second\n")
        self.assertEqual(len(comments), 2)
        self.assertNotIn("#", [t.value for t in tokens])

    def test_unknown_character_reports_location(self):
        with self.assertRaises(LexError) as ctx:
            tokenize("let a = 1\nlet b = @")
        self.assertEqual((ctx.exception.line, ctx.exception.col), (2, 9))

    def test_single_quotes_are_a_delimiter(self):
        # 0.9.0: single quotes used to be rejected with a hint; they are now a
        # real delimiter, and `tests/test_string_delimiters.py` covers all four
        tokens, _ = tokenize("sprint('hi')")
        self.assertEqual(tokens[2].kind, "string")
        self.assertEqual(tokens[2].value, "hi")

    def test_unterminated_string(self):
        with self.assertRaises(LexError):
            tokenize('sprint("abc)')

    def test_bad_escape(self):
        with self.assertRaises(LexError):
            tokenize(r'"a\qb"')

    def test_malformed_number(self):
        with self.assertRaises(LexError):
            tokenize("12abc")

    def test_eof_token_always_last(self):
        tokens, _ = tokenize("")
        self.assertEqual(tokens[-1].kind, "eof")


if __name__ == "__main__":
    unittest.main()
