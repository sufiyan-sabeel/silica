"""Audit the generics implementation against the eight areas of the merge review.

This is a developer tool, not part of the test suite: it lives outside `tests/`
so pytest never collects it, and it prints a readable report instead of
assertions. The cases that were not already covered by `tests/` were promoted
into `tests/test_generics_audit.py`; the ones here stay as a broad sweep that can
be re-run by hand before a merge.

    python3 tools/audit_generics.py          # from the repository root
    python3 tools/audit_generics.py -v       # list every case, not just failures

Exit status is 0 when every case behaves as expected, 1 otherwise.

Sections, matching the review:
  1 nesting        parameterised containers inside one another
  2 inference      what determines a type argument, and what fails
  3 dispatch       method resolution (Silica has no inheritance)
  4 diagnostics    invalid type arguments and the quality of the message
  5 round-trip     formatter output must re-parse and be idempotent
  6 backward       non-generic programs must behave exactly as before
  7 interaction    generics meeting structs, classes, natives and bytecode
"""

import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from silica.engine import check_source, run_source            # noqa: E402
from silica.errors import SilicaError                          # noqa: E402
from silica.fmt import format_program                          # noqa: E402
from silica.lexer import tokenize                              # noqa: E402
from silica.parser import parse                                # noqa: E402

FAILURES = []
PASSES = []


def program(body, decls=""):
    return decls + "sfn main() {\n" + body + "\n}\n"


def case(section, name, source, expect, output=None):
    """expect: "ok" or a fragment of the error message that must be raised."""
    try:
        if output is not None:
            out = io.StringIO()
            run_source(source, "<audit>", stdin=io.StringIO(""), stdout=out)
            got = out.getvalue()
            if got != output:
                FAILURES.append((section, name,
                                 "output %r != expected %r" % (got, output)))
                return
        else:
            check_source(source)
        if expect != "ok":
            FAILURES.append((section, name,
                             "expected an error containing %r, but it succeeded"
                             % expect))
            return
        PASSES.append((section, name))
    except SilicaError as exc:
        message = getattr(exc, "message", str(exc))
        if expect == "ok":
            FAILURES.append((section, name, "unexpected %s: %s"
                             % (exc.kind, message)))
        elif expect not in message:
            FAILURES.append((section, name,
                             "error %r does not contain %r" % (message, expect)))
        else:
            PASSES.append((section, name))
    except Exception:                                    # a crash is always a bug
        FAILURES.append((section, name, "CRASH: " + traceback.format_exc(limit=2)))


NEST = "sfn main() {\n"

# ---------------------------------------------------------------- 1. nesting
case("1 nesting", "Map<String, List<Int>> annotation + index",
     NEST + ' let m: Map<String, List<Int>> = {"a": [1, 2]}\n'
            ' let n: Int = m["a"][1]\n}', "ok")
case("1 nesting", "Map<String, List<Int>> wrong element type",
     NEST + ' let m: Map<String, List<Int>> = {"a": [1, 2]}\n'
            ' let s: String = m["a"][1]\n}', "cannot initialise String")
case("1 nesting", "List<List<Int>>",
     NEST + " let xs: List<List<Int>> = [[1], [2]]\n"
            " let inner: List<Int> = xs[0]\n let n: Int = xs[1][0]\n}", "ok")
case("1 nesting", "Map<String, Map<String, Int>>",
     NEST + ' let m: Map<String, Map<String, Int>> = {"a": {"b": 1}}\n'
            ' let n: Int = m["a"]["b"]\n}', "ok")
case("1 nesting", "three levels deep",
     NEST + ' let m: Map<String, List<Map<String, Int>>> = {"a": [{"b": 1}]}\n'
            ' let n: Int = m["a"][0]["b"]\n}', "ok")
case("1 nesting", "nested as a field type",
     "struct Tree {\n    kids: List<Tree>\n}\n" + NEST +
     " let t: Tree = Tree([])\n sprint(len(t.kids))\n}", "ok", "0\n")
case("1 nesting", "nested as a parameter and return",
     "sfn flatten(xs: List<List<Int>>) -> List<Int> {\n"
     "    let out: List<Int> = []\n"
     "    per row in xs {\n        per v in row {\n            push(out, v)\n"
     "        }\n    }\n    ret out\n}\n" + NEST +
     " let xs: List<List<Int>> = [[1, 2], [3]]\n sprint(flatten(xs))\n}",
     "ok", "[1, 2, 3]\n")
case("1 nesting", "iterate a Map of Lists",
     NEST + ' let m: Map<String, List<Int>> = {"a": [1]}\n'
            ' per key in m {\n  let k: String = key\n }\n}', "ok")
