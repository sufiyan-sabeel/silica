# Silica audit and prioritised roadmap

Stage A of the language brief: establish the baseline, document what exists,
record the real numbers, and propose an order of work. Nothing here is a plan to
rewrite the project — it is an evidence-based account of where it stands.

Every figure below was produced by running something, and the command is given so
it can be reproduced.

---

## 1. Baseline

```
$ python3 -m unittest discover -s tests -t .
Ran 671 tests ... OK (skipped=7)

$ python3 -m silica test tests
5/5 test files passed

$ python3 -m silica fmt --check examples/*.sc tests/silica/*.sc benchmarks/silica/*.sc
(exit 0)
```

Re-run on 2026-10-28 for this release. The first version of this audit recorded
555 tests at 0.8.0; that figure is historical and has been superseded.

| | |
|---|---|
| Version | 0.9.2 |
| Implementation | Python 3.9+, ~10,700 lines in `silica/`, ~5,900 lines of tests |
| Test count | 671 |
| Bytecode format | `.sbc` 1.0, versioned, verified on load |
| CI | GitHub Actions, Python 3.9 / 3.11 / 3.12 |

---

## 2. What exists

### Language

Lexer, recursive-descent parser, AST, type checker, bytecode compiler, a
verifying loader and a stack VM. Keywords are Silica's own (`sfn`, `sprint`, `si`,
`sino`, `ret`, `oui`, `nein`, `tant`, `per`, `und`, `ou`, `non`). Types are
`Int`, `Float`, `Bool`, `String`, `Unit`, `List`, `Map`, `Any` — with no generics,
so `List` and `Map` elements check as `Any`.

Builder blocks (`call { ... }`) and dotted module paths (`use ui.lib.widgets`) were
added in 0.2.0. Both were parse errors before, so they are provably additive.

### Standard library — 23 namespaces, 174 native functions

```
core 14   math 8   string 9   collections 4   json 2   fs 4   speech 6
ui 16 + 6 submodules (widgets 18, colors 3, layout 2, scroll 2, theme 2, animation 1)
tui 23 + 3 submodules   gui 22 + 3 submodules
```

**Planned but absent:** `path`, `time`, `random`, `regex`, `http`, `net`,
`process`, `log`, `crypto`, `test`, `async`, `ai`. Importing one is a compile
error that says so; it does not pretend to load.

### Toolchain

`run`, `check`, `compile`, `fmt`, `test`, `repl`, `capabilities`, `voice`, plus
direct `silica file.sc`. An installer (`install.sh`) with SHA-256 verification, an
uninstaller, and a release workflow.

### Security model

Capability-based, least privilege by default. Seven capabilities: `fs.read`,
`fs.write`, `fs.list`, `speech.speak`, `speech.listen`, `speech.models`,
`tui.run`, `gui.run`.
Enforcement happens at the VM's native dispatch point, before the function body
runs, so a native cannot forget to check. Paths are resolved and containment-checked
once, and the resolved path is what the native receives.

---

## 3. Performance, measured

```
$ python3 benchmarks/bench.py --runs 3
host: Linux x86_64 · python 3.12.13 · silica 0.9.2 · best of 3
workload                                       silica     python      ratio  check
arithmetic loop (1e6 iterations)             15155.8ms     323.4ms     46.87x  ok
recursion (fib 24)                            1945.0ms      17.5ms    111.06x  ok
collections (200k push + iterate + sort)      3098.0ms      56.6ms     54.76x  ok
strings (20k join + split)                     183.1ms       3.7ms     49.53x  ok
```

Re-measured on 2026-10-28 for this release. Silica is **47–111× slower than
CPython** on these workloads. That is expected: the VM is a Python loop over
decoded instructions, and every value is a Python object. **No claim is made that
Silica is fast.** Publishing "faster than Python" here would be false.

The number worth acting on is the *shape*: recursion is worst (111×) because every
Silica call builds a `Frame` and pushes a Python list; arithmetic is 47× because
dispatch dominates. Those are the two places a profiler would point first.

### The earlier 0.8.0 run — historical, not current

The first audit recorded the same four workloads at 41–93× (`--runs 1`, Python
3.12.13). Those figures are kept only as history: they were taken before the
release that added this run, on a different load, and the spread between runs of
the same benchmark is several percent. Treat the table above as the current
number and any older one as superseded.

### Since this audit: constant folding (0.8.0)

`silica/optimizer.py` folds literal arithmetic at compile time. Measured with
`python3 benchmarks/optimizer.py`:

| What | Off | On | Change |
|---|---|---|---|
| Instructions, 200 literal expressions | 1602 | 402 | −74.9% |
| Bytecode, same program | 5214 B | 3145 B | −39.7% |
| Hot loop, 300k iterations | 3.477 s | 2.113 s | −39.2% |

