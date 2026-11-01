"""The `random` module: pseudorandom by default, secure on request, never confused."""

import re
import unittest

from .helpers import run


def program(body):
    return "use random\n\nsfn main() {\n" + body + "\n}\n"


def out(body):
    code, text = run(program(body))
    return text


class PseudorandomTests(unittest.TestCase):
    def test_float_is_in_range(self):
        self.assertEqual(out("let x: Float = random.float()\n"
                             "sprint(x >= 0.0)\nsprint(x < 1.0)"), "oui\noui\n")

    def test_int_is_half_open(self):
        self.assertEqual(out("let x: Int = random.int(5, 6)\nsprint(x)"), "5\n")

    def test_int_stays_inside_the_bounds(self):
        body = "let i: Int = 0\n"
        body += "tant i < 200 {\n    let x: Int = random.int(10, 12)\n"
        body += "    si x < 10 { sprint(\"low\") }\n    si x > 11 { sprint(\"high\") }\n"
        body += "    i = i + 1\n}\nsprint(\"done\")"
        self.assertEqual(out(body), "done\n")

    def test_a_seed_makes_the_sequence_reproducible(self):
        self.assertEqual(out("random.seed(42)\nlet a: Int = random.int(0, 1000000)\n"
                             "random.seed(42)\nlet b: Int = random.int(0, 1000000)\n"
                             "sprint(a == b)"), "oui\n")

    def test_a_different_seed_gives_a_different_sequence(self):
        # not a guarantee in theory, but it would be alarming in practice
        self.assertEqual(out("random.seed(1)\nlet a: Int = random.int(0, 1000000000)\n"
                             "random.seed(2)\nlet b: Int = random.int(0, 1000000000)\n"
                             "sprint(a == b)"), "nein\n")

    def test_choice_returns_an_element(self):
        self.assertEqual(out('let xs: List = ["a"]\nsprint(random.choice(xs))'), "a\n")

    def test_shuffle_returns_a_new_list_and_leaves_the_argument_alone(self):
        self.assertEqual(out("let xs: List = [1, 2, 3, 4]\n"
                             "let ys: List = random.shuffle(xs)\n"
                             "sprint(len(xs))\nsprint(len(ys))\n"
                             "sprint(len(ys) == 4)"), "4\n4\noui\n")

    def test_shuffle_keeps_every_element(self):
        self.assertEqual(out("let xs: List = [1, 2, 3]\n"
                             "let ys: List = random.shuffle(xs)\n"
                             "let total: Int = 0\n"
                             "per v in ys {\n    total = total + v\n}\n"
                             "sprint(total)"), "6\n")


class SecureTests(unittest.TestCase):
    def test_secure_bytes_returns_hex_text(self):
        self.assertEqual(out("let s: String = random.secure_bytes(8)\n"
                             "sprint(len(s))"), "16\n")
        self.assertEqual(out('let s: String = random.secure_bytes(8)\n'
                             'sprint(len(s) == 16)'), "oui\n")

    def test_secure_token_is_url_safe_text(self):
        self.assertEqual(out("let s: String = random.secure_token(16)\n"
                             "sprint(len(s) > 16)"), "oui\n")

    def test_secure_int_is_inside_its_bounds(self):
        self.assertEqual(out("let x: Int = random.secure_int(10, 20)\n"
                             "sprint(x >= 10)\nsprint(x < 20)"), "oui\noui\n")

    def test_seeding_does_not_determine_secure_output(self):
        # the CSPRNG is not the seeded generator; if it were, this would match
        self.assertEqual(out("random.seed(5)\nlet a: String = random.secure_bytes(16)\n"
                             "random.seed(5)\nlet b: String = random.secure_bytes(16)\n"
                             "sprint(a == b)"), "nein\n")

    def test_secure_bytes_is_hex_characters(self):
        text = out("sprint(random.secure_bytes(4))").strip()
        self.assertEqual(len(text), 8)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{8}", text), text)


class SafetyTests(unittest.TestCase):
    def test_an_empty_list_cannot_be_chosen_from(self):
        with self.assertRaises(Exception) as ctx:
            run(program("sprint(random.choice([]))"))
        self.assertIn("non-empty", str(ctx.exception))

    def test_an_inverted_range_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program("sprint(random.int(10, 10))"))
        self.assertIn("high > low", str(ctx.exception))

    def test_a_negative_byte_count_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program("sprint(random.secure_bytes(-1))"))
        self.assertIn("non-negative", str(ctx.exception))

    def test_an_absurd_byte_count_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program("sprint(random.secure_bytes(99999999))"))
        self.assertIn("refuses more than", str(ctx.exception))

    def test_the_module_requires_no_capability(self):
        from silica.natives import MODULES
        for name, native in MODULES["random"].items():
            self.assertIsNone(native.requires, name)

    def test_the_secure_functions_are_named_as_such(self):
        # the naming rule is the API: anything secret says `secure_`
        from silica.natives import MODULES
        names = set(MODULES["random"])
        self.assertEqual({n for n in names if n.startswith("secure_")},
                         {"secure_bytes", "secure_int", "secure_token"})