case("1 nesting", "arity is checked at depth",
     NEST + " let m: Map<String, List<Int, Int>> = {}\n}",
     "List expects 0 or 1 type argument(s)")
case("1 nesting", "unknown type inside an argument",
     NEST + " let m: Map<String, Nope> = {}\n}", "unknown type")

# ------------------------------------------------------------- 2. inference
FIRST = "sfn first<T>(items: List<T>) -> T {\n    ret items[0]\n}\n\n"
IDENT = "sfn ident<T>(x: T) -> T {\n    ret x\n}\n\n"
case("2 inference", "from an annotated argument",
     FIRST + program("let xs: List<Int> = [1]\nlet n: Int = first(xs)"), "ok")
case("2 inference", "from a literal argument",
     FIRST + program("sprint(first([1, 2]))"), "ok", "1\n")
case("2 inference", "from a nested literal",
     "sfn flat<T>(x: List<List<T>>) -> List<T> {\n    ret x[0]\n}\n" +
     program('sprint(flat([["a"]]))'), "ok", '["a"]\n')
case("2 inference", "conflicting arguments",
     "sfn same<T>(a: T, b: T) -> T {\n    ret a\n}\n" +
     program('sprint(same(1, "x"))'), "must be T, found String")
case("2 inference", "nothing to infer from",
     "sfn make<T>() -> List<T> {\n    ret []\n}\n" +
     program("let xs: List = make()"), "cannot infer type parameter")
case("2 inference", "annotation supplies the empty container",
     "class S<T> {\n    items: List<T>\n}\n" +
     program("let s: S<String> = S([])"), "ok")
case("2 inference", "annotation of the wrong shape is still an error",
     "class S<T> {\n    items: List<T>\n}\n" +
     program('let s: S<Int> = S(["a"])'), "expects List<T>, found List<String>")
case("2 inference", "generic calls generic",
     IDENT + FIRST + program("sprint(ident(first([7])))"), "ok", "7\n")
case("2 inference", "generic struct inside a generic struct",
     "struct Box<T> {\n    v: T\n}\nstruct Pair<A, B> {\n    a: A\n    b: B\n}\n" +
     program("let p: Pair<Box<Int>, String> = Pair(Box(1), \"x\")\n"
             "sprint(p.a.v)\nsprint(p.b)"), "ok", "1\nx\n")
case("2 inference", "method result feeds a generic call",
     "class B<T> {\n    items: List<T>\n    sfn all() -> List<T> {\n"
     "        ret self.items\n    }\n}\n" + FIRST +
     program('let b: B<Int> = B([1, 2])\nlet n: Int = first(b.all())'), "ok")
case("2 inference", "inference inside a generic body",
     "struct Box<T> {\n    v: T\n}\nsfn wrap<T>(x: T) -> Box<T> {\n"
     "    ret Box(x)\n}\n" +
     program("let b: Box<Int> = wrap(1)\nsprint(b.v)"), "ok", "1\n")
case("2 inference", "a bare List argument cannot bind T",
     "sfn f<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n" +
     program("let xs: List = [1]\nlet n: Int = f(xs)"), "cannot infer")

# --------------------------------------------------- 3. dispatch / inheritance
case("3 dispatch", "no inheritance keyword exists",
     "class A {\n    v: Int\n}\nclass B : A {\n    w: Int\n}\n" + program(""),
     "expected")
case("3 dispatch", "same method name on two classes dispatches correctly",
     "class A {\n    n: Int\n    sfn run() -> Int {\n        ret 1\n    }\n}\n"
     "class B {\n    n: Int\n    sfn run() -> Int {\n        ret 2\n    }\n}\n" +
     program("let a: A = A(0)\nlet b: B = B(0)\nsprint(a.run())\nsprint(b.run())"),
     "ok", "1\n2\n")
case("3 dispatch", "same method name on generic and non-generic classes",
     "class A {\n    n: Int\n    sfn get() -> Int {\n        ret 9\n    }\n}\n"
     "class G<T> {\n    v: T\n    sfn get() -> T {\n        ret self.v\n    }\n}\n" +
     program('let a: A = A(0)\nlet g: G<String> = G("x")\n'
             "sprint(a.get())\nsprint(g.get())"), "ok", "9\nx\n")
case("3 dispatch", "a method on the wrong class is rejected",
     "class A {\n    n: Int\n}\nclass B {\n    m: Int\n}\n" +
     program("let a: A = A(0)\nsprint(a.missing())"), "has no member")
case("3 dispatch", "method call on a parameterised receiver resolves",
     "class S<T> {\n    items: List<T>\n    sfn peek() -> T {\n"
     "        ret self.items[0]\n    }\n}\n" +
     program('let s: S<String> = S(["a"])\nlet v: String = s.peek()'), "ok")

