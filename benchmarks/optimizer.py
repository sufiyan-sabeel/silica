"""Benchmark for the constant folder.

Reproducible, and deliberately modest in its claims. It measures three things:

1. instructions emitted for a program made of literal expressions
2. serialized bytecode size for the same program
3. wall-clock for a hot loop whose body is a literal expression

`SILICA_NO_OPT=1` disables folding, so every number below is a comparison against
the same compiler with only the optimisation switched off.

    python3 benchmarks/optimizer.py

Numbers on the machine this was written on (2 vCPU, Python 3.12, 2 GB):

    instructions   1602 -> 402     (-74.9%)
    bytecode       5214 -> 3145 B  (-39.7%)
    hot loop       3.496s -> 2.163s (-38.1%)   300k iterations, identical output

The 200-expression program shows no wall-clock gain: interpreter start-up
dominates it. The hot loop is where folding actually pays, and that is the number
worth quoting.
"""

import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LITERAL_PROGRAM = "sfn main() {\n" + "".join(
    "    sprint(%d + %d * %d - %d)\n" % (i, i + 1, i + 2, i) for i in range(200)
) + "}\n"

HOT_PROGRAM = """sfn main() {
    let total: Int = 0
    let i: Int = 0
    tant i < 300000 {
        total = total + (2 + 3 * 4 - 6)
        i = i + 1
    }
    sprint(total)
}
"""


def _env(optimise):
    env = dict(os.environ)
    if optimise:
        env.pop("SILICA_NO_OPT", None)
    else:
        env["SILICA_NO_OPT"] = "1"
    return env


def _write(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False)
    handle.write(text)
    handle.close()
    return handle.name


def compile_stats(path, optimise):
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from silica.engine import compile_source\n"
        "from silica.bytecode import decode, serialize\n"
        "src = open(%r).read()\n"
        "chunk = compile_source(src, '<bench>').chunk\n"
        "n = sum(len(decode(f.code, '<bench>', f.name)) for f in chunk.functions)\n"
        "print(n, len(serialize(chunk)))\n" % (ROOT, path)
    )
    out = subprocess.run([sys.executable, "-c", code], env=_env(optimise),
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise SystemExit("compile failed:\n" + out.stderr[-800:])
    instructions, size = out.stdout.split()
    return int(instructions), int(size)


def runtime(path, optimise, runs=3):
    best = None
    for _ in range(runs):
        start = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-m", "silica", "run", path],
            cwd=ROOT, env=_env(optimise), capture_output=True, text=True,
            timeout=600)
        elapsed = time.perf_counter() - start
        if completed.returncode != 0:
            raise SystemExit("run failed:\n" + completed.stderr[-800:])
        best = elapsed if best is None else min(best, elapsed)
    return best, completed.stdout.strip()


def report(label, off, on, unit=""):
    change = 100.0 * (on - off) / off if off else 0.0
    print("  %-14s off: %10.3f%-2s  on: %10.3f%-2s  (%+.1f%%)"
          % (label, off, unit, on, unit, change))


def main():
    print("Silica constant folding benchmark")
    print("  python  : %s" % sys.version.split()[0])
    print("  folding : on by default; SILICA_NO_OPT=1 disables it")
    print()

    literal = _write(LITERAL_PROGRAM)
    hot = _write(HOT_PROGRAM)
    try:
        print("200 literal expressions (code size):")
        off_ins, off_size = compile_stats(literal, False)
        on_ins, on_size = compile_stats(literal, True)
        report("instructions", off_ins, on_ins)
        report("bytecode", off_size, on_size, "B")
        print()

        print("hot loop, 300,000 iterations of a literal expression:")
        off_time, off_out = runtime(hot, False)
        on_time, on_out = runtime(hot, True)
        report("wall clock", off_time, on_time, "s")
        print("  output identical: %s (%r)" % (off_out == on_out, on_out))
        print()

        print("Not measured: steady-state speed of programs with no literal")
        print("expressions. Folding does nothing for those, by design.")
    finally:
        os.unlink(literal)
        os.unlink(hot)


if __name__ == "__main__":
    main()
