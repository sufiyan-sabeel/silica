# Silica — R1 Benchmark Readiness

**Status:** ready for approval — benchmark defined and executable; M1 blocked only on a Rust toolchain
**Reviewed commit:** `9f6cf886851e4b39e58745ba913cb272bd39409d` (`main`)
**Document version:** 1.0 · 2026-11-03
**Answers:** the seven pre-implementation checks in the M1 approval

This document fixes the gate **before** any Rust exists. Every number below was
measured on the review machine (x86_64, Linux, Python 3.12.13); the command is given
so each can be re-derived, and `benchmarks/gate.py` is the executable form of the
definition.

---

## 0. Verdict

| Check | Result |
|---|---|
| 1. Benchmark computes exactly `1499997500000` | **Verified** — closed form, independent loop, and the VM all agree |
| 2. The 7.17 s figure excludes compilation; startup stated | **Corrected** — the gate number is execution only; startup is excluded and reported separately (§2) |
| 3. Measurement command, runs, warm-up, statistic | **Defined and executable** — `benchmarks/gate.py`, median of 5 after 1 warm-up (§3) |
| 4. stdout byte-identical to the reference | **Pinned** — exact bytes, SHA-256 and exit code (§4) |
| 5. 30-opcode M1 scope runs the benchmark from unmodified `.sbc` | **Verified** — 12 distinct opcodes, all inside M1 (§5) |
| 6. Rust toolchain on the implementation machine | **Not verifiable here** — absent, and not installable in this environment (§6) |
| 7. Platform/toolchain blockers | **Three named** — toolchain, linker, PyO3 headers at M2 (§7) |

**The benchmark is ready. The only blocker to starting M1 is a Rust toolchain on a
machine that can build and link.**

---

## 1. Check 1 — the benchmark computes exactly `1499997500000`

The program sums `i * 3 - 1` for `i` in `[0, 1000000)`:

```silica
sfn main() {
    let total: Int = 0
    let i: Int = 0
    tant i < 1000000 {
        total = total + i * 3 - 1
        i = i + 1
    }
    sprint(total)
}
```

Three independent derivations agree:

| Method | Value |
|---|---|
| Closed form: $$3 \cdot \frac{n(n-1)}{2} - n$$ with $$n = 1000000$$ | `1499997500000` |
| Independent Python loop | `1499997500000` |
| Silica VM output | `1499997500000` |

The value stays far below $$2^{63}$$ (≈1.5 × 10¹²), so this benchmark **does not**
exercise integer overflow — that is covered by the parity corpus (`int_overflow_add`),
not by the gate. The gate measures dispatch throughput, not arithmetic edge cases.

---

## 2. Check 2 — what the 7.17 s figure actually meant

The earlier figure was `median wall time − empty-program startup`, subtracting a
measurement taken on a **different program**. That is close but not exact, so it has
been replaced with a decomposition measured in-process, where the phases can actually
be separated:

| Phase | Cost | How measured |
|---|---|---|
| Compilation (`compile_file`) | **1.0 ms** | in-process, median of 5 after warm-up |
| `.sbc` decode + verify (`load_bytecode`) | **0.37 ms** | in-process, median of 5 |
| **VM execution only** (`run_chunk`) | **7.14–7.28 s** | in-process, median of 5 after 1 warm-up |
| Process start + imports (empty program) | 0.341 s | subprocess, median of 5 |
| Bare CPython floor | 0.061 s | `python3 -c pass` |

**So the gate number is execution only.** It excludes compilation (1 ms), decode and
verify (0.37 ms), process start and imports (0.341 s). Startup is measured and
reported separately; it is not part of the ratio.

Observed range for the execution median across runs: **6.92 s – 7.60 s** (≈±5%),
i.e. **7.14–7.28 s** depending on machine state. That variance is why §3 defines a
statistic and a harness rather than quoting a single number.

### 2.1 A measurement trap worth recording

Sequential benchmark groups drift. In one session, `.sc` runs (compile + run) measured
a 9.185 s median and `.sbc` runs (no compile) 8.454 s — a 0.73 s gap that **cannot** be
compilation, which is 1 ms. The second group simply ran warmer. A ratio computed
across sequential groups would therefore be wrong by up to ~8%, which is more than the
margin between a good and a mediocre Rust implementation.

The protocol in §3 removes this: both VMs are measured **interleaved**, by one harness,
in one process, so drift applies to both.

---

## 3. Check 3 — the exact measurement definition

### 3.1 Command

```
# reference side
python benchmarks/gate.py --sbc build/gate_bench.sbc

# both sides, interleaved, ratio + gate verdict
python benchmarks/gate.py --sbc build/gate_bench.sbc --compare target/release/silica

# machine-readable
python benchmarks/gate.py --sbc build/gate_bench.sbc --json
```

### 3.2 Policy

| Parameter | Value | Why |
|---|---|---|
| Timed region | `VM.run()` / the Rust exec loop only | the dispatch loop is the thing under test |
| Excluded | compile, decode+verify, process start, imports | each is reported separately |
| Warm-up | **1 discarded run** | page cache, allocator, and any lazy initialisation |
| Runs | **5** | enough for a median, cheap enough to repeat |
| Statistic | **median** of the 5 | robust to a single scheduler hiccup; the min is also reported |
| Reported | min, median, max, per-iteration µs, decode ms, stdout hash, exit code | so a reviewer can see the spread, not just a ratio |
| Order | **interleaved** A/B in `--compare` mode | removes the sequential drift in §2.1 |
| Gate | `rust_median ≤ python_median / 3` | the Python median is measured **in the same session** |

