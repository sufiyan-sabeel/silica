# Silica Performance — measured, not claimed

Silica's engine is written in Python (the VM is unchanged since 0.1.0, which is
what the numbers below measure). Every Silica instruction costs one
Python-level dispatch step, so the honest headline is: **this implementation is
slower than CPython, by roughly 47×–111× on the workloads below**, measured on
2026-10-28 with Silica 0.9.3.

That is expected, and it is measured rather than assumed. The numbers exist to
be a baseline for the Rust port (Milestone E/F), not a marketing claim. Silica
is **not** faster than Python, C, or Rust in v0.8.0, and no such claim is made
anywhere in this repository.

## How to reproduce

```
python3 benchmarks/bench.py --runs 3
```

`benchmarks/bench.py` runs each Silica program in `benchmarks/silica/` and a
Python function performing the same work with the same algorithm, takes the best
of N runs, checks that both produce the expected result, and prints a ratio
(`silica time / python time`; above 1.00× means Silica is slower).

## The current run

Recorded on 2026-10-28 with `python3 benchmarks/bench.py --runs 3`:

| | |
|---|---|
| Host | Linux, x86_64 |
| Python | CPython 3.12.13 |
| Silica | 0.9.3, bytecode VM (Python reference engine) |
| Runs | best of 3 |

| Workload | Silica | CPython | Ratio |
|---|---|---|---|
| arithmetic loop, 1e6 iterations | 15155.8 ms | 323.4 ms | 46.9× slower |
| recursion, `fib(24)` (≈150k calls) | 1945.0 ms | 17.5 ms | 111.1× slower |
| collections: 200k `push` + iterate + sort | 3098.0 ms | 56.6 ms | 54.8× slower |
| strings: 20k-element `join` + `split` | 183.1 ms | 3.7 ms | 49.5× slower |

Absolute times vary with the machine; the ratio is the useful figure. Re-run the
script on your own hardware before quoting a number.

### Historical runs — superseded, do not quote

Earlier tables in this file recorded 25×–85× and then 41×–93× on the same four
workloads, with Silica 0.1.0/0.8.0 and different CPython builds. They are kept
only to show the trend; every one of them has been replaced by the table above,
and none of them should be quoted as the current figure.

## 0.10.0: the arithmetic fast path, measured

The first optimization in this cycle came from profiling, not guessing. A
`cProfile` run of `benchmarks/silica/arith_loop.sc` showed the cost concentrated
in the dispatch loop's arithmetic: 26 million `isinstance` calls, 13 million list
`pop`/`append` pairs, and two million calls each into `_add`, `_numeric` and
`i64` for a one-million-iteration loop.

What changed, in `silica/vm.py` only:

- **ADD, SUB and MUL test `type(x) is int` first.** That is the fastest check
  Python offers, and it excludes `Bool` exactly as `isinstance` did — so Bool
  still reaches the same type error.
- **The 64-bit range test replaces `i64()` on the common path.** An overflowing
  add still wraps (`9223372036854775807 + 1` is `-9223372036854775808`), it just
  no longer pays for the wrap when it does not happen.
- **`<`, `<=`, `>` and `>=` compare two Ints directly.**
- **The per-call lambdas for subtract and multiply became module-level
  functions**, removing a function object creation from the hot path.

Nothing else changed: same opcodes, same bytecode format, same errors, same
`i64` wrapping at the boundary.

### Before and after

Same machine, same command (`python3 benchmarks/bench.py --runs 3`), best of
three runs, Linux x86_64 / CPython 3.12.13:

| workload | before | after | change |
|---|---|---|---|
| arithmetic loop (1e6 iterations) | 11705.7 ms | **7966.0 ms** | **−32%** |
| recursion (fib 24) | 1500.5 ms | **1163.9 ms** | **−22%** |
| collections (200k push + iterate + sort) | 2635.3 ms | **2121.8 ms** | **−19%** |
| strings (20k join + split) | 152.1 ms | 141.0 ms | −7% |

Every workload's `check` column still reads `ok`, which means Silica and CPython
produce the same result — the speed did not come from computing less.

### What this does not claim

Silica is still 31× slower than CPython on the arithmetic loop and 72× on
recursion. The ratio improved; the ordering did not. The remaining cost is the
interpreter loop itself (one Python-level `if/elif` dispatch per instruction), and
that is what the plan below addresses — a dispatch table, then a Rust engine.

Regressions were checked the same way: the full suite (1170 tests) and the
Silica-level suite pass unchanged, and `test_bool_arithmetic_is_still_refused`
pins the one semantic the fast path could have broken.

## What the numbers mean

* **Call-heavy code suffers most** (recursion, 84×). Each Silica call pushes a
  frame object and each instruction re-enters the interpreter loop.
* **Native-heavy code suffers least** (collections sort, 25×). Work done inside
  a native is plain Python work, so only the loop overhead is Silica's.
* **Instruction dispatch dominates** (arith loop, 54×). The loop executes
  roughly 8 Silica instructions per iteration; each one is an `if/elif` step in
  Python.

## What is already in place

* Compilation to bytecode: source is parsed and type-checked once, never
  re-interpreted per statement.
* Locals live in a per-frame list indexed by a compiled slot number; globals in a
  flat slot array.
* Bytecode is decoded once per function and cached, then executed from a tuple
  list with the instruction pointer and stack hoisted into interpreter locals.
* Constant pooling deduplicates literals across the whole program.
* `sprint(x)` / `dit(x)` as statements compile to a single `PRINT`/`DIT` opcode.
* Short-circuit `und`/`ou` compile to jumps, so the right side really is skipped.

## Optimization plan, in order of expected payoff

1. **Dispatch table instead of an `if/elif` chain** — index a list of handlers by
   opcode. Low risk, mechanical, likely a large win in a Python-hosted VM.
2. **Superinstructions** — fuse common sequences (`LOAD_LOCAL`, `CONST`,
   `ADD`, `STORE_LOCAL`; `LOAD_LOCAL`, `CONST`, `LT`, `JUMP_IF_FALSE`) during a
   peephole pass after codegen. Cuts both dispatch count and stack traffic.
3. **Inline caching for globals and natives** — resolve `CALL_NATIVE` module/name
   pairs to a direct callable at load time instead of a dictionary lookup per
   call.
4. **Register-style locals** — avoid pushing/popping for locals entirely by
   giving binary ops a "local operand" form.
5. **Port the engine to Rust** — the intended destination. The `.sbc` format is
   already implementation-neutral and verified, so a Rust VM can consume the same
   files and be compared against this engine byte-for-byte on the test suite.
6. **Native code backend** (later) — an LLVM or Cranelift backend for numeric
   kernels, keeping the bytecode VM as the portable baseline.

None of these change the language or the bytecode semantics, so every existing
program and every existing test keeps working. Until step 5 lands and is
measured, this document's claim stands: the reference engine is slower than
CPython.
