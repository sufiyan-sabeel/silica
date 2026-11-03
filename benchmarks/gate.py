"""The R1 dispatch gate: the one measurement that decides whether R1 continues.

`docs/design/SILICA_R1_BENCHMARK_READINESS.md` defines the gate. This script is the
definition, so that the Python VM and the future Rust VM are measured by the same
harness, in the same order, with the same statistic — the only way a ratio between
two implementations means anything.

What is measured
----------------
**Execution only**: `VM.run()` on an already-decoded chunk. Excluded from the timed
region: process start, imports, `.sbc` decode and verify, and compilation. Those are
reported separately, because they are real costs but they are not the dispatch loop.

The gate statistic
------------------
The **median** of `--runs` timed runs (default 5), after `--warmup` discarded runs
(default 1). The gate is `rust_median <= python_median / 3`.

Usage
-----
    # the reference side
    python benchmarks/gate.py --sbc build/gate_bench.sbc

    # both sides, interleaved (the protocol that removes drift)
    python benchmarks/gate.py --sbc build/gate_bench.sbc \
        --compare target/release/silica

    # machine-readable
    python benchmarks/gate.py --sbc build/gate_bench.sbc --json

Exit status is 0 when the measured output matches the pinned bytes, 1 otherwise. A
ratio is reported but only `--compare` enforces the gate, because the gate is about
two implementations, not one.
"""

import argparse
import hashlib
import io
import json
import os
import statistics
import subprocess
import sys
import time

# Pinned by the reference VM. The Rust VM must produce these exact bytes.
EXPECTED_STDOUT = "1499997500000\n"
EXPECTED_SHA256 = "2c20dd17e4334e60a656cd03e4c6c8f4c6d1bcdc60dea81268493925fc4a4189"
GATE_FACTOR = 3.0


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def measure_python(sbc, runs, warmup):
    """Timed execution of a decoded chunk on the Python VM."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from silica.engine import load_bytecode, run_chunk

    started = time.perf_counter()
    chunk = load_bytecode(sbc)
    decode_s = time.perf_counter() - started

    def once():
        out = io.StringIO()
        begin = time.perf_counter()
        code = run_chunk(chunk, sbc, stdin=io.StringIO(), stdout=out,
                         stderr=io.StringIO())
        return time.perf_counter() - begin, out.getvalue(), code

    for _ in range(warmup):
        once()

    times, outputs, codes = [], [], []
    for _ in range(runs):
        elapsed, out, code = once()
        times.append(elapsed)
        outputs.append(out)
        codes.append(code)

    return {
        "vm": "python",
        "decode_s": decode_s,
        "times": times,
        "stdout": outputs[0],
        "stdout_stable": len(set(outputs)) == 1,
        "exit": codes[0],
        "exit_stable": len(set(codes)) == 1,
    }


def measure_rust(sbc, runs, warmup, binary):
    """Timed execution reported by the Rust CLI itself.

    The CLI must implement `--bench-json`, printing decode/exec/total milliseconds
    for a single run, so both sides report the same decomposition. Process start is
    the caller's cost, not the loop's, and is measured separately.
    """
    def once():
        proc = subprocess.run([binary, "--vm=rust", "--bench-json", sbc],
                              capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise SystemExit("rust run failed (%d): %s"
                             % (proc.returncode, proc.stderr[-400:]))
        return json.loads(proc.stdout)

    for _ in range(warmup):
        once()

    samples = [once() for _ in range(runs)]
    return {
        "vm": "rust",
        "decode_s": statistics.median(s["decode_ms"] for s in samples) / 1000.0,
        "times": [s["exec_ms"] / 1000.0 for s in samples],
        "stdout": samples[0].get("stdout", ""),
        "stdout_stable": len({s.get("stdout") for s in samples}) == 1,
        "exit": samples[0].get("exit", 0),
        "exit_stable": len({s.get("exit") for s in samples}) == 1,
    }


def summarise(result, iterations):
    times = result["times"]
    median = statistics.median(times)
    return {
        "vm": result["vm"],
        "runs": len(times),
        "min_s": round(min(times), 4),
        "median_s": round(median, 4),
        "max_s": round(max(times), 4),
        "per_iteration_us": round(median / iterations * 1e6, 3),
        "decode_ms": round(result["decode_s"] * 1000, 3),
        "stdout": result["stdout"],
        "stdout_sha256": _sha(result["stdout"]),
        "stdout_matches_reference": result["stdout"] == EXPECTED_STDOUT,
        "stdout_stable": result["stdout_stable"],
        "exit": result["exit"],
        "exit_stable": result["exit_stable"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sbc", required=True, help="the compiled gate benchmark")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=1000000,
                        help="loop iterations in the benchmark, for per-iteration cost")
    parser.add_argument("--compare", metavar="RUST_BIN",
                        help="also measure a Rust CLI and report the ratio")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.exists(args.sbc):
        raise SystemExit("no such .sbc: %s" % args.sbc)

    if args.compare:
        # Interleaved: alternating groups, so slow drift on the machine affects both
        # sides equally. Sequential groups were measured to differ by ~8% for no
        # reason attributable to the code.
        python_runs, rust_runs = [], []
        for _ in range(args.warmup):
            measure_python(args.sbc, 1, 0)
            measure_rust(args.sbc, 1, 0, args.compare)
        for _ in range(args.runs):
            python_runs.append(measure_python(args.sbc, 1, 0)["times"][0])
            rust_runs.append(measure_rust(args.sbc, 1, 0, args.compare)["times"][0])
        python_median = statistics.median(python_runs)
        rust_median = statistics.median(rust_runs)
        ratio = python_median / rust_median
        report = {
            "gate_factor": GATE_FACTOR,
            "python_median_s": round(python_median, 4),
            "rust_median_s": round(rust_median, 4),
            "ratio": round(ratio, 2),
            "passes_gate": ratio >= GATE_FACTOR,
            "rust_target_s": round(python_median / GATE_FACTOR, 4),
        }
    else:
        report = summarise(measure_python(args.sbc, args.runs, args.warmup),
                           args.iterations)
        report["gate_factor"] = GATE_FACTOR
        report["rust_target_s"] = round(report["median_s"] / GATE_FACTOR, 4)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            print("%-26s %s" % (key, value))

    ok = report.get("stdout_matches_reference", True)
    if not ok:
        print("FAIL: stdout does not match the pinned reference bytes", file=sys.stderr)
        print("expected %r (sha256 %s)" % (EXPECTED_STDOUT, EXPECTED_SHA256),
              file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
