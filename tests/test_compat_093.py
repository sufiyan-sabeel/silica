"""Compatibility gate: programs written for Silica 0.9.3 must behave identically.

Each case is a small, representative program using the language as it stood
before the 0.10.0 work, with the exact output it produced. If any of these change,
the release is not a superset of 0.9.3 and must not ship.

The point is not to re-test the compiler (the rest of the suite does that) but to
pin the *surface*: keywords, operators, literals, control flow, native modules,
structs, classes, generics and capabilities, as a user would write them.
"""

import io
import unittest

from silica.capabilities import CapabilitySet, FS_READ
from silica.engine import run_source


def run_program(source, capabilities=None):
    out = io.StringIO()
    code = run_source(source, "<compat>", stdin=io.StringIO(""), stdout=out,
                      stderr=io.StringIO(), capabilities=capabilities)
    return code, out.getvalue()


#: (label, program, expected stdout) — every program is 0.9.3 syntax.
PROGRAMS = [
    ("hello", 'sfn main() {\n    sprint("Hello from Silica")\n}\n',
     "Hello from Silica\n"),

    ("keywords and booleans",
     'sfn main() {\n    let a: Bool = oui\n    let b: Bool = nein\n'
     '    sprint(a)\n    sprint(b)\n    si a und nein {\n        sprint("no")\n'
     '    }\n    sino {\n        sprint("yes")\n    }\n}\n',
     "oui\nnein\nyes\n"),

    # Int / Int truncates; a Float on either side promotes. Pinned because a
    # later "fix" to make division always float would be a breaking change.
    ("arithmetic, comparison and precedence",
     'sfn main() {\n    sprint(2 + 3 * 4)\n    sprint((2 + 3) * 4)\n'
     '    sprint(10 / 4)\n    sprint(10.0 / 4)\n    sprint(10 % 3)\n'
     '    sprint(2 < 3)\n    sprint(1 == 1.0)\n}\n',
     "14\n20\n2\n2.5\n1\noui\noui\n"),

    ("integer overflow wraps at 64 bits",
     'sfn main() {\n    let big: Int = 9223372036854775807\n'
     '    sprint(big + 1)\n}\n',
     "-9223372036854775808\n"),

    ("control flow: tant, break, continue, fin",
     'sfn main() {\n    let i: Int = 0\n    let total: Int = 0\n'
     '    tant i < 10 {\n        i = i + 1\n        si i % 2 == 0 {\n'
     '            continue\n        }\n        si i > 7 {\n            break\n'
     '        }\n        total = total + i\n    }\n    sprint(total)\n}\n',
     "16\n"),

    ("for over a list and a map",
     'sfn main() {\n    let xs: List = [1, 2, 3]\n    let sum: Int = 0\n'
     '    per x in xs {\n        sum = sum + x\n    }\n    sprint(sum)\n'
     '    let m: Map = {"a": 1, "b": 2}\n    per key in m {\n        dit(key)\n'
     '    }\n    sprint("")\n}\n',
     "6\nab\n"),

    ("string literals: single, double and escapes",
     "sfn main() {\n    sprint('single')\n    sprint(\"double\")\n"
     '    sprint("tab:\\there")\n    sprint("quote: \\"ok\\"")\n}\n',
     'single\ndouble\ntab:\there\nquote: "ok"\n'),

    ("functions, recursion and early return",
     'sfn fib(n: Int) -> Int {\n    si n < 2 {\n        ret n\n    }\n'
     '    ret fib(n - 1) + fib(n - 2)\n}\n'
     'sfn main() {\n    sprint(fib(10))\n}\n',
     "55\n"),

    ("structs: construction, fields, equality, printing",
     'struct Point {\n    x: Int\n    y: Int\n}\n'
     'sfn main() {\n    let p: Point = Point(1, 2)\n    sprint(p.x + p.y)\n'
     '    sprint(p)\n    sprint(p == Point(1, 2))\n}\n',
     "3\nPoint(x: 1, y: 2)\noui\n"),

    ("named struct arguments",
     'struct Point {\n    x: Int\n    y: Int\n}\n'
     'sfn main() {\n    let p: Point = Point(y: 5, x: 2)\n    sprint(p.x)\n'
     '    sprint(p.y)\n}\n',
     "2\n5\n"),

    ("classes: methods, private fields, statics",
     'class Counter {\n    value: Int\n    private label: String\n\n'
     '    sfn bump() -> Int {\n        self.value = self.value + 1\n'
     '        ret self.value\n    }\n\n'
     '    sfn describe() -> String {\n        ret self.label + str(self.value)\n'
     '    }\n\n'
     '    static sfn zero(label: String) -> Counter {\n        ret Counter(0, label)\n'
     '    }\n}\n'
     'sfn main() {\n    let c: Counter = Counter.zero("hits=")\n'
     '    sprint(c.bump())\n    sprint(c.bump())\n    sprint(c.describe())\n'
     '    sprint(Counter(0, "a") == Counter(0, "a"))\n}\n',
     "1\n2\nhits=2\nnein\n"),

    ("generics: inference, constraints, containers",
     'struct Box<T> {\n    value: T\n}\n'
     'sfn first<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n'
     'sfn twice<T: Numeric>(x: T) -> T {\n    ret x + x\n}\n'
     'sfn main() {\n    let b: Box<Int> = Box(7)\n    sprint(b.value)\n'
     '    sprint(first([4, 5]))\n    sprint(twice(21))\n'
     '    let m: Map<String, List<Int>> = {"a": [1, 2]}\n'
     '    sprint(m["a"][1])\n}\n',
     "7\n4\n42\n2\n"),

    ("native modules: math, string, collections, json",
     'use math\nuse string\nuse collections\nuse json\n'
     'sfn main() {\n    sprint(math.abs(-3))\n    sprint(string.upper("ok"))\n'
     '    sprint(collections.sum([1, 2, 3]))\n'
     '    sprint(json.stringify({"a": 1}))\n}\n',
     "3\nOK\n6\n{\"a\":1}\n"),

    ("filesystem behind a capability",
     'use fs\nsfn main() {\n    sprint(fs.exists("compat-probe.txt"))\n}\n',
     "nein\n"),
]


#: Programs that need a capability to run at all.
GRANTS = {
    "filesystem behind a capability":
        CapabilitySet().grant(FS_READ, "."),
}


class CompatibilityTests(unittest.TestCase):
    def test_every_program_behaves_as_it_did(self):
        for label, program, expected in PROGRAMS:
            with self.subTest(program=label):
                code, out = run_program(program, GRANTS.get(label))
                self.assertEqual(code, 0)
                self.assertEqual(out, expected)

    def test_a_capability_is_still_required_for_the_filesystem(self):
        program = ('use fs\nsfn main() {\n    fs.write_text("x.txt", "y")\n}\n')
        with self.assertRaises(Exception) as ctx:
            run_program(program)
        self.assertIn("capability", str(ctx.exception).lower())

    def test_unknown_and_planned_modules_still_fail_loudly(self):
        for module, fragment in (("nope", "unknown module"),
                                 ("http", "planned")):
            with self.subTest(module=module):
                with self.assertRaises(Exception) as ctx:
                    run_program("use %s\nsfn main() {\n}\n" % module)
                self.assertIn(fragment, str(ctx.exception).lower())

    def test_a_type_error_is_still_a_type_error(self):
        with self.assertRaises(Exception) as ctx:
            run_program('sfn main() {\n    let n: Int = "text"\n}\n')
        self.assertIn("cannot initialise", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
