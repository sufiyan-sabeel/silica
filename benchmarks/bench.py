#!/usr/bin/env python3
"""Benchmark Silica against CPython on equivalent workloads.

Each Silica program in benchmarks/silica/ has a matching Python function here
that performs the same work with the same algorithm, so the comparison measures
the implementations rather than the problems.

Run:  python3 benchmarks/bench.py [--runs N]

Results are printed, not stored: docs/PERFORMANCE.md records one real run and
states the machine and versions. Never quote a speed-up that this script has
not produced on the machine you are quoting.
"""

import io
import os
import platform
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silica.engine import compile_source, run_chunk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SILICA_DIR = os.path.join(HERE, "silica")


def py_arith_loop():
    n = 0
    total = 0
    while n < 1000000:
        total = total + n * 2 - 1
        n = n + 1
    return total


def py_recursion():
    def fib(n):
        if n < 2:
            return n
        return fib(n - 1) + fib(n - 2)
    return fib(24)


def py_collections():
    xs = []
    i = 0
    while i < 200000:
        xs.append(i)
        i += 1
    total = 0
    for x in xs:
        total += x
    return "%d %d" % (total, len(sorted(xs[::-1])))


def py_strings():
    parts = []
    i = 0
    while i < 20000:
        parts.append("item")
        i += 1
    joined = ",".join(parts)
    split = joined.split(",")
    return "%d %d" % (len(joined), len(split))


BENCHMARKS = [
    ("arithmetic loop (1e6 iterations)", "arith_loop.sc", py_arith_loop, "999998000000"),
    ("recursion (fib 24)", "recursion.sc", py_recursion, "46368"),
    ("collections (200k push + iterate + sort)", "collections.sc", py_collections,
     "19999900000 200000"),
    ("strings (20k join + split)", "strings.sc", py_strings, "99999 20000"),
]


def run_silica(path, runs):
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    chunk = compile_source(source, path).chunk
    best = None
    output = None
    for _ in range(runs):
        out = io.StringIO()
        start = time.perf_counter()
        run_chunk(chunk, path, stdin=io.StringIO(""), stdout=out)
        elapsed = time.perf_counter() - start
        output = out.getvalue().strip()
        best = elapsed if best is None else min(best, elapsed)
    return best, output


def run_python(func, runs):
    best = None
    output = None
    for _ in range(runs):
        start = time.perf_counter()
        output = str(func())
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best, output


def main(argv):
    runs = 3
    if "--runs" in argv:
        runs = int(argv[argv.index("--runs") + 1])

    print("Silica benchmark suite")
    print("  host      : %s %s" % (platform.system(), platform.machine()))
    print("  python    : %s" % platform.python_version())
    print("  silica    : %s (bytecode VM)" % _silica_version())
    print("  runs      : best of %d" % runs)
    print()
    header = "%-42s %10s %10s %10s  %s" % ("workload", "silica", "python", "ratio", "check")
    print(header)
    print("-" * len(header))

    failures = 0
    for label, filename, pyfunc, expected in BENCHMARKS:
        path = os.path.join(SILICA_DIR, filename)
        s_time, s_out = run_silica(path, runs)
        p_time, p_out = run_python(pyfunc, runs)
        ok = (s_out.replace("\n", " ").strip() == expected.replace("\n", " ").strip()
              and p_out.replace("\n", " ").strip() == expected.replace("\n", " ").strip())
        if not ok:
            failures += 1
        ratio = s_time / p_time if p_time else float("inf")
        print("%-42s %9.1fms %9.1fms %9.2fx  %s" % (
            label, s_time * 1000, p_time * 1000, ratio, "ok" if ok else "MISMATCH"))
        if not ok:
            print("    silica output: %r" % s_out)
            print("    python output: %r" % p_out)

    print()
    print("ratio = silica time / python time; above 1.00x means Silica is slower.")
    return 1 if failures else 0


def _silica_version():
    from silica import __version__
    return __version__


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