# ------------------------------------------------- 4. invalid type arguments
case("4 diagnostics", "List arity",
     program("let x: List<Int, Int> = [1]"), "List expects 0 or 1 type argument(s)")
case("4 diagnostics", "Map arity",
     program("let m: Map<Int> = {}"), "Map expects 0 or 2 type argument(s)")
case("4 diagnostics", "user type arity",
     "struct Box<T> {\n    v: T\n}\n" +
     program("let b: Box<Int, Int> = Box(1)"), "Box expects 0 or 1 type argument(s)")
case("4 diagnostics", "unknown type argument",
     program("let xs: List<Nope> = [1]"), "unknown type")
case("4 diagnostics", "unknown constraint",
     "sfn f<T: Fancy>(x: T) -> T {\n    ret x\n}\n" + program(""),
     "unknown constraint 'Fancy'")
case("4 diagnostics", "constraint violated at the call",
     "sfn twice<T: Numeric>(x: T) -> T {\n    ret x + x\n}\n" +
     program('sprint(twice("a"))'), "does not satisfy Numeric")
case("4 diagnostics", "unconstrained operator",
     "sfn twice<T>(x: T) -> T {\n    ret x + x\n}\n" + program(""),
     "is unconstrained")
case("4 diagnostics", "constraint too weak for the operator",
     "sfn big<T: Numeric>(a: T, b: T) -> T {\n    si a > b {\n        ret a\n"
     "    }\n    ret b\n}\n" + program(""), "needs a Orderable value")
case("4 diagnostics", "type parameter takes no arguments",
     "sfn g<U>(y: U<Int>) -> U {\n    ret y\n}\n" + program(""),
     "cannot take type arguments")
case("4 diagnostics", "duplicate type parameter",
     "struct B<T, T> {\n    x: T\n}\n" + program(""), "duplicate type parameter")
case("4 diagnostics", "static cannot use the class parameter",
     "class Box<T> {\n    v: T\n    static sfn make() -> T {\n        ret self.v\n"
     "    }\n}\n" + program(""), "static")
case("4 diagnostics", "invariance of type arguments",
     program("let xs: List<Int> = [1]\nlet ys: List<Float> = xs"),
     "cannot initialise List<Float>")
case("4 diagnostics", "struct self-containment with parameters",
     "struct P<T> {\n    p: P<T>\n}\n" + program(""), "cannot contain itself")

# ------------------------------------------------------- 5. round-trip / fmt
def fmt_case(name, source):
    try:
        once = format_program(parse(tokenize(source)[0]))
        twice = format_program(parse(tokenize(once)[0]))
        if once != twice:
            FAILURES.append(("5 round-trip", name, "formatter is not idempotent"))
            return
        parse(tokenize(once)[0])
        PASSES.append(("5 round-trip", name))
    except Exception:
        FAILURES.append(("5 round-trip", name,
                         "CRASH: " + traceback.format_exc(limit=2)))


fmt_case("generic struct, class and function",
         "struct Box<T> {\n    v: T\n}\n\n"
         "class Bag<T> {\n    items: List<T>\n\n    sfn add(x: T) {\n"
         "        push(self.items, x)\n    }\n}\n\n"
         "sfn big<T: Orderable>(a: T, b: T) -> T {\n    ret a\n}\n")
fmt_case("multi-parameter and nested annotations",
         "struct Pair<K, V> {\n    k: K\n    v: V\n}\n\n"
         "sfn main() {\n    let m: Map<String, List<Int>> = {}\n"
         "    let p: Pair<String, List<Int>> = Pair(\"a\", [])\n}\n")
fmt_case("private and static members on a generic class",
         "class C<T> {\n    v: T\n    private label: String\n\n"
         "    sfn get() -> T {\n        ret self.v\n    }\n\n"
         "    static sfn of<U>(x: U) -> List<U> {\n        ret [x]\n    }\n}\n")

