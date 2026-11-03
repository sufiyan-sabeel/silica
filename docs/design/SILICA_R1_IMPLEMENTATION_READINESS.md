# Silica — R1 Rust VM Implementation-Readiness Review

**Status:** decisions recorded — Decision A (NOP) implemented; Decision B (bounded
M1+M2 spike) approved; no Rust code written
**Reviewed commit:** `84e6d1ca9acedb669fc0057c4d73a89cd572c574` (`main`, after PR #8)
**Document version:** 1.1 · 2026-11-03
**Scope:** whether Silica should begin R1 of the optional Rust VM, and in what shape

Every number below was produced by running something against the checked-out tree;
the command is given so it can be re-derived. Where the architecture document made a
claim, the claim was checked against the source, and the two places they disagree
are named in §2.9.

---

## 1. Executive summary

**Recommendation: conditional GO for a narrowed R1 — and NO-GO for the nine-crate
structure at R1.**

The VM is small enough to reimplement and the contract is now executable, which is
what makes R1 feasible at all. But three things must happen before any Rust code is
written, and one of them is a defect in the reference VM:

1. **Resolve `NOP`.** It is in the opcode table, has a stack effect, and passes the
   verifier — but the VM raises `unknown opcode 0x00` if it ever executes. A Rust VM
   that implements all 43 opcodes would therefore *diverge from the reference on the
   first instruction of this kind*. Either implement it in Python (one line) or
   delete it from the table. §2.9.
2. **Provide a Rust toolchain.** None exists in the review environment (`cargo`,
   `rustc` and `gcc` are all absent), so nothing in this document is a build result.
3. **Fund a time-boxed spike, not a VM.** R1 should prove two things and stop:
   that Rust can decode and verify `.sbc` with the same accept/reject decisions, and
   that a dispatch loop over a measured opcode subset produces byte-identical output.

**The strongest argument for R1** is not speed, it is portability: the reference VM
needs CPython, and every non-Python target in the platform plan eventually needs an
execution engine that does not. **The strongest argument against** is that R1 keeps
the natives in Python through PyO3 — so R1 does *not* deliver a Python-free runtime,
only a Python-free dispatch loop. That is a real limitation of the phase and it is
stated in §8 rather than hidden.

**Effort, assuming one engineer familiar with the codebase:** 12–18 engineer-days to
the end of M2 (the gate that matters), 25–35 to all 42 opcodes with the bridge. §11
gives the breakdown and the assumptions behind it.

---

## 2. Current architecture audit

### 2.1 The engine, measured

```
$ wc -l silica/vm.py silica/bytecode.py silica/natives.py silica/capabilities.py silica/compiler.py
   617 silica/vm.py
   757 silica/bytecode.py
   685 silica/natives.py
   591 silica/capabilities.py
   693 silica/compiler.py
```

The dispatch loop is a hand-written `if op == 0x01: … elif …` chain over **numeric
opcode literals**, not a table of handler functions and not a `match`. Frame state is
hoisted into locals (`ip`, `stack`, `locals_`) and written back on `CALL`/`RET`, which
is the usual Python optimisation and tells a Rust implementer exactly where the hot
state is. Frames are explicit (`frames` list), so recursion depth is bounded by
`max_frames` (4096) rather than by the host stack.

### 2.2 Opcodes: 43 in the table, 42 implemented

```
$ python3 -c "from silica.bytecode import OPS; print(len(OPS))"     # 43
```

Cross-checking every `op == 0xNN:  # NAME` handler in `vm.py` against the table:

| | Count |
|---|---|
| Opcodes in the table | 43 |
| Opcodes with a handler in `vm.py` | 42 |
| Missing | **`NOP` (0x00)** |

Every handler's numeric literal agrees with the table's numeric value (checked
programmatically: zero mismatches). Stack effects live in `bytecode.STACK_EFFECT`
and are enforced by the verifier, which runs on every compiled program — so the table
is exercised by the whole suite, not just by inspection.

### 2.3 `.sbc` format 1.0

```
$ python3 -c "import silica.bytecode as b; print(b.MAGIC, b.FORMAT_MAJOR, b.FORMAT_MINOR, b.HEADER_SIZE)"
b'SILICABC' 1 0 17
```

Header is 17 bytes: 8-byte magic, `u16` major, `u16` minor, 1 flag byte, `u32` CRC-32
over the payload. Then varint-prefixed tables: constants (tagged Int/Float/String/
Bool), globals (name + type tag), functions (name, arity, locals, max stack, return
type, code bytes, line table), init and entry indices. Limits, all enforced on load:

| Limit | Value |
|---|---|
| `MAX_CONSTANTS` | 65,536 |
| `MAX_FUNCTIONS` | 4,096 |
| `MAX_LOCALS` | 4,096 |
| `MAX_STACK` | 4,096 |
| `MAX_CODE_BYTES` | 1,048,576 |

The verifier is not a formality: it decodes every instruction, checks operand ranges
(constant index, local slot, global index, call target and arity, native existence
and arity), checks jump targets land on instruction boundaries, and runs an abstract
stack-depth analysis over the control-flow graph, rejecting underflow, inconsistent
depths and functions that fall off the end. **A Rust port must reproduce its accept
and reject decisions, not merely its acceptances** — that is the first R1 gate.

### 2.4 Native registry

```
$ python3 -c "from silica.natives import MODULES; print(len(MODULES), sum(len(m) for m in MODULES.values()))"
29 316
```

A `Native` carries `module, name, params, ret, fn, min_args, max_args, requires,
path_arg, accepts_block`. Capability demand is per-native and declared:

| `requires` | Natives |
|---|---|
| none (pure) | **281** |
| `speech.models` | 8 |
| `speech.listen` | 6 |
| `interop.python` | 6 |
| `gui.run` | 4 |
| `speech.speak` | 4 |
| `tui.run` | 3 |
| `fs.read` | 2 |
| `fs.write` | 1 |
| `fs.list` | 1 |

Two natives declare `path_arg` (the containment-validated ones); 22 accept a block.
**88.9% of the native surface is capability-free**, which is why a bridge that only
forwards `CALL_NATIVE` is tractable in R1.

### 2.5 Capability enforcement — one choke point, verified

`vm.py`, `CALL_NATIVE` (opcode 0x1A):

```python
if native.requires is not None:
    args = self.capabilities.authorize_call(native, args)
result = native.fn(ctx, args)
```

`authorize_call` checks the grant and then **returns a rewritten argument list with
the path replaced by the resolved one that was authorised**, so the native never
re-resolves a path and cannot be tricked into a second resolution. This is the single
place a capability is consulted on the execution path; the comment in the source says
so and the code matches. A Rust port must keep exactly this shape: one function, on
the dispatch path, returning the authorised arguments.

### 2.6 Value representation and ownership

Values are ordinary Python objects — `bool`, `int`, `float`, `str`, `list`, `dict` —
plus two runtime-only classes:

- `StructValue` with `type_name`, `fields`, `frozen`, `is_struct`. Deliberately not a
  dict, because `Point(x: 1, y: 2)` must not equal `{"x": 1, "y": 2}`.
- `Iterator` with `items`, `index`, used only by `per`. Not user-visible.

There is no VM object graph, no handle table and no GC of its own: ownership is
CPython's reference counting, and a struct held in a `const` is marked `frozen`
rather than copied. This is the part of the design with the largest Rust-side
implication: the reference VM gets identity, cycles and lifetime for free, and the
Rust VM must supply them (arena + mark-sweep, per §13.10 of the architecture
document).

### 2.7 Parity contract, and the float fix

`tests/parity/` holds 14 cases (9 stdout, 5 diagnostics) plus a runner that compares
**stdout, stderr including `hint:` lines, and exit codes** through a subprocess, with
five self-tests proving each comparison fires. The corrected float constant interning
is on `main` (PR #7, merge `da61801`): `constant_key` keys floats on
`struct.pack(">d", value)`, and the pool now carries both zeros (index 0 `-0.0`,
index 1 `0.0`). There are **no remaining xfail cases** — the corpus is fully enforced.

### 2.8 Test baseline

```
$ python3 -m unittest discover -s tests -t .
...................................................................
----------------------------------------------------------------------
Ran 1329 tests in 153.636s

OK (skipped=7)
```

Environment: Python 3.12.13, `pytest` 9.2.0, `build`/`setuptools`/`wheel`, git working
tree. 1,322 pass, 7 skipped, 0 failures, 0 expected failures. The count rose from 1,318
because `NOP` now has 11 regression tests (§2.9).

### 2.9 Where the document and the source disagree

**`NOP` was unimplemented — now fixed.** The architecture document says "43 opcodes";
the table had 43 and the VM executed 42. Reproduced directly at review time:

```
verifier accepts NOP: yes
VM rejects NOP: SilicaRuntimeError unknown opcode 0x00
```

The compiler never emits `NOP`, so no source program could reach it — but `.sbc` is a
documented, versioned artefact, and a third-party or hand-built chunk containing `NOP`
verified cleanly and then failed at run time.

**Decision A: implement it, keep 43.** Landed as PR #8, merge commit
`84e6d1ca9acedb669fc0057c4d73a89cd572c574`. The dispatch chain gained one branch at its
head:

```python
if op == 0x00:  # NOP
    pass
elif op == 0x01:  # CONST
```

The instruction pointer has already advanced before dispatch, so `NOP` advances
execution and changes nothing else. `tests/test_nop.py` holds **11 regression tests**,
assembling bytecode **by hand** because the compiler cannot produce it: contract values
(`OPS["NOP"] == 0x00`, stack effect `(0, 0)`), verifier acceptance in every position,
unchanged abstract stack depth, a jump targeting a `NOP` boundary, the runtime actually
executing it, the operand stack untouched, the instruction pointer advancing (eight
`NOP`s = eight bytes at offsets 0–7), semantic invisibility under a differential test,
and a **hand-written `.sbc` file** that serialises, loads through `load_bytecode` and
runs. The container format is unchanged (magic `SILICABC`, format 1.0, 17-byte header).

**`sprint` has two paths.** `core.sprint` exists as a native, but the statement form
compiles to the `PRINT` opcode:

```
$ silica compile of: sprint(len(xs))
CONST CONST CONST MAKE_LIST STORE_LOCAL LOAD_LOCAL CALL_NATIVE PRINT …
native calls: [('core','len')]
```

So printing does **not** require the bridge, while `len`, `str`, `range`, `push`,
`math.*` do. This matters for the MVP scope in §5: a Rust VM can produce correct
output with zero natives, which is a smaller first gate than it looked.

### 2.10 What real programs actually execute

Compiled every `examples/*.sc` and `tests/silica/*.sc` and counted instructions:

```
programs: 33 | instructions: 3,888 | distinct opcodes: 39 of 43
```

| Opcode | Share | Cumulative |
|---|---|---|
| `CONST` | 23.0% | 23.0% |
| `LOAD_LOCAL` | 16.6% | 39.6% |
| `CALL_NATIVE` | 12.9% | 52.5% |
| `STORE_LOCAL` | 6.2% | 58.8% |
| `POP` | 5.5% | 64.3% |
| `PRINT` | 4.2% | 68.5% |
| `RET` | 4.0% | 72.6% |
| `JUMP_IF_FALSE` | 3.5% | 76.1% |
| `ADD` | 3.5% | 79.5% |
| `EQ` | 3.4% | 83.0% |
| `JUMP` | 2.2% | 85.1% |
| `UNIT` | 1.9% | 87.0% |

Twelve opcodes cover **87%** of executed instructions; twenty cover **96%**. Never
used by the corpus at all: `FREEZE`, `LEN`, `NEG`, `NOP` — four opcodes whose only
coverage is hand-written tests, which is precisely where a second implementation
drifts.

### 2.11 Cost structure, measured

| Measurement | Value | Command |
|---|---|---|
| Empty program, end to end | **0.285 s** | `python3 -m silica run empty.sc` |
| Same, from `.sbc` (no compile) | 0.289 s | `python3 -m silica run empty.sbc` |
| Bare CPython floor | 0.046 s | `python3 -c pass` |
| Loop iteration (no native) | 7.56 µs | 200k iterations |
| **Native call** | **2.35 µs** | 200k iterations ±`math.sqrt` |
| Versus CPython on four workloads | 46.9×–111.1× slower | `docs/PERFORMANCE.md` |

Two things follow. **Startup is imports, not compilation** — running a precompiled
`.sbc` measured 0.289 s against 0.285 s for compile-then-run, so the compiler's share
is below the noise floor (a few milliseconds) and ~240 ms of the 285 ms is CPython
plus imports over the 0.046 s bare-interpreter floor. A Rust VM's startup advantage
will come from not importing CPython, not from a faster parser. And the **native call is a quarter of the loop
iteration cost** (2.35 µs of 9.91 µs), so a Rust dispatch loop that still calls Python
for `len`/`str` will be capped by the bridge on any native-heavy program. That is the
central measurement risk of R1 and §7 designs the benchmarks to expose it separately.

---

## 3. Nine crates versus one crate versus a hybrid

Three structures were evaluated against eight criteria.

| Criterion | A. Nine crates | B. One crate | C. Hybrid (3 crates) |
|---|---|---|---|
| Build complexity | 9 manifests, 9 dependency edges, workspace config | 1 manifest | 3 manifests, one workspace |
| Dependency management | clean per-crate semver, but premature | single version, everything moves together | two stable interfaces (`vm` → `native`) |
| Compilation time | parallel, but 9 unit boundaries; clean builds dominated by PyO3 either way | worst incremental (any edit rebuilds all) | near-B, small win from isolating PyO3 |
| Testing | unit tests per crate, integration needs all | simple | unit tests in `silica-vm` with no CPython present — **a real advantage** |
| Maintainability | high ceremony for a project with one consumer | lowest ceremony, highest coupling | low ceremony, clear seams |
| Extensibility | best in theory | refactor needed later | `caps` can be split out when a second host exists |
| Performance impact | none (LTO flattens it) | none | none |
| Risk of unnecessary abstraction | **high** — boundaries chosen before evidence | low | low |

**Recommendation: C.** Three crates, because the seams that are certainly real are
only two — *the pure VM* and *the host boundary where unsafe and FFI live* — and
everything else in the nine-crate proposal is a guess about where the code will want
to divide. Nine crates would also make the most important property of this port
harder to enforce: `silica-vm` can be `#![forbid(unsafe_code)]` and tested with no
CPython in the process, which is only true if the bridge is in a different crate.

`silica-caps` is deliberately *not* separate at R1: it is ~600 lines of Python today
and one host consumes it. Extract it when a second host (JNI, C ABI) exists, which is
a later phase by definition.

---

## 4. Recommended architecture

```
silica-rust/
  Cargo.toml                 # workspace
  crates/
    silica-vm/               # pure: no unsafe, no I/O, no CPython
      src/value.rs           # Value, StructValue, Iterator, formatting (§16.3 parity)
      src/bytecode.rs        # decode + verifier (port of verify_function)
      src/heap.rs            # arenas, cells, mark-sweep, root registration
      src/frames.rs          # operand stack, call frames, max_frames
      src/exec.rs            # the dispatch loop, one function per opcode
    silica-native/           # the only crate that may use unsafe / PyO3
      src/registry.rs        # native metadata mirroring `Native`
      src/caps.rs            # CapabilitySet + path containment (port of authorize_call)
      src/bridge.rs          # PyO3 calls into the existing Python natives
    silica-cli/              # thin binary: args, .sbc loading, wiring, exit codes
```

Rules that make the recommendation enforceable rather than aspirational:

- `silica-vm` is `#![forbid(unsafe_code)]` and has **no** dependency on PyO3, so its
  test suite runs anywhere.
- `silica-native` is the only crate allowed `unsafe`, and it exposes exactly one
  entry point: `invoke(caps, module, name, args)`.
- `silica-cli` owns process concerns (argv, exit codes, stderr), never semantics.

---

## 5. Minimum viable R1 scope

Three gates. Each proves something specific and each is independently reviewable.

| Gate | Opcodes | Natives | What it proves | Corpus it must pass |
|---|---|---|---|---|
| **M1 — decode and dispatch** | **30**: `NOP CONST UNIT TRUE FALSE LOAD_LOCAL STORE_LOCAL LOAD_GLOBAL STORE_GLOBAL POP ADD SUB MUL DIV MOD NEG EQ NE LT LE GT GE JUMP JUMP_IF_FALSE CALL RET PRINT DIT HALT_OK HALT_POP` | **none** | bytecode decoding, frames, arithmetic, branching, printing — the whole loop, with no FFI | a hand-built subset corpus: arithmetic, loops, recursion, printing, error cases |
| **M2 — data and the bridge** | + `MAKE_LIST MAKE_MAP INDEX_GET LEN ITER_START ITER_NEXT CALL_NATIVE` | forwarded to Python via PyO3 | collections, iteration, and the native ABI + capability choke point | **the full parity corpus (14 cases)** plus every `examples/*.sc` that needs no capability |
| **M3 — full surface** | all 42 (or 43, per the `NOP` decision) | all | records, methods, `FREEZE`, the long tail | the full differential suite over `tests/silica/` and `examples/` |

M1 deliberately excludes `CALL_NATIVE`, which is 12.9% of real instructions but 100%
of the FFI risk. It answers "can Rust run the loop?" without touching PyO3 at all.
Those 30 opcodes cover ≈81% of the instructions in the corpus; what they exclude is
`CALL_NATIVE` (12.9%), the collection opcodes (4.7%) and the record opcodes (0.9%).

**The M1 benchmark program, verified against the opcode set.** Compiled with the
Python compiler, it uses **12** distinct opcodes — `ADD CONST JUMP JUMP_IF_FALSE
LOAD_LOCAL LT MUL PRINT RET STORE_LOCAL SUB UNIT` — all inside M1, in 25 instructions:

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

It prints `1499997500000`, verified three ways: closed form `3·(n(n−1)/2) − n`,
an independent Python loop, and the VM itself. On the reference VM it takes
**7.14–7.28 s** of execution only, in-process, median of 5 after one warm-up — about
7.2 µs per iteration. Compilation is 1.0 ms and decode+verify 0.37 ms, both excluded
from the gate; process startup (0.341 s) is reported separately. See
`docs/design/SILICA_R1_BENCHMARK_READINESS.md`.
M2 is the gate that matters commercially, because it is where the bridge cost appears.

**Explicitly out of scope for R1:** closures (they do not exist in the language yet),
`async`, WASM, the front end, `fs` migration, any change to `.sbc`, any change to
default behaviour. R1 ships behind `--vm=rust`.

---

## 6. Opcode implementation sequence

Ordered by measured corpus frequency, not by opcode number, so that each step
increases the set of runnable programs as fast as possible.

| Step | Opcodes added | Cumulative instruction coverage | Runnable at this point |
|---|---|---|---|
| 0 | `NOP` decision first (§2.9) | — | contract fixed before code |
| 1 | `CONST LOAD_LOCAL STORE_LOCAL RET UNIT PRINT` | 55% | `sprint` of a literal |
| 2 | `ADD SUB MUL DIV MOD NEG` + `EQ NE LT LE GT GE` | 64% | arithmetic and comparisons |
| 3 | `JUMP JUMP_IF_FALSE` + `TRUE FALSE` | 71% | `si`/`sino`, `tant`, `per` over ranges |
| 4 | `CALL POP` + `HALT_OK HALT_POP` | 76% | functions, recursion, exit codes → **M1** |
| 5 | `MAKE_LIST MAKE_MAP INDEX_GET ITER_START ITER_NEXT` | 81% | lists, maps, iteration |
| 6 | `CALL_NATIVE` (+ bridge) | 94% | `len`, `str`, `range`, `math.*` → **M2** |
| 7 | `MAKE_STRUCT GET_FIELD SET_FIELD FREEZE CALL_METHOD` | 99.9% | records and methods |
| 8 | `LOAD_GLOBAL STORE_GLOBAL LEN DIT` | 100% | globals, `dit`, `len` as an opcode |

The last three opcodes in the corpus frequency table (`SET_FIELD` 1, `LE` 1,
`STORE_GLOBAL` 3) are the ones whose absence hides longest, which is why step 8 is a
gate and not an afterthought.

---

## 7. Benchmark methodology

**Four comparisons**, reported separately, because collapsing them hides the only
result that matters:

| # | Comparison | What it isolates |
|---|---|---|
| 1 | Python VM | the baseline |
| 2 | Rust VM, no native calls (M1 programs) | dispatch-loop speed |
| 3 | Rust VM with Python natives (M2 programs) | bridge cost, and whether it eats the gain |
| 4 | Equivalent CPython | whether either Silica VM is competitive with the host language |

**Workloads** — reuse the existing `benchmarks/bench.py` set so results are comparable
with `docs/PERFORMANCE.md`: arithmetic loop (1e6 iterations), recursion `fib(24)`,
collections (200k `push` + iterate + sort), strings (20k `join` + `split`). Add one
native-heavy workload (200k `math.sqrt` calls) purely to measure the bridge.

**Procedure:**

- **Warm-up:** discard the first run entirely; CPython's import and page-cache state
  dominate a cold start, and the reference numbers were taken warm.
- **Iterations:** 3 runs per workload per VM, report the **median** and the min; the
  spread is the noise floor and must be published alongside the ratio.
- **Startup separated:** time (a) process start to first instruction, (b) execution
  only, (c) total. The reference VM's 0.285 s empty-program time is mostly imports
  (§2.11), so a single "wall time" number would be misleading in both directions.
- **Memory:** peak RSS via `resource.getrusage` on Linux for the same workloads; for
  the Rust VM also report allocation count and GC pauses under `SILICA_GC_STRESS=1`
  (correctness) versus normal thresholds (performance).
- **Statistics:** median of 3, min, max, and the ratio `python / rust`; state the
  machine (CPU, RAM, OS, Python and Rust versions). No p-values — these are not
  samples from a distribution.
- **Pre-registered acceptance thresholds.** Fixed here, before any Rust code exists,
  so they cannot be fitted to whatever the spike produces:
  - **Primary gate:** ≥**3× faster dispatch** on the M1 arithmetic benchmark,
    measured as **execution only** — excluding compile (1.0 ms), decode+verify
    (0.37 ms), process start and imports (0.341 s). Reference: **7.14–7.28 s** median
    in-process. The target is derived at run time as `python_median / 3` (≈2.38 s),
    not hardcoded, so a slower machine does not silently weaken the gate. The exact
    command, run count, warm-up and statistic are frozen in
    `docs/design/SILICA_R1_BENCHMARK_READINESS.md`, and `benchmarks/gate.py` is the
    executable form: both VMs are measured by it, interleaved, in one session.
  - **No generalisation.** That single result may not be reported as "Silica is 3×
    faster". Representative workloads (recursion, collections, strings) are reported
    alongside it, and a speedup claim is scoped to the workload it was measured on.
  - **M2 gate:** the native-heavy workload must be **no slower** than the Python VM,
    else the bridge dominates and the recommendation becomes "stop at M1, keep the
    Rust VM optional".
  - The **2.35 µs** native-call figure is a *reference*, not a target: a PyO3 call is
    expected to cost more, and the report must state by how much rather than rounding
    it away.

**No numbers are predicted here.** §2.11 gives the reference measurements; §16.14.3 of
the architecture document keeps the four R1 figures marked *not measured* until a
Rust run exists.

---

## 8. Platform and packaging

**Toolchain reality, not aspiration.** Verified absent in this environment:
`cargo`, `rustc`, `gcc`. So none of the following is a build result.

| Target | Toolchain | abi3 wheel | Notes |
|---|---|---|---|
| Linux x86_64 | rustup, mature | yes | the natural first target; CI runners have it |
| Linux ARM64 | rustup, mature | yes | needed for ARM servers and some CI |
| Android ARM64 / Termux | `rustup target add aarch64-linux-android` + NDK | **not abi3** — needs a per-ABI build and a CPython for Android | the hardest target in the list; Termux has `rust` in its repos but PyO3 needs a Python dev environment |
| Windows | rustup + MSVC build tools | yes | needs the MSVC linker, not just rustup |
| macOS | rustup + Xcode CLT | yes | two architectures (x86_64, arm64) or a universal binary |

**Distribution without breaking Python-only installs.** The Rust VM is an *optional*
extra, never a required dependency:

- `pip install silica-lang` keeps working with no compiler and no wheel — the pure
  Python VM is the default, today and after R1.
- `pip install silica-lang[rust]` pulls a prebuilt extension for the platform, built
  with `abi3-py39` so one wheel per OS/arch serves every supported Python.
- If the extension is missing, fails to load, or the platform has no wheel, the CLI
  **falls back to the Python VM with a warning** and exits 0. The fallback is tested,
  not assumed.
- `.sbc` is unchanged, so a `.sbc` compiled on one platform runs on the other VM
  without recompilation.

**What R1 cannot fix:** PyO3 embeds a CPython. So on Android the "no Python" story
still fails at R1 — the extension needs a CPython for that ABI. That is the honest
boundary of this phase, and it is why the platform plan puts a pure-Rust native layer
(no PyO3) after R2.

---

## 9. Risk register

Likelihood and impact are H/M/L. Each mitigation has a validation criterion that a
reviewer can check.

| # | Risk | L | I | Mitigation | Validation criterion |
|---|---|---|---|---|---|
| 1 | Bytecode compatibility drift | M | H | Rust reads `.sbc` 1.0 unmodified; no writer in R1 | the Rust VM loads every `.sbc` produced by the Python compiler in CI, and rejects every file the Python verifier rejects (a mutation corpus) |
| 2 | Incorrect opcode semantics | **H** | H | implement in corpus-frequency order (§6); differential test per step | after each step, the runnable corpus matches stdout, stderr and exit code exactly |
| 3 | Integer overflow divergence | M | H | explicit wrapping arithmetic everywhere (`i64::wrapping_*`); parity case `int_overflow_add` | `9223372036854775807 + 1` and `max * 2` match; literal-range error message matches |
| 4 | Unicode behaviour | M | H | index by `char`, never by byte; no normalisation | `len("héllo")`=5, `len("😀")`=1, `len("e"+U+0301)`=2, `"héllo"[1]`=`é`, negative index error text |
| 5 | Float formatting | **H** | M | one shared formatting routine; bit-pattern constant keys | 1,000-double corpus matches `repr`; `0.1+0.2`, `1e-07`, `-0.0`, `inf`, `nan` match |
| 6 | Capability bypass | L | **H** | one choke point in `silica-native`; immutable `CapabilitySet`; `forbid(unsafe_code)` in `silica-vm` | a VM built without `fs.read` returns the documented error for `fs.read_text`; path traversal corpus matches Python exactly |
| 7 | GC / rooting errors | M | H | arena + mark-sweep with explicit roots; stress mode in CI | whole differential corpus passes with `SILICA_GC_STRESS=1`; closure cycle collected |
| 8 | PyO3 overhead | **H** | M | measure it separately (comparison #3); keep natives coarse-grained | native-heavy workload is no slower than the Python VM, or R1 stops at M1 |
| 9 | Packaging failures | M | M | optional extra; abi3 wheels; tested fallback | `pip install silica-lang` then `silica run` works with the extension absent, present, and deliberately corrupted |
| 10 | Python/Rust drift over time | **H** | H | Python VM stays the oracle; differential suite is the gate | CI runs three jobs (Python only, Rust only, both-compared); the third must pass |
| 11 | Long-term maintenance burden | **H** | M | 3 crates, not 9; Rust is optional; a documented "stop at M1" exit exists | the report states lines of Rust, crates, CI minutes and an owner; if the speedup does not justify it, the recommendation is to stop |

The two H×H risks — semantics drift and long-term drift — are the same risk seen at
two time scales, and they are the reason the parity corpus exists.

---

## 10. Go / no-go recommendation

**Approved — bounded, narrowed, and reversible.** (Decision B, recorded in §13.)

- **GO for M1 and M2** as a time-boxed spike (12–18 engineer-days), because the loop
  is 617 lines, the contract is executable, and the gate results are falsifiable.
- **NO-GO for the nine-crate structure** at R1. Three crates, as in §4.
- **NO-GO on any of these:** changing `.sbc`, changing default behaviour, migrating
  `fs` or the security path, adding closures, starting R2 automatically, or quoting a
  speedup before the four measurements exist.
- **Unblocked:** the `NOP` decision is made and implemented (§2.9), so the opcode
  contract is settled before a second implementation encodes it.

**Is R1 worth funding?** On the evidence: yes for the spike, because the cost is
bounded and the answer is binary — either the dispatch loop is ≥3× faster (and the
portability argument gets a foundation) or it is not (and the project stops cheaply).
It is **not** worth funding as a full VM rewrite now, because R1 keeps the natives in
Python and therefore does not deliver the thing the platform plan actually needs.

---

## 11. Estimated implementation effort

Assumptions, stated so the estimate can be rejected rather than argued with: one
engineer who already knows this codebase; no parallel work; the Python VM stays
frozen as the oracle; no closures, no async; reviews included; estimates are
engineer-days, not calendar.

| Work | Days | Notes |
|---|---|---|
| Bytecode decode + verifier port | 4–6 | the verifier is the fiddly part: operand ranges, jump boundaries, stack-depth analysis |
| Value model + formatting parity | 3–4 | the 1,000-double corpus and the struct/`oui`/`nein` renderers |
| Frames + dispatch loop (M1, 20 opcodes) | 4–6 | mechanical once decode is right |
| Differential harness + subset corpus | 2 | reuses `tests/parity/` |
| **M1 total** | **13–18** | |
| Heap, cells, mark-sweep | 4–6 | cycles and root registration are where bugs live |
| Collections + iteration opcodes | 2 | |
| `silica-native` + PyO3 bridge + capability port | 5–7 | the riskiest block: FFI, capability parity, path containment |
| **M2 total (cumulative)** | **24–33** | |
| Records, methods, `FREEZE`, long tail | 3–5 | |
| Packaging: abi3 wheels, CI matrix, fallback test | 3–5 | per-platform cost, not per-line |
| **M3 total (cumulative)** | **30–43** | |

The architecture document's earlier figure of "days, not one session" is consistent
with this; §1 quotes the M2 number because that is the gate that decides the project.

---

## 12. Exact acceptance criteria

R1 is accepted only when **every** row passes, and the evidence is attached. This
extends §16.14 of the architecture document with the M-gate criteria.

### 12.1 Gate criteria

| Gate | Criterion | Check |
|---|---|---|
| M0 | `NOP` decided and the reference updated or the table reduced | the decision is recorded; `OPS` and `vm.py` agree; a test asserts it |
| M1 | 20 opcodes execute; no FFI in the process | subset corpus matches stdout/stderr/exit code byte-for-byte |
| M1 | verifier parity | every accept/reject decision matches on the corpus **and** on a mutation corpus of hand-corrupted `.sbc` files |
| M2 | parity corpus passes | all 14 cases in `tests/parity/` pass under `--vm=rust` |
| M2 | capability parity | each of the 35 gated natives, called without its grant, returns the documented error |
| M3 | full surface | differential suite over `tests/silica/` + `examples/` matches on stdout, stderr and exit code |

### 12.2 Non-negotiable constraints

| # | Constraint | Check |
|---|---|---|
| 1 | Consumes unmodified `.sbc` from the Python compiler | compile with Python, run on Rust, no recompilation step |
| 2 | Python VM untouched | `git diff` touches nothing under `silica/` |
| 3 | Not the default | `silica run` still uses Python; `--vm=rust` is required |
| 4 | No security migration | no Rust `fs` native; capability logic unchanged |
| 5 | Fallback works | extension absent → Python VM, warning, exit 0 |
| 6 | No closures, no async, no WASM, no new modules | scope review |

### 12.3 The four measurements

| Measurement | Status | Compared against |
|---|---|---|
| Performance (four workloads, comparisons 1–4) | **not measured** | reference VM: 46.9×–111.1× slower than CPython |
| Build size (wheel, binary, per platform) | **not measured** | pure-Python wheel, no compiled component |
| Bridge overhead | **not measured** | **2.35 µs** per native call, measured (§2.11) |
| Maintenance cost (Rust LOC, crates, CI minutes, owner) | **not measured** | zero Rust in the tree today |

A row stays *not measured* until a run exists to fill it. An estimate, a projection,
or a figure borrowed from another project is not a measurement.

---

### 12.4 M1 stop-gate items

The M1 review (§14.5) must report: opcodes implemented and exercised, parity tests
passed by name, benchmark validity and reproducibility, preliminary dispatch
performance, and whether the ≥3× target still looks achievable. §14.6 lists the
conditions that end the project instead.

## 13. Recorded decisions

### Decision A — `NOP` is implemented; the 43-opcode contract stands

| | |
|---|---|
| Decision | Implement `NOP` in the Python reference VM rather than removing it |
| Rationale | The verifier already accepts it and `.sbc` is a versioned artifact; removing an opcode breaks the contract for any file that contains it |
| Behaviour | Advances the instruction pointer (already done before dispatch); no stack effect, no state, no diagnostics |
| Regression test | `tests/test_nop.py`, 11 tests, hand-built bytecode including a hand-written `.sbc` file |
| Landed | PR #8, merge commit `84e6d1ca9acedb669fc0057c4d73a89cd572c574` |
| Format impact | None — magic `SILICABC`, format 1.0, 17-byte header unchanged |
| Baseline after | 1,329 tests, 7 skipped, 0 failures |

### Decision B — bounded M1+M2 feasibility spike, three crates

| | |
|---|---|
| Decision | Approve a bounded spike estimated at 12–18 engineer-days, three-crate structure |
| Not approved | A full VM rewrite; nine crates; any change to `.sbc`, default behaviour or the Python fallback |
| Authority | The Python VM remains authoritative; Rust remains opt-in; natives stay in Python behind PyO3 for the spike |
| Stop conditions | §12.4 — a failed M1 gate ends the project, it does not trigger a redesign |
| What it does not deliver | A Python-free runtime (§15) |

---

## 14. M1 implementation plan

This is the plan to review **before** any Rust is written. M1 answers one question —
can a Rust decoder, verifier and dispatch loop reproduce the reference VM on a
non-trivial program from an unmodified `.sbc`? — and nothing else.

### 14.1 Scope

| | |
|---|---|
| In | `.sbc` decode, verifier, value model, frames, 30-opcode dispatch loop, `PRINT`/`DIT` formatting, error text, exit codes, CLI flag `--vm=rust` |
| Out | `CALL_NATIVE`, PyO3, collections, records, methods, closures, async, WASM, the front end, `fs`, any change to `.sbc` |
| Consequence | M1 can run arithmetic, control flow, function calls and printing; it cannot run anything that calls `len`, `str`, `range`, `math.*` or any other native |

### 14.2 Files, in build order

```
silica-rust/
  Cargo.toml                     workspace: 3 members, resolver 2, no external deps
  crates/silica-vm/
    Cargo.toml                   no dependencies (no PyO3, no serde, no thiserror)
    src/lib.rs                   #![forbid(unsafe_code)], module wiring
    src/error.rs                 VmError { kind, message, line, col, filename, hint }
                                 rendered exactly as "file:line:col: kind: message"
                                 plus the two-space "  hint: …" line
    src/value.rs                 Value enum, struct/iterator placeholders, and the
                                 formatting routines that PRINT/DIT use (parity §16.3)
    src/bytecode.rs              header, varint reader, decode, verifier
                                 (port of verify_function: operand ranges, jump
                                 boundaries, stack-depth analysis, limit checks)
    src/frames.rs                Frame { fn_index, ip, locals, stack }, max_frames 4096
    src/exec.rs                  the dispatch loop, one arm per opcode
  crates/silica-cli/
    Cargo.toml
    src/main.rs                  argv, .sbc loading, run, stdout/stderr, exit code
  crates/silica-native/          created empty in M1 (M2 fills it)
```

The two crates that matter for M1 are `silica-vm` (pure, testable with no CPython in
the process) and `silica-cli` (process concerns only). `silica-native` exists as an
empty member so the workspace shape is fixed before M2 needs it.

### 14.3 Opcode order inside M1

Implemented in corpus-frequency order so the runnable set grows fastest, and each
step is committed only when its tests pass:

| Step | Opcodes | Runnable after |
|---|---|---|
| 1 | `CONST LOAD_LOCAL STORE_LOCAL RET UNIT PRINT NOP` | printing a literal |
| 2 | `ADD SUB MUL DIV MOD NEG` | integer/float arithmetic, wrapping |
| 3 | `EQ NE LT LE GT GE` | comparisons |
| 4 | `TRUE FALSE JUMP JUMP_IF_FALSE` | `si`, `tant`, `per` over ranges |
| 5 | `CALL POP HALT_OK HALT_POP` | functions, recursion, exit codes → **the M1 benchmark runs** |
| 6 | `LOAD_GLOBAL STORE_GLOBAL DIT` | globals, `dit` |

### 14.4 Test plan

| Test | What it asserts |
|---|---|
| Decoder parity | every `.sbc` the Python compiler emits in the corpus decodes to the same instruction stream (offset, opcode, operands) as Python's `decode` |
| Verifier parity | the same accept/reject decision as `verify_chunk` on the corpus **and** on a mutation corpus (truncated payload, bad CRC, bad magic, unknown opcode, bad jump target, stack underflow) |
| Value parity | `format_value` equivalence: ints, floats (1,000-double corpus), `oui`/`nein`, strings, `Point(x: 3, y: 4)`, `{"a": 1}`, `[]` |
| Error parity | `file:line:col: message` plus the hint line, byte for byte |
| Execution parity | the M1 benchmark and a subset corpus produce identical stdout and exit code |
| Startup separation | process start, decode, execution timed separately |

### 14.5 The M1 stop gate — what the report must contain

Before M2 is discussed, the report states, for each item, a number or a verdict:

1. Which opcodes are implemented, and which of the 30 are exercised by the passing tests.
2. Which parity tests pass — named, with counts, not "parity looks good".
3. Whether the arithmetic benchmark is valid and reproducible: same output
   (`1499997500000`), median of 3, machine named, startup subtracted.
4. Preliminary dispatch performance, as a ratio measured by `benchmarks/gate.py`
   against the reference VM in the same session.
5. Whether the **≥3×** target still appears achievable, and if not, what the
   measurement suggests instead. The gate definition is frozen in
   `docs/design/SILICA_R1_BENCHMARK_READINESS.md`; it is not renegotiable after the
   fact.

### 14.6 Stop conditions

R1 stops, and is reported as a negative result, if **any** of these holds:

| # | Condition |
|---|---|
| 1 | The M1 benchmark is **not ≥3×** faster than the reference VM |
| 2 | Decoder or verifier parity cannot be reached on the corpus (a decision differs) |
| 3 | Exact error text cannot be reproduced without contorting the design |
| 4 | The dispatch loop needs `unsafe` in `silica-vm` to be fast enough |
| 5 | The work exceeds the 12–18 day bound without reaching the gate |
| 6 | Any requirement forces a change to `.sbc`, the Python VM's semantics, or the default VM |

Stopping is a valid outcome. It is reported with the measurements that caused it, and
it does not trigger a redesign, a second attempt, or R2.

---

## 15. What the spike does not deliver

Stated plainly, because the most expensive misunderstanding available here is
believing R1 removes the Python dependency:

- **Not a Python-free runtime.** M1 uses no Python at all — but only because it cannot
  call a single native. M2 brings PyO3 back, so the shipped result still embeds
  CPython. `len`, `str`, `range`, `math.*`, `fs`, `ui`, `tui`, `gui`, `speech` all
  remain Python.
- **Not a performance claim.** One benchmark, one workload, one machine. If it passes
  the gate, the claim is "3× faster on this arithmetic loop", not "Silica is faster".
- **Not Android or desktop readiness.** PyO3 needs a CPython for the target ABI, so the
  "no Python on the device" story still fails at the end of M2.
- **Not a full VM.** 30 of 43 opcodes at M1, 37 at M2; collections and records arrive
  later, and the front end never moves in this phase.
- **Not a commitment to R2.** A green M2 is evidence, not authorisation.

---

## 16. What this review did not do

- No Rust code was written; no toolchain exists in the review environment.
- `.sbc` was not changed, the Python VM's semantics were not changed beyond
  implementing the already-declared `NOP`, the default VM was not changed, no closure
  syntax was added, `fs` and the security path were not migrated, and the Python
  fallback was not removed.
- No performance improvement is claimed. The only performance numbers here are
  measurements of the **Python** VM, taken to define the baseline.
- R2 was not started.



- No Rust code was written; no toolchain exists in the review environment.
- `.sbc` was not changed, the Python VM's semantics were not changed, the default VM
  was not changed, no closure syntax was added, `fs` and the security path were not
  migrated, and the Python fallback was not removed.
- No performance improvement is claimed. The only performance numbers here are
  measurements of the **Python** VM, taken to define the baseline.
- R1 and R2 were not started.
