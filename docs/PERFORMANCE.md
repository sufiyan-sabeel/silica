# Silica Performance — measured, not claimed

Silica's v0.7.0 engine is written in Python (the VM is unchanged since 0.1.0, which is what the numbers below measure). Every Silica instruction costs one
Python-level dispatch step, so the honest headline is: **this implementation is
slower than CPython, by roughly 25×–85× on the workloads below.**

That is expected, and it is measured rather than assumed. The numbers exist to
be a baseline for the Rust port (Milestone E/F), not a marketing claim. Silica
is **not** faster than Python, C, or Rust in v0.7.0, and no such claim is made
anywhere in this repository.

## How to reproduce

```
python3 benchmarks/bench.py --runs 3
```

`benchmarks/bench.py` runs each Silica program in `benchmarks/silica/` and a
Python function performing the same work with the same algorithm, takes the best
of N runs, checks that both produce the expected result, and prints a ratio
(`silica time / python time`; above 1.00× means Silica is slower).

## One real run

Recorded on the development sandbox used to build this release:

| | |
|---|---|
| Host | Linux, x86_64 |
| Python | CPython 3.12.13 |
| Silica | 0.1.0, bytecode VM (Python reference engine) |
| Runs | best of 2 |

| Workload | Silica | CPython | Ratio |
|---|---|---|---|
| arithmetic loop, 1e6 iterations | 14628.7 ms | 270.1 ms | 54.2× slower |
| recursion, `fib(24)` (≈150k calls) | 1861.2 ms | 22.1 ms | 84.4× slower |
| collections: 200k `push` + iterate + sort | 2977.9 ms | 118.4 ms | 25.2× slower |
| strings: 20k-element `join` + `split` | 215.0 ms | 3.3 ms | 66.1× slower |

Absolute times vary with the machine; the ratio is the useful figure. Re-run the
script on your own hardware before quoting a number.

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