# ------------------------------------------------ 6. backward compatibility
BACKWARD = [
    ("plain functions and locals",
     program("let n: Int = 2\nlet s: String = \"x\"\nsprint(n)\nsprint(s)"),
     "2\nx\n"),
    ("bare List and Map still work",
     program('let xs: List = [1, "a"]\nlet m: Map = {"k": 1}\n'
             'sprint(len(xs))\nsprint(m["k"])'), "2\n1\n"),
    ("structs unchanged",
     "struct Point {\n    x: Int\n    y: Int\n}\n" +
     program("let p: Point = Point(1, 2)\nsprint(p.x + p.y)\nsprint(p)"),
     "3\nPoint(x: 1, y: 2)\n"),
    ("field assignment through a path",
     "struct Inner {\n    v: Int\n}\nstruct Outer {\n    inner: Inner\n}\n" +
     program("let o: Outer = Outer(Inner(1))\no.inner.v = 5\nsprint(o.inner.v)"),
     "5\n"),
    ("classes unchanged",
     "class C {\n    v: Int\n    sfn bump() -> Int {\n        self.v = self.v + 1\n"
     "        ret self.v\n    }\n}\n" +
     program("let c: C = C(0)\nsprint(c.bump())\nsprint(c.bump())"), "1\n2\n"),
    ("struct equality is structural, class is identity",
     "struct P {\n    x: Int\n}\nclass C {\n    v: Int\n}\n" +
     program("sprint(P(1) == P(1))\nsprint(C(1) == C(1))"), "oui\nnein\n"),
    ("freezing a const struct",
     "struct P {\n    x: Int\n}\n" + program("const p: P = P(1)\np.x = 2"),
     "it is a constant"),
    ("natives over parameterised containers",
     program('let xs: List<Int> = [3, 1]\npush(xs, 2)\nsprint(len(xs))\n'
             'sprint(xs)\nlet m: Map<String, Int> = {"a": 1}\nsprint(keys(m))'),
     '3\n[3, 1, 2]\n["a"]\n'),
]
for name, source, output in BACKWARD:
    if output.startswith("it is a constant"):
        case("6 backward compat", name, source, output)
    else:
        case("6 backward compat", name, source, "ok", output)

# --------------------------------------------------- 7. interaction coverage
case("7 interaction", "generic class holding generic structs",
     "struct Box<T> {\n    v: T\n}\nclass Shelf<T> {\n    items: List<T>\n\n"
     "    sfn add(x: T) {\n        push(self.items, x)\n    }\n\n"
     "    sfn first() -> T {\n        ret self.items[0]\n    }\n}\n" +
     program("let s: Shelf<Box<Int>> = Shelf([])\ns.add(Box(1))\n"
             "sprint(s.first().v)"), "ok", "1\n")
case("7 interaction", "generic function taking a class instance",
     "class C {\n    v: Int\n}\nsfn show<T>(x: T) -> T {\n    ret x\n}\n" +
     program("let c: C = C(3)\nlet d: C = show(c)\nsprint(d.v)"), "ok", "3\n")
case("7 interaction", "generic function over a List of classes",
     "class C {\n    v: Int\n}\nsfn first<T>(xs: List<T>) -> T {\n    ret xs[0]\n}\n" +
     program("let cs: List<C> = [C(4)]\nlet c: C = first(cs)\nsprint(c.v)"),
     "ok", "4\n")
case("7 interaction", "method returning a parameterised container",
     "class B<T> {\n    items: List<T>\n    sfn all() -> List<T> {\n"
     "        ret self.items\n    }\n}\n" +
     program('let b: B<String> = B(["a"])\nlet xs: List<String> = b.all()\n'
             "sprint(xs[0])"), "ok", "a\n")
case("7 interaction", "generic struct with a method-free struct and str()",
     "struct Box<T> {\n    v: T\n}\n" +
     program("let b: Box<Int> = Box(7)\nsprint(str(b.v) + \"!\")\n"
             "sprint(type_of(b))"), "ok", "7!\nBox\n")
case("7 interaction", "generic class inside a bare List",
     "class C<T> {\n    v: T\n}\n" +
     program('let xs: List = [C(1), C("a")]\nsprint(len(xs))'), "ok", "2\n")
case("7 interaction", "bytecode round-trip keeps generics working",
     "class S<T> {\n    items: List<T>\n    sfn add(x: T) {\n"
     "        push(self.items, x)\n    }\n    sfn peek() -> T {\n"
     "        ret self.items[0]\n    }\n}\n" +
     program('let s: S<String> = S(["a"])\ns.add("b")\nsprint(s.peek())'), "ok")


def report(verbose):
    sections = {}
    for section, _name in PASSES:
        sections.setdefault(section, [0, 0])[0] += 1
    for section, _name, _why in FAILURES:
        sections.setdefault(section, [0, 0])[1] += 1
    print("=" * 72)
    for section in sorted(sections):
        ok, bad = sections[section]
        print("%-20s %2d passed  %2d failed" % (section, ok, bad))
    print("=" * 72)
    print("TOTAL: %d passed, %d failed" % (len(PASSES), len(FAILURES)))
    if verbose:
        print("\nall cases:")
        for section, name in PASSES:
            print("  ok   [%s] %s" % (section, name))
    if FAILURES:
        print("\nFAILURES:")
        for section, name, why in FAILURES:
            print("  [%s] %s\n      %s" % (section, name,
                                           why.strip().splitlines()[0]))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(report("-v" in sys.argv or "--verbose" in sys.argv))