Output is identical in every case, and a differential test compiles 32 expressions
both ways and requires the same stdout, stderr and exit code. This does not change
the table above, because those benchmarks use variables, not literals — folding
has nothing to fold there. The next real win is the call path, which is Stage F of
the roadmap below.

---

## 4. Known gaps and technical debt

Ordered by how much they block other work.

1. **No closures or first-class functions.** This is the single biggest language
   gap. It is why the TUI polls for events instead of dispatching callbacks, and
   why GUI handlers are resolved by name. Everything else that wants callbacks —
   `iter` pipelines, `async`, `test` fixtures — is blocked behind it.
2. **No generics.** `List` and `Map` are `Any`-typed internally, so container
   errors surface at run time, not compile time.
3. **No structs, enums or pattern matching.** Programs model data as nested maps,
   which the checker cannot verify.
4. **No error type.** Failures are runtime aborts; there is no `Result` or typed
   error, so recovery is impossible in-language.
5. **Formatter drops comments.** `silica fmt` refuses a file containing comments
   rather than preserving them. Every example is therefore comment-free.
6. **The VM is slow** (section 3), and there is no profiler to say where.
7. **No package manager.** `silica.toml` is documented but `new/add/install/build`
   are unimplemented and say so.
8. **No language server, debugger or doc generator.**
9. **Test coverage is behavioural, not measured.** There is no coverage number;
   the suite is 555 tests but nobody knows which lines they miss.
10. **GUI/TUI event models diverge from the brief's callback shape** because of
    gap 1.

---

## 5. Prioritised roadmap

Ordered so each stage unblocks the next. Acceptance criteria are stated as things
that can be run.

### Stage B — Functions as values (highest value)

Closures, or at minimum function references.

* `let f = twice` and passing a function as an argument.
* Callback-based `tui.on_key` / `gui.on_click(widget, fn)` with real closures.
* **Acceptance:** `tui` and `gui` handlers take a function value; a closure
  capturing a local works; `.sbc` format bumps to 1.1 with a documented migration.

This is first because it is the blocker for four other items.

### Stage C — Types that can express data

Structs, enums, pattern matching, then generics.

* `struct Point { x: Int, y: Int }`, `enum Shape { Circle(Float), Square(Float) }`,
  `si shape { Circle(r) { ... } }`.
* Generic `List<T>` / `Map<K, V>` with checker enforcement.
* **Acceptance:** container element errors are compile-time; existing programs
  still pass.

### Stage D — Errors as values

* `Result<T, E>` in the standard library, plus `?`-style propagation.
* **Acceptance:** a function can return an error and the caller can handle it;
  runtime aborts remain for genuine bugs.

### Stage E — Missing standard library

In dependency order, each with tests: `time`, `random`, `path`, `iter`, `log`,
`regex`. Then the capability-gated ones: `process`, `net`, `http`. Then `crypto`,
using a vetted library and never a hand-rolled primitive.

* **Acceptance:** each module documented, tested, capability-scoped, and absent
  from `PLANNED_MODULES`.

### Stage F — Performance, measured

Profile first, then optimise what the profile says.

* A profiler for the VM (instruction counts, hot functions).
* Then: specialised dispatch, avoiding `Frame` allocation on calls, caching
  constant lookups.
* **Acceptance:** the benchmark table in this document improves by a stated
  factor, re-measured, with the command recorded. No claim without a number.

### Stage G — Packages

`silica.toml` manifest, lockfile, `silica add/install/build`, checksums, offline
installs. `silica new` first, because it is trivial and unblocks examples.

* **Acceptance:** a two-package project resolves reproducibly; a tampered package
  is refused; `install` never reports success without installing.

### Stage H — Tooling

Language server (diagnostics, completion, definition, references), debugger
(breakpoints, stack, variables), `silica doc`.

* **Acceptance:** an editor shows a type error from the LSP; a breakpoint stops
  the VM and shows a frame.

### Stage I — Conformance suite, then native backend

* Freeze a conformance suite: programs with expected stdout, stderr and exit code,
  run against any implementation.
* Only then evaluate Rust for the VM or a native backend, against that suite.
* **Acceptance:** a second implementation passes the suite or is not adopted.

### Explicitly not planned

Self-hosting, a JIT, and claiming platform support that has not been tested on
that platform. Each would need its own evidence.

---

## 6. What this audit did not do

It did not profile (there is no profiler yet), it did not measure coverage (there
is no coverage tool wired in), and it did not test on macOS, Windows or Termux.
Those are named here rather than left as implied claims.