**The target is not a hardcoded number.** The harness divides the concurrently
measured Python median by 3 at run time. Against the current reference that is
**≈2.38 s**; it will move with the machine, and that is correct — a fixed second-count
would silently weaken on a slower machine and tighten on a faster one.

### 3.3 What the Rust side must implement

`--bench-json` on the Rust CLI, printing one JSON object per run:

```json
{"decode_ms": 0.4, "exec_ms": 2370.0, "total_ms": 2370.4,
 "stdout": "1499997500000\n", "exit": 0}
```

`exec_ms` must cover the dispatch loop only, so the two sides are comparable. If the
Rust CLI cannot report that split, the comparison is invalid and the gate is not met.

---

## 4. Check 4 — stdout byte-identical to the reference

Pinned from the reference VM, from **both** the source and the `.sbc` (identical):

| | Value |
|---|---|
| stdout | `1499997500000\n` (14 bytes, including the trailing newline) |
| SHA-256 | `2c20dd17e4334e60a656cd03e4c6c8f4c6d1bcdc60dea81268493925fc4a4189` |
| exit code | `0` |
| stability | identical across 5 consecutive runs |

`benchmarks/gate.py` enforces this: it compares the measured stdout against the pinned
bytes, prints `FAIL` and exits 1 on any difference, and reports `stdout_matches_reference`
in its JSON. The Rust VM must produce the same 14 bytes — the newline included, because
a missing newline is exactly the kind of difference that survives casual eyeballing.

---

## 5. Check 5 — the M1 scope runs the benchmark from an unmodified `.sbc`

Compiled with the **Python** compiler, then inspected as bytecode:

| | |
|---|---|
| `.sbc` size | 134 bytes |
| Functions | `main` |
| Constants | `[0, 1000000, 3, 1]` |
| Distinct opcodes | **12** — `ADD CONST JUMP JUMP_IF_FALSE LOAD_LOCAL LT MUL PRINT RET STORE_LOCAL SUB UNIT` |
| Inside the 30-opcode M1 set | **yes** — no opcode falls outside it |
| Output from `.sbc` | `1499997500000\n`, identical to the source run |

So M1 needs 12 of its 30 opcodes to run the gate, and none of the 12 requires
`CALL_NATIVE` — the gate can be measured with **zero Python involvement** in the Rust
process, which is what makes the M1/M2 split meaningful.

---

## 6. Check 6 — the Rust toolchain

**Verified absent in this environment** (`verify_requirements`):

| Tool | Status |
|---|---|
| `cargo` | absent |
| `rustc` | absent |
| `rustup` | absent |
| `gcc` / `cc` | absent |
| `pkg-config` | absent |

**And it cannot be installed here.** `crates.io` and `static.crates.io` are reachable,
but `static.rust-lang.org` and `sh.rustup.rs` are **not allowlisted** by this
environment's network policy, so `rustup` cannot be fetched even without root. A
toolchain in this sandbox is therefore not merely missing but unobtainable.

**This is why the check must run on the actual implementation machine.** Run these and
keep the output; it is the evidence the gate report will cite:

```bash
rustc --version            # record the exact version
cargo --version
rustup target list --installed
cc --version || gcc --version        # the linker for the gnu target
python3 --version
python3 -c "import sysconfig; print(sysconfig.get_paths()['include'])"   # M2 / PyO3
python3 -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))" # M2 / PyO3
```

**Ready** means: `rustc` and `cargo` both answer with a version ≥ 1.70, `cc` or `gcc`
is present, and for M2 the Python include path exists and contains `Python.h`.

---

## 7. Check 7 — platform and toolchain blockers, before any Rust

| # | Blocker | Affects | Status |
|---|---|---|---|
| 1 | No Rust toolchain in this environment, and it cannot be installed here | everything | **blocking** — needs a machine with `rustc`/`cargo` |
| 2 | No C linker (`gcc`/`cc` absent) | the `x86_64-unknown-linux-gnu` target links via `cc` | blocking in this environment; untested elsewhere |
| 3 | PyO3 needs Python headers and a linker | M2 only | not yet verified on any machine |
| 4 | Android/Termux: PyO3 needs a CPython built for the target ABI plus the NDK | M2 and beyond | **do not plan on it** — the "no Python on the device" story fails until a pure-Rust native layer exists |
| 5 | Windows needs the MSVC build tools, not just rustup | M2 packaging | known, not exercised |

What is **not** a blocker: network access to crates.io (allowlisted), `.sbc` decoding
(pure Rust, no dependencies), and the benchmark itself (§1–§5 are all verified).

---

## 8. What changes if no toolchain can be provided

The gate cannot be evaluated without an implementation, and the implementation cannot
exist without a toolchain. If none can be provided, the honest outcomes are:

1. **Defer R1** and keep the frozen parity contract as the deliverable. Nothing here
   decays: the `.sbc` format, the corpus and the gate definition stay valid.
2. **Do not substitute an estimate for a measurement.** The four R1 figures remain
   *not measured* until a run exists.

---

## 9. What this report does not claim

- No Rust performance figure, because no Rust code exists.
- No general Silica speedup, from this benchmark or any other.
- No statement that the ≥3× gate will be met — only what would count as meeting it.
- No claim that the toolchain works anywhere; §6 lists the commands that would
  establish it.
