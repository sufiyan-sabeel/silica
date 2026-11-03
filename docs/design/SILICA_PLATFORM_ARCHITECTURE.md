# Silica Platform Architecture

**Status:** revised for review — design direction approved, decisions recorded,
Rust migration designed (not approved)
**Applies to:** Silica 0.10.0 (`sufiyan-sabeel/silica`)
**Document version:** 1.6 · 2026-11-03
**Scope:** how Silica becomes able to build web, desktop, Android, GUI/TUI and
eventually system software — without breaking anything that works today — and how
its VM moves to Rust without a rewrite

**Revision history**

| Version | Change |
|---|---|
| 1.0 | Initial audit and proposal; six open decisions raised |
| 1.1 | Decisions 1–6 recorded (§12); first-class functions and closures designed (§13); trade-offs that remain open (§14) |
| 1.2 | Rust VM migration strategy (§16); closure memory model without CPython (§13.10); runtime-neutral closure representation (§13.5); parity hazards named as contract terms (§16.3) |
| 1.3 | Parity hazards measured against the running VM and pinned by executable tests (§16.3, §16.13); one optimizer defect found and recorded (§16.13.5); R1 boundary and acceptance criteria fixed (§16.14) |
| 1.6 | The float constant-intern defect is **fixed** (bit-pattern pool keys, §16.13.6) and the strict xfail is retired; the corrected parity contract is **frozen** for R1. Baseline re-run: 1,318 tests, 0 failures. |
| 1.5 | Design phase closed. Baseline command and output recorded verbatim (§16.14.1); the four R1 measurements marked **not measured** with the figures they will be compared against (§16.14.3). No implementation started. |
| 1.4 | R1 approved for a feasibility prototype only. Strict-xfail regression test for the optimizer defect; the float correction isolated as its own change with its compatibility impact (§16.13.6); exit codes and hints verified in the runner (§16.14); product-versus-environment reporting rule (§16.14.1); normative parity statement (§16.14.2) |

Nothing in this document is implemented. No closure, async, WASM, platform backend
or Rust code may be written until this revision is approved.

---

## 0. Summary

Silica today is a Python-hosted language: a lexer, parser, checker, bytecode
compiler, verifier and stack VM, 29 standard-library modules, three UI renderers
and a sandboxed Python interop channel. It can run programs, draw a terminal UI,
open a tkinter window, render a web page and drive speech synthesis. It cannot
produce a standalone binary, cannot call a platform API that has no Silica
binding, cannot run two things at once, and has no package ecosystem.

The core claim of this proposal is unchanged:

> **Platforms are reached through host processes, not through the VM.** Silica
> logic stays in `.sc` files and bytecode; every platform API is reached through
> a validated bridge with the same handle discipline the Python interop already
> uses. The VM never gains the ability to touch a raw pointer, a file
> descriptor, a JNI reference or a browser object directly.

Two things gate everything after the front end:

1. **Silica has no first-class functions**, which makes real event handling,
   callbacks and any async model impossible to express. §13 designs that work.
2. **The runtime is CPython**, which blocks standalone binaries, makes desktop
   and Android packaging expensive, and costs 46.9×–111.1× versus CPython on the
   recorded benchmarks. §16 designs a migration to a Rust VM that consumes the
   *existing* compiler output — no rewrite, no fork of the semantics.

Both are design-only. The Python VM remains the semantic reference
implementation throughout, permanently.

---

## 1. Method, and what this document is not

Everything in §2 was read out of the v0.10.0 tree, not from the roadmap:

```
python3 -c "from silica.natives import MODULES; print(len(MODULES))"        # 29
python3 -c "from silica.bytecode import OPS; print(len(OPS))"               # 43
python3 -c "from silica import capabilities; print(capabilities.KNOWN)"     # 9
wc -l silica/*.py silica/*/*.py | tail -1                                   # 17,083
python3 -m unittest discover -s tests -t .                                  # 1,201 collected
```

It is **not** a promise, a schedule, or a statement that any of this is easy. It
is a proposal with acceptance criteria, written so that a reviewer can reject
individual phases.

Three existing documents are load-bearing and are not repeated here:
`docs/INTEROPERABILITY.md` (bridge protocol, handles, C ABI, WASI),
`docs/SECURITY_MODEL.md` (what capability checks do and do not guarantee) and
`docs/BYTECODE.md` (the `.sbc` container). Where they decide something, they win.

---

## 2. Current capability audit

### 2.1 The pipeline

| Stage | File | Role |
|---|---|---|
| Lexer | `silica/lexer.py` | tokens with line/column, comments preserved for the formatter |
| Parser | `silica/parser.py` | recursive descent to an AST; braces, newline-terminated statements |
| Checker | `silica/checker.py` | scopes, arities, struct/class fields, generics, constraints |
| Compiler | `silica/compiler.py` | AST to a bytecode chunk, locals in numbered slots |
| Bytecode | `silica/bytecode.py` | `.sbc` container: magic `SILICABC`, format 1.0, CRC-32, line table |
| Verifier | `silica/bytecode.py` | rejects malformed input before execution |
| VM | `silica/vm.py` | stack machine, explicit frames, `max_frames=4096` |
| Engine | `silica/engine.py` | ties the stages together for the CLI |

43 opcodes (§16.2). The VM is single-threaded and re-entrant only in the sense
that a native may call back into it (the GUI click handler does exactly that).

### 2.2 Standard library — 29 modules, 316 natives

| Domain | Modules | Notes |
|---|---|---|
| Core language | `core` (14) | `sprint`, `dit`, `len`, `range`, `push`, `keys`, `has`, `type_of`, conversions |
| Data | `collections` (4), `json` (2), `string` (9) | no user-defined modules yet |
| Text/paths | `path` (11), `time` (9), `random` (8), `math` (8) | `path` is lexical only, no capability |
| I/O | `fs` (4) | behind `fs.read` / `fs.write` / `fs.list` |
| Colour | `colors` (29) | OKLab/OKLCH/P3, WCAG audit, CSS output |
| UI | `ui` (16) + 6 `ui.lib.*` modules | renders to HTML/CSS + a JS action runtime |
| Terminal UI | `tui` (39) + 3 `tui.lib.*` | ANSI, capability `tui.run` |
| Desktop GUI | `gui` (22) + 3 `gui.lib.*` | tkinter, capability `gui.run` |
| Speech | `speech` (23), `voice` (23) | capability `speech.*`; needs models on disk |
| Interop | `python` (7) | capability `interop.python`; worker process + handles |

Reserved and failing loudly: `ai`, `async`, `crypto`, `http`, `log`, `net`,
`process`, `regex`, `test`.

### 2.3 The UI model — the constraint that shapes everything else

`ui.render({target: "web", out: "build/index.html"})` writes three files: the
HTML document, `theme.css` and `silica-ui-runtime.js`. Layout is CSS; the
renderer emits flexbox/grid and lets the browser do the work.

Crucially: **an event body is not Silica running in the browser.** It is lowered
to a declarative JSON action list that the JS runtime interprets. Anything
beyond that action table runs at build time, or not at all. `gui.on_click` takes
the *name* of a Silica function because there are no first-class functions to
pass.

This is honest and it is also the ceiling: an interactive web app cannot run its
own logic in the browser today. §5.2 addresses this directly; §13 removes the
language-level cause.

### 2.4 Interop as it exists (the template for platforms)

`docs/INTEROPERABILITY.md` defines a worker protocol: frames of
`magic "SIW1" | version | kind | request id | payload length | JSON`, 8 MiB per
frame, JSON only (nothing is unpickled), and **opaque 128-bit handles** — a
Silica program never sees an address, a file descriptor or a native integer.
Released tokens are refused rather than resolving to null. Access needs
`interop.python`, which is denied by default.

That is the pattern every platform bridge in this proposal copies.

### 2.5 Classification

| Capability | State | Evidence |
|---|---|---|
| Language, checker, generics, classes, structs | **existing** | 1,201 tests collected; `tests/test_generics.py` |
| Bytecode compile + verify + reload | **existing** | `docs/BYTECODE.md`, format 1.0 |
| Capability checks on `fs`, `tui`, `gui`, `speech`, `interop` | **existing** | `docs/SECURITY_MODEL.md` |
| Terminal UI | **existing** | `tui` module, `docs/TUI.md` |
| Desktop windows | **existing, minimal** | tkinter; one window, 22 natives, handlers by name |
| Web rendering | **existing, static** | HTML + CSS + JS action runtime; no Silica logic in the browser |
| Python interop | **existing** | worker process, handles, `interop.python` |
| Application examples | **existing** | `examples/calculator_app.sc`, `task_manager.sc`, `data_report.sc` |
| Event handlers that call arbitrary Silica code in a browser | **partial** | action list only, no closures |
| Concurrency | **unsupported** | single-threaded VM, no async, `async` module reserved |
| Exceptions / error values | **unsupported** | errors abort with a located diagnostic |
| Network, HTTP, TLS, crypto | **unsupported** | modules reserved and failing |
| Native code (C ABI), JNI, WASM | **unsupported** | designed in `INTEROPERABILITY.md`, not built |
| User packages, registry, lockfile | **unsupported** | `use` resolves built-ins only |
| Standalone binary, app packaging | **unsupported** | pure-Python wheel + `install.sh` |
| Rust VM | **unsupported** | §16 designs it; no code exists |
| Self-hosting | **unsupported** | `docs/BOOTSTRAP.md`: plan only |

### 2.6 Per-target matrix today

| Target | Can build today | Missing to be "an application" |
|---|---|---|
| **Web** | a rendered page with declarative events | logic in the browser, routing, data fetch, build output |
| **Desktop** | one tkinter window with name-based handlers | packaging, menus, dialogs, file pickers, real event loop |
| **Android** | nothing | everything: runtime, JNI, lifecycle, manifest, APK |
| **GUI/TUI** | TUI apps; minimal GUI | persistence of state, richer widgets, input handling |
| **Operating system** | nothing | a freestanding runtime, memory management, drivers — out of scope for years |

---

## 3. Architectural limitations of the Python-hosted VM

Each of these is a real constraint with a consequence, not a to-do item.

1. **CPython is the runtime.** No standalone binary; the user needs Python 3.9+.
   *Consequence:* desktop/Android packaging needs either an embedded CPython or a
   different execution backend. §16 is the path to the latter.
2. **Speed: 46.9×–111.1× slower than CPython** on the recorded benchmarks
   (`docs/PERFORMANCE.md`, 2026-10-28). *Consequence:* a browser-side runtime
   must not be a port of this interpreter if it is to run interactive UI; and any
   Rust VM must be measured, not assumed (§16.9).
3. **No first-class functions.** Handlers are names. *Consequence:* no
   callbacks, no middleware, no closures over UI state — the single biggest
   blocker for real applications. §13 designs the fix.
4. **Single-threaded, no concurrency primitives.** *Consequence:* a server cannot
   serve two requests; a GUI cannot do work without freezing.
5. **No exceptions or error values.** A failure aborts the program.
   *Consequence:* any real I/O layer needs a `Result`-shaped value. Decision 1.
6. **No FFI.** Platform APIs are reachable only through a maintained bridge
   process, or through a new `extern` mechanism.
7. **No user packages.** No ecosystem; every project copies code.
8. **No byte type.** Binary protocols are hex/URL-safe text; a conversion tax.
9. **The VM is not a sandbox.** Capability checks stop a *program* from asking
   for a file; they do not stop a malicious *engine build*, and they are not an
   OS boundary.
10. **No debugger protocol.** Line tables exist; nothing consumes them.

---

## 4. What "build an application" means per target

For each target: what the developer writes, what the build produces, where the
logic runs, and what has to be true before the target may be called supported.

### 4.1 Web

**Definition of done:** `silica build --target web` produces a directory that a
static host serves, and the application's *logic* runs in the browser.

| | `web.static` | `web.app` |
|---|---|---|
| Logic runs | at build time (today's `ui.render`) | in the browser |
| Output | `index.html`, `theme.css`, `silica-ui-runtime.js` | the same, plus a compiled module |
| Ships today | yes | no |

`web.app` requires compiling Silica to a form the browser executes. WASM is a
**proposed strategy, not a commitment** — decision 4 requires a feasibility
prototype first (§12, Phase 3a).

### 4.2 Desktop

**Definition of done:** `silica build --target desktop` produces a single
directory or archive that runs on a machine with no Python installed.

Per decision 3, tkinter **stays** as the desktop backend for now, and the work is
to put a toolkit-independent interface in front of it so a native backend can be
added later without touching application logic. A Rust VM (§16) removes the
CPython dependency from the *execution* side; the UI toolkit remains a separate
question.

### 4.3 Android

**Definition of done:** an APK that installs and runs, with the application logic
in `.sc` files compiled to bytecode, executed by an embedded runtime, and
platform APIs reached over JNI through the same handle protocol.

A Rust VM is the realistic embedding target here; CPython-in-an-APK is a
prototype, not a shipping plan (§5.3).

### 4.4 GUI / TUI

**Definition of done:** an application with persistent state, keyboard and
pointer input, and a lifecycle — not a single rendered frame.

TUI is closest to done: `tui` has 39 natives, polling, focus and selection.
What is missing is a state model that survives redraws and an input loop that
can call back into Silica code — which is §13.

### 4.5 Operating system

**Definition of done:** there isn't one that can be claimed in this decade. What
this document commits to is only this: **nothing in phases 1–6 or the Rust
migration may make an eventual freestanding runtime harder** — no dependency on
CPython object identity in the bytecode, no host-pointer values in the VM,
handles everywhere, and a value model that is already arena-based (§13.10).

---

## 5. Interoperability strategy

### 5.1 Four bridges, one discipline

| Bridge | Reaches | Mechanism | Phase |
|---|---|---|---|
| **Worker** (exists) | Python | `SIW1` frames over a pipe, JSON, handles | 0 |
| **Native host** | C ABI (`dlopen`), OS APIs, dialogs, tray | host process, same frames, typed signatures | 6 |
| **JNI host** | Android/Java | Kotlin host process, same frames, handles | 5 |
| **WASM** | browser, sandboxed compute | compile Silica to `.wasm`, JS host provides imports | 3 |

The rule that makes this tractable: **a bridge exposes a typed surface, not an
object graph.** A Silica program receives an opaque handle or a plain value
(`Int`, `Float`, `String`, `Bool`, `List`, `Map`, struct) — never a host object.
`docs/INTEROPERABILITY.md` §2 already defines the value mapping; every new bridge
reuses it rather than inventing one.

### 5.2 Keeping logic in `.sc`

- the `.sc` sources compile to bytecode for host targets and to a browser
  artifact for the web target — one front end, two back ends;
- platform APIs appear as ordinary Silica modules (`web.*`, `desktop.*`,
  `android.*`) whose natives are bridge calls;
- the language surface does not change per target: the same `sfn main()` runs
  everywhere, and a target that cannot support a module fails at *link* time with
  a named error, not at runtime.

### 5.3 What is explicitly rejected

- **Transpiling Silica to Kotlin/Java/Swift source.** It forks the semantics.
- **Running the Python VM inside an Android app as the primary path.** It is a
  legitimate prototype, but it ships a CPython interpreter and a process boundary
  into a phone.
- **Exposing Python objects as Silica values.** Already forbidden.
- **A full Rust rewrite up front.** Rejected by the reviewer, and rejected here
  on the merits: it would fork the semantics with no oracle to check against.

---

## 6. Compiler and runtime evolution

Ordered so each step is additive. **No step may change the meaning of an
existing program**; `tests/test_compat_093.py` and the full suite are the gate.

| Phase | Change | Language impact | Bytecode |
|---|---|---|---|
| P0 | Bridges only; no language change | none | unchanged |
| P1 | Module system + package manifest | new `use pkg` resolution | unchanged |
| P2 | First-class functions, closures (§13) | new: function values, capture rules | **minor bump**: `MAKE_CLOSURE`, `CALL_VALUE`, upvalue ops |
| P3 | `Result` error values (decision 1) | new: one value type, no unwinding | minor bump if a new tag is needed |
| P4 | Concurrency — async/await (decision 2) | new keywords | bump |
| P5 | `extern` declarations for C ABI | new declaration form | bump |
| P6 | Alternative back end (WASM, then Rust VM) | none | new target, same semantics |

**Ordering is fixed by decision 2:** function values, closures, capture semantics
and their VM representation come first; the event loop and async model are
designed *on top of* that representation, not before it.

**The Rust VM is a parallel track, not a language phase.** Its stages (R1–R5,
§16.11) can run alongside P1 and P2 but must never change `.sbc`, `.sc` or any
observable behaviour. The closure representation in §13.5 is specified so that
the Python VM and the Rust VM implement the *same* semantics from day one.

**Bytecode policy.** `FORMAT_MAJOR` changes only for an incompatible layout;
adding opcodes bumps `FORMAT_MINOR` and keeps older readers able to *reject*
rather than misread. Every bump updates `docs/BYTECODE.md`, the verifier's stack
table, and the round-trip tests in the same commit.

---

## 7. Standard-library roadmap

| Order | Modules | Unlocks | Notes |
|---|---|---|---|
| 1 | `process`, `log` | desktop, CLI tools | `process` behind a capability; no shell interpolation |
| 2 | `net` (TCP), `http` (client) | web.app, desktop | TLS via the host, not hand-rolled |
| 3 | `crypto` (hash, HMAC, AEAD) | auth, tokens | never invent primitives; wrap a vetted library |
| 4 | `async` (decision 2 model) | servers, UI responsiveness | must not leak host futures into Silica |
| 5 | `regex` | text tools | define the dialect before implementing |
| 6 | `test` | CI for user projects | assertion library on top of `silica test` |
| 7 | `web.*`, `desktop.*`, `android.*` | platform APIs | thin, typed, one native per documented behaviour |
| 8 | `ai` | later | out of scope for the platform phases |

Rule carried over from 0.10.0: a module is either implemented and documented with
tests, or it stays in `PLANNED_MODULES` and fails loudly. There is no third state.

---

## 8. Project structure and build tooling

```
myapp/
  silica.toml            # name, version, entry, targets, capabilities, deps
  silica.lock            # pinned commits + checksums (decision 5)
  src/main.sc
  src/ui/*.sc
  assets/
  tests/*_test.sc
```

```toml
[app]
name = "myapp"
version = "0.1.0"
entry = "src/main.sc"

[targets]
web     = { out = "dist/web" }
desktop = { out = "dist/desktop" }

[capabilities]
fs.read = ["assets"]

[dependencies]
"git+https://example.invalid/util" = { rev = "<commit-sha>", sha256 = "<checksum>" }
```

Commands, each of which must exist before its phase is "done":

```
silica new myapp                  # scaffold the tree above
silica add <git-url>              # resolve to a pinned commit, verify checksum, write lock
silica build --target web         # emit dist/web
silica build --target desktop     # emit dist/desktop
silica run --capabilities silica.toml
silica run --vm=rust              # §16.8, until the Rust VM is the default
silica test
```

Resolution is deterministic and offline-verifiable: `silica.lock` pins every
dependency to a commit and a checksum, and `silica add --locked` must fail if a
remote commit no longer matches its recorded hash. Artifacts are deterministic:
same inputs, same bytes.

---

## 9. Security model per target

| Target | Additional capabilities | Explicitly not guaranteed |
|---|---|---|
| Web (static) | none; the page is inert data | nothing about what a browser extension can do |
| Web (WASM) | `web.fetch` for network, per-origin in the host | WASM isolation is the browser's, not ours |
| Desktop | `process.spawn`, `desktop.dialogs`, `desktop.tray` | that a signed app cannot be tampered with after install |
| Android | `android.intent`, `android.permissions`, `android.storage` | that the OS permission model maps 1:1 to ours |
| Any | — | **the VM is not an OS sandbox** (unchanged from `SECURITY_MODEL.md`) |

Two new rules for platform work:

1. A bridge must validate **shape and length** before dispatch — the frame limits
   in `INTEROPERABILITY.md` §9 apply to every new bridge.
2. A capability may never be granted implicitly by a platform (an Android
   permission in the manifest must not auto-grant the Silica capability).

A third rule applies to the Rust VM and is specified in §16.6: **the capability
check is a property of the native dispatch path, not of the VM implementation**,
and no Rust-side optimisation may skip it.

---

## 10. Phased plan with acceptance criteria

Every phase has a gate that is a command and an expected result.

### Phase 0 — this document *(current)*

**Gate:** reviewed and approved; no code merged. Decisions 1–6 recorded (§12).

### Phase 1 — packages and project structure *(no language change)*

- `silica.toml`, `silica.lock`, `silica new`, `silica add` (pinned commits and
  checksums only; no registry — decision 5).
- `use` resolves user modules from the manifest, built-ins unchanged.

**Acceptance:** `silica new demo && cd demo && silica run` prints the scaffolded
greeting; a project depending on a local package builds; `silica add --locked`
fails when a checksum no longer matches; **all existing tests still pass**;
`silica fmt --check examples/*.sc` exits 0.

### Phase 2 — first-class functions and closures *(the hinge, §13)*

- Function values, closures, capture rules, `MAKE_CLOSURE`, `CALL_VALUE`, upvalue
  opcodes.
- Checker: function types, capture analysis, arity through values.
- `gui.on_click` and `tui` handlers accept a function value; the name form keeps
  working unchanged.

**Gate before code:** §13 approved, including capture, lifetime and the
memory-management model in §13.10.

**Acceptance:** the per-iteration binding case behaves as specified; a closure
escaping its defining function keeps its captures alive; arity and type
mismatches are compile errors; `.sbc` round-trips a program with closures;
`tests/test_compat_093.py` and the full suite pass; `FORMAT_MINOR` bumped with
verifier tests.

### Phase 3a — WASM feasibility prototype *(decision 4: prove, then decide)*

- Compiles the existing bytecode representation to WASM for a narrow subset
  (arithmetic, calls, structs, loops) and runs it under Node and in a browser.
- No new standard-library surface, no UI, no CLI build command.

**Acceptance:** the prototype reproduces the documented output of five existing
`examples/*.sc` byte-for-byte; a written comparison against the alternatives with
measured size and startup numbers. The full backend is approved only after that
report is reviewed.

### Phase 3b — web target (`web.app`)

**Acceptance:** `examples/calculator_app.sc` builds and runs in a headless
Chromium in CI with **zero console errors**; identical stdout under `silica run`;
artifact set asserted by a test; no `.sc` file changes between targets.

### Phase 4 — desktop target

**Acceptance:** built app runs on a machine **without Python installed**; opens a
window, reads a file through a granted capability, and refuses it when not
granted (tested both ways); startup to first frame measured and recorded; the
existing `gui` tests pass unchanged.

### Phase 5 — Android target

**Acceptance:** APK installs on an emulator; the app starts, handles a lifecycle
event, calls one platform API through a handle, and returns a value; a denied
capability produces the documented error, not a crash.

### Phase 6 — native FFI (`extern`)

**Acceptance:** a documented C library is called through a declared signature;
passing a wrong type is a compile error; a length-bounded buffer test passes.

### Phase 7 — system software *(research, not scheduled)*

No acceptance criteria are defined, because none can be honestly promised.

---

## 11. Risks and trade-offs

| Risk | Impact | Mitigation |
|---|---|---|
| Two back ends to keep in step | divergence between host and web behaviour | one front end, shared checker, differential tests (§16.7) |
| Two VMs to keep in step | semantic drift between Python and Rust | Python stays the oracle; differential suite is the gate (§16.7) |
| Embedding CPython makes desktop builds large and slow to start | 30–60 MB, slow cold start | the Rust VM is the long-term answer (§16) |
| Android work is unbounded | months, device-specific bugs | strict gate: one app, one lifecycle event, one API |
| First-class functions change semantics subtly | silent behaviour drift | written capture rules + differential tests (§13.9) |
| Capability model fragments per platform | security claims become untrue | one capability registry; single dispatch choke point (§16.6) |
| The 46–111× performance gap makes desktop apps feel broken | user-visible | measure and publish per phase; no performance claim before a benchmark |
| `Result` everywhere makes ordinary code noisy | developer friction | a narrow, documented set of helpers; no exceptions smuggled back in |
| Rust GC pauses appear under load | latency spikes | threshold-triggered collection, stress mode in tests, nursery later (§13.10) |

**Alternatives considered and rejected:** transpile-to-Kotlin (§5.3); a
JavaScript interpreter of Silica bytecode in the browser; building all targets at
once; a full Rust rewrite before the semantics are pinned (§16.1).

---

## 12. Recorded decisions

### Decision 1 — Error model: `Result`, not exceptions

**Decided:** expected failures — I/O, network, interop — return a `Result`-shaped
value. Exceptions are **not** added.

| Class | Examples | Behaviour |
|---|---|---|
| Programming error | wrong type (already a compile error), out-of-range index, missing map key, division by zero, arity mismatch | **aborts** with a located diagnostic. Not catchable, not a `Result`. |
| Recoverable failure | file missing, permission denied, connection refused, timeout, malformed JSON from a peer, bridge call rejected | returned as a **failed `Result`** with a stable machine-readable code and a human message. |

**Consequence:** the language needs a `Result` representation before any I/O
module ships; its syntax and propagation must be specified in a separate design
document (§14, open item 1) and approved before Phase 3.

### Decision 2 — Concurrency: async/await, deferred until after closures

**Decided:** async/await is the intended model; **nothing is implemented yet**.
Function values, closures, capture semantics and their VM representation come
first (§13). The event loop and async model are designed *around* that
representation.

**Consequence:** the `async` module stays reserved and failing; no keyword is
reserved in the parser until the design exists.

### Decision 3 — Desktop: keep tkinter, add a toolkit-independent interface

**Decided:** tkinter remains the desktop backend; the work is to define a
toolkit-independent UI interface that the current renderer implements, so a native
backend can be added later without changing application logic.

**Explicitly not decided:** rewriting the UI system. `docs/UI.md`'s rule stands —
a target is "supported" only when an acceptance test renders it.

### Decision 4 — WASM: a prototype before a commitment

**Decided:** WASM is a proposed strategy; a feasibility prototype must prove that
the existing compiler representation can target WASM while preserving semantics,
and it must be compared against alternatives with measured numbers before any full
backend is approved.

**Consequence:** Phase 3 splits into 3a (prototype + report) and 3b (backend,
after review).

### Decision 5 — Packages: lockfile, pinned commits, checksums; no registry

**Decided:** lockfile, pinned Git commits, checksums. No public registry.
Deterministic resolution and integrity verification first.

### Decision 6 — Minimum CPython version: unchanged

**Decided:** the declared minimum stays as published. Raising it requires a
compatibility audit, test evidence and a documented reason.

### Decision 7 — Rust VM: designed now, approved separately *(new in 1.2)*

**Decided:** a Rust VM is the intended long-term runtime; an immediate full
rewrite is **not** approved. The migration is designed in §16 as a
consume-the-existing-bytecode strategy with the Python VM as a permanent semantic
reference. No Rust code may be written until §16 is approved on its own.

---

## 13. First-class functions and closures (Phase 2 design)

This section is the gate for Phase 2. It is a **design**: no syntax here has been
added to the parser, and every rule below must be accepted or amended before code
is written.

The goal is narrow: make a Silica function a value that can be stored, passed,
returned and called — with captures that behave the way a reader expects, and
without changing what any existing program does. The design is
**runtime-neutral**: the Python VM and the planned Rust VM (§16) must implement
the same observable rules.

### 13.1 Function values and calling conventions

**Value form.** A function value carries code, an arity, and a capture list.
Named functions declared with `sfn` remain callable by name, unchanged. Used as a
value, a named function produces a closure with **zero captures** — a "static
function value", the cheap case.

**Type syntax (proposed).**

```
Fn(Int, String) -> Bool
Fn() -> Unit
```

`Fn` is a built-in type form, parsed only in type position, so it cannot collide
with an identifier. It is deliberately not `Fn<T>`: function types are not generic
parameters, and reusing that syntax would make `Fn(Int) -> Int` ambiguous with
type arguments.

**Calling.** Two call forms, both explicit in bytecode:

| Form | Source | Opcode |
|---|---|---|
| by name | `add(1, 2)` where `add` is an `sfn` | `CALL` (unchanged) |
| through a value | `f(1, 2)` where `f` holds a function value | `CALL_VALUE` (new) |

The checker resolves which form applies from the binding's type, so the compiler
never guesses. `CALL_VALUE` pops the callee and arguments and checks the arity
against the closure's recorded arity; a mismatch is a *runtime* error only when
the value arrived through `Any`, otherwise it is a compile error.

**Calling convention.** Unchanged frame layout: `n_locals` slots, arguments in the
first `arity` slots. A closure call pushes a frame whose locals begin with its
captured cells, so a closure body addresses captures exactly like locals.

### 13.2 Closure capture semantics

**Lexical, static, decided by the compiler.** A nested function captures the free
variables it references; the set is computed by free-variable analysis in the
checker and recorded on the chunk. There is no dynamic scoping, no implicit
`self`, and no way for a function to reach a binding it did not name.

| Captured binding | Captured as | Mutation visible in the enclosing scope |
|---|---|---|
| `let x: Int = 1` | a shared cell | **yes** — both see the same cell |
| `const x: Int = 1` | the value itself | not applicable; `const` cannot be reassigned |
| parameter `x: Int` | a shared cell | yes, if the parameter is reassigned |
| `struct`/`class` value | the reference | field mutation is visible (identity), regardless of `let`/`const` |

**Loop bodies create a fresh binding per iteration.** `per` and `tant` bodies that
declare a binding capture *that iteration's* cell, so a list of closures built in
a loop captures `1, 2, 3` and not `3, 3, 3`. This is specified so it cannot be
decided by accident, and it is test #3 in §13.9.

**What is not captured.** Globals are not captured — they are looked up at call
time through `LOAD_GLOBAL`, so a closure always sees the current global.

### 13.3 Mutable and immutable captures

- A mutable capture is a **shared cell**: writing inside the closure writes the
  enclosing binding. Reads and writes inside the closure are ordinary
  `LOAD_LOCAL`/`STORE_LOCAL` against the cell slot.
- An immutable capture is **copied** at closure creation. This is the observable
  rule: a `const` read inside a closure cannot change because of something the
  enclosing function did later.
- `const` freezing extends to captures: capturing a `const` struct does not
  unfreeze it.
- **No capture-by-copy for `let`.** Copying mutable captures would make two
  closures over the same variable disagree, which is worse than sharing.

### 13.4 Lifetime and memory management

- **Lifetime is reachability.** A closure keeps its captured cells alive for as
  long as the closure is reachable; there is no `free`, no `release`, and no
  lifetime annotation in the language.
- **Escaping closures are supported**: returning a closure that captures a local
  keeps that cell alive after the defining frame is gone. This is required for
  handlers and is why captures are cells rather than frame slots.
- **No finalisers.** A closure cannot run code when it is collected.
- **The mechanism is not part of the language.** On the Python VM it is CPython
  reference counting plus the cycle collector; on the Rust VM it is the arena and
  collector in §13.10. Programs may not depend on either.

### 13.5 VM representation

Proposed shapes (names illustrative; the invariants are the commitment):

```
Closure
  code_index : Int        # index into the chunk's function table
  arity      : Int
  captures   : List[Cell] # one entry per capture descriptor
  name       : String     # for diagnostics only

Cell
  value      : Any        # one slot, shared by every closure that captured it
```

- **Frame layout stays flat.** A function with captured locals allocates those
  slots as cells at entry, decided at compile time; uncaptured locals stay plain
  slots. The verifier enforces that a slot is never used both ways in one
  function.
- **New opcodes** (`FORMAT_MINOR` bump):
  - `MAKE_CLOSURE` — code index, then capture descriptors (slot index or upvalue
    index per capture).
  - `CALL_VALUE` — argument count.
  - `LOAD_UPVALUE` / `STORE_UPVALUE` — explicit upvalue opcodes, so the verifier
    can check capture indices against the recorded capture list instead of
    trusting a flag.
- **Two implementations, one semantics.** The Python VM represents a cell as a
  one-slot object; the Rust VM represents it as an index into a cell arena
  (§13.10). Neither representation is observable: no Silica program can take the
  address of a cell, compare two cells, or observe collection.
- **No host pointers.** A `Closure` holds an index into the chunk, never a Python
  callable or a Rust function pointer. This keeps bytecode portable and keeps
  §4.5's promise to a future freestanding runtime.
- **Serialization.** Closures are runtime values and are **not** constants: the
  constant pool records the *code* of nested functions and their capture
  descriptors, never a live closure (§13.10.7).

### 13.6 Type checking

- **Function types are checked, not erased**: `Fn(Int) -> Int` is a distinct type.
- **Arity is part of the type**; `Fn(Int, Int) -> Int` and `Fn(Int) -> Int` do not
  unify.
- **Named functions used as values take their declared signature.** An `sfn` with
  an unannotated parameter yields `Any` for that position, consistent with
  existing inference.
- **Invariance, matching generics.** `Fn(Any) -> Unit` is not a supertype of
  `Fn(Int) -> Unit`.
- **`Any` still exists.** Assigning a function value to `Any` loses the signature;
  the call is then checked at runtime, with a located diagnostic.
- **Capture analysis is a checker responsibility.** A closure referencing a
  variable not in scope is a compile error naming the variable; a closure that
  captures nothing is not boxed.

### 13.7 Serialization restrictions

| Situation | Rule |
|---|---|
| Closure as a `.sbc` constant | **forbidden** — closures are runtime values only |
| Closure through `json` | **refused** with a named error |
| Closure across any bridge | **refused** — `python.call` and every future bridge reject function values; no handle is minted for one |
| Closure stored in a struct field | **allowed**; the struct then cannot be JSON-serialised or bridged |
| Closure printed with `sprint` | **allowed**, prints `<fn name>` — stable, documented text |
| Closure compared with `==` | **identity only**; no structural equality, no ordering |
| Closure reconstructed from text | **no such operation**; there is no `eval` and none is planned |

### 13.8 Compatibility with existing named functions

- **`sfn` declarations are unchanged** — same syntax, same semantics, same
  bytecode (`CALL` by name).
- **Name-based handlers keep working.** `gui.on_click(button, "handle_click")`
  and the TUI equivalents stay exactly as they are; accepting a function value is
  an **added** form.
- **No existing program changes meaning.** The checker only gains the ability to
  accept programs it previously rejected. `tests/test_compat_093.py` is the guard.
- **`type_of` reports `Fn`** for a function value — new output only for values
  that could not exist before.
- **Formatter round-trip.** `silica fmt` must print function types and closures
  and re-parse to the same AST.

### 13.9 Regression tests

Each row is a test in `tests/test_closures.py` unless noted.

| # | Case | Expected |
|---|---|---|
| 1 | closure captures a `let` and mutates it | enclosing scope observes the write |
| 2 | closure captures a `const` | value copied; later enclosing mutation impossible by construction |
| 3 | **closures built in a loop capture per-iteration bindings** | three closures return `1, 2, 3` |
| 4 | closure escapes its defining function | captures remain alive and readable |
| 5 | two closures capture the same `let` | both observe each other's writes |
| 6 | recursion through a function value | terminates, same result as the named form |
| 7 | arity mismatch through a typed `Fn` | compile error naming the arity |
| 8 | arity mismatch through `Any` | runtime error with a located diagnostic |
| 9 | passing the wrong `Fn` type | compile error |
| 10 | closure stored in a struct field | readable and callable; `json` refuses it |
| 11 | `sprint` of a closure | prints `<fn name>` |
| 12 | `==` on two closures | identity semantics, not structural |
| 13 | `.sbc` round-trip of a program with closures | identical output before and after reload |
| 14 | verifier rejects a hand-built `CALL_VALUE` with a bad capture index | rejected before execution |
| 15 | `silica fmt` round-trip on closures and function types | byte-identical AST |
| 16 | named handlers in `examples/gui_demo.sc` | unchanged behaviour (existing test) |
| 17 | **self-capturing cycle**: a closure stored in a cell it captures | collected; no leak; program still exits 0 (§13.10.5) |
| 18 | **dropped closure releases its cells** | under `SILICA_GC_STRESS=1`, the cell count returns to baseline |
| 19 | full suite on 3.9 / 3.11 / 3.12 | green, including `test_compat_093.py` |

### 13.10 Memory management without CPython

The closure design cannot lean on CPython's collector, because the target runtime
is Rust (§16). This subsection answers the eight questions raised in review and is
the part that must be right before Phase 2 starts.

**13.10.1 Mutable captures as shared cells.** A cell is a one-slot indirection
that both the closure and the enclosing scope reference. In the Python VM it is a
small object with a `value` attribute. In the Rust VM it is a `CellId(u32)` index
into a `Vec<CellSlot>` owned by the heap — **not** an `Rc<RefCell<Value>>`.
Sharing is by index, so two closures over the same variable hold the same
`CellId`, and no reference count is involved.

**13.10.2 Immutable captures.** A `const` capture is a **copy of the `Value`**
stored directly in the closure's capture vector, not a cell. For struct and class
values the copied `Value` is a reference to the same object (identity preserved),
so copying is cheap and does not duplicate the object graph.

**13.10.3 Loop iteration bindings.** The compiler emits `NEW_CELL` at the top of a
loop body for every binding that is captured, and it runs **once per iteration**.
Each iteration therefore allocates a fresh `CellId`; a closure created in that
iteration captures that id and keeps it after the loop advances. The Python VM
does the same thing with a fresh cell object per iteration. This is why the
`1, 2, 3` case in §13.9 is a language rule and not an implementation detail.

**13.10.4 Retention and release.** Nothing is retained or released explicitly:

- a closure is reachable if a value, a frame slot, a global, or a host root
  reaches it;
- a cell is reachable if a closure captures it, or a frame slot holds it;
- when a closure becomes unreachable, its capture vector becomes unreachable with
  it, and the cells it held are collected in the same sweep.

**13.10.5 Cycle handling — and why `Rc`/`Arc` is not the answer.** The reviewer's
warning is correct and is the reason this subsection exists. The object graph
contains cycles that reference counting cannot break:

```
closure ──captures──▶ cell ──holds──▶ closure        (self-capturing closure)
closure ──captures──▶ cell ──holds──▶ list ──holds──▶ closure
```

`Rc<T>` cannot collect either: each side keeps the other's strong count at ≥1, so
the memory is never freed. `Arc` adds atomics and changes nothing about cycles.
`Rc<RefCell<..>>` adds a second failure mode — a borrow conflict becomes a
*panic at run time*, which is unacceptable in a language whose error model says
programming errors abort with a diagnostic, not a crash in the host.

The Rust VM therefore keeps the value graph **free of reference counting**:

```
Value = Unit | Bool(bool) | Int(i64) | Float(f64) | Str(StrId)
      | List(ObjId) | Map(ObjId) | Instance(ObjId) | Closure(ObjId)

Heap  = { objects: Vec<Option<Object>>, cells: Vec<Option<Value>>,
          strings: StrArena, free_objects: Vec<ObjId>, free_cells: Vec<CellId> }

Object = List(Vec<Value>) | Map(IndexMap<Key, Value>)
       | Instance { type_id: u32, fields: Vec<Value> }
       | Closure { fn_index: u32, captures: Vec<Capture> }
Capture = Cell(CellId) | Value(Value)
```

Every reference is an index into an arena the VM owns. **Collection is
mark-and-sweep**, not reference counting:

1. **Roots**: global slots, every live frame's locals and operand stack, the value
   in flight, and host-held roots registered by a bridge (a Silica handle held by
   the Python interop worker is a root, and must be declared as one).
2. **Mark**: trace `Value` → `ObjId`/`CellId` → children, with an explicit work
   list (no recursion, so a deep list cannot blow the Rust stack).
3. **Sweep**: drop unmarked objects and cells, return their ids to the free lists.

Cycles are collected by construction: reachability from roots is what decides
liveness, so a self-capturing closure that nothing else references is unreachable
and is freed.

**Why mark-sweep and not trial deletion (Bacon–Rajan).** Trial deletion is the
other standard answer and is also correct, but it needs a write barrier, a
candidate buffer and a second pass per collection; mark-sweep needs a root set and
a free list. For a first correct implementation, mark-sweep has fewer moving parts
and fewer invariants to violate. Trial deletion remains a legitimate later
optimisation for a young generation, recorded in §14.

**Pause behaviour.** Collection is stop-the-world and threshold-triggered
(allocated-bytes or object-count since the last collection). The thresholds are
tunable, and `SILICA_GC_STRESS=1` collects on every allocation so that the test
suite can catch a missing root instead of waiting for a rare crash.

**13.10.6 Does the lifetime model work without CPython?** Yes, and the reason is
structural rather than hopeful:

- no `Value` contains a raw pointer, a `Box`, an `Rc` or a host handle — only
  plain scalars and arena indices;
- ownership of every object is unambiguous: the `Heap` owns it, and nothing else
  can free it;
- liveness is defined by roots, and the root set is enumerable at every point
  where the VM can pause (between instructions, never mid-opcode);
- the one thing that must be added for a host embedding is root registration:
  anything a bridge holds across a call must be registered before the next
  collection. That is an API requirement on the bridge, not a language rule, and
  §16.7 tests it.

**13.10.7 Runtime closures versus compiled function definitions in `.sbc`.** They
are different things and must not be confused:

| | Function definition (in `.sbc`) | Closure (at run time) |
|---|---|---|
| What it is | code + arity + `n_locals` + `max_stack` + capture *descriptors* + line table | an object pairing a function index with a capture vector |
| Persisted | yes, in the chunk's function table and constant pool | never |
| Created by | the compiler, once per `sfn` | `MAKE_CLOSURE`, at the point the expression executes |
| Contains | no values | `CellId`s and copied `Value`s |
| Can be equal-compared | n/a | identity only |

A capture *descriptor* says how many captures there are and whether each is a cell
or a copy; it is metadata, not data. The verifier checks that a `LOAD_UPVALUE`
index is inside the declared capture count, so a hand-edited `.sbc` cannot read
past the capture vector.

**13.10.8 Rejection at serialization and bridge boundaries.** Three enforcement
points, in order of defence:

1. **Bytecode writer**: there is no opcode that emits a closure into the constant
   pool, and the verifier rejects a constant-pool entry of a function-value kind.
2. **Data serializers**: the `json` encoder has no case for `Fn` and returns a
   named error rather than writing a placeholder.
3. **Bridge marshaller**: the value-to-JSON mapping in `INTEROPERABILITY.md` §2
   has no entry for `Fn`; the marshaller rejects the value **before** a frame is
   framed, so nothing reaches the worker, and no handle is minted for a closure.

The consequence is stated as a rule, not an implementation detail: **a closure
cannot cross a trust boundary in either direction.**

---

## 14. Unresolved trade-offs

1. **`Result` syntax and propagation.** Needed before Phase 3. Options: a
   struct-shaped `Result` with `ok`/`error` fields handled by `si` (no new
   syntax), versus a dedicated binding form. Recommendation: the struct first.
2. **Capture-by-cell versus capture-by-copy for `let`.** Decided as shared cell
   (§13.2). Reversible only with a documented breaking change.
3. **GC strategy over time.** Mark-sweep is proposed (§13.10.5); trial deletion or
   a nursery generation are later options if pauses become visible. The *language*
   semantics do not change either way.
4. **Function type ergonomics.** `Fn(Int) -> Int` is verbose in parameter lists. A
   type alias form is attractive and is not in this design.
5. **Closures in `const` bindings.** Recommendation: allow, and freeze the
   binding, not the captured cells.
6. **Whether async/await needs `Fn` to be thread-safe.** On a single-threaded
   event loop, probably not; if green threads ever return, this becomes real.
7. **Rust VM: whether natives move to Rust at all.** §16.5 proposes keeping
   platform natives in Python indefinitely and moving only pure ones. The
   alternative — porting everything — is faster in theory and unmaintainable in
   practice.

---

## 15. What this document does not claim

- That Silica is production-ready, fast, or secure against a hostile host.
- That any phase after Phase 0 is implemented.
- That WASM is the chosen backend — decision 4 requires a prototype first.
- That async/await exists, or will ship in any particular release.
- **That a Rust VM will be faster.** It is expected to be, and it will be
  measured (§16.9), but no ratio is promised here.
- That the Rust VM has been approved — §16 is a design for separate review.
- That closures behave as described today — §13 is a design awaiting approval.
- That Android or system software will be delivered on any date.
- That the current VM is a sandbox.

The objective is a working, verifiable foundation — not APIs that look finished.

---

## 16. Rust VM migration

**Status:** design for review. No Rust code exists, and none may be written until
this section is approved on its own terms.

The constraint that shapes everything below: **the compiler stays Python for now,
and the Rust VM consumes the bytecode the existing compiler already produces.**
That is what makes the migration incremental and testable — there is always an
oracle to compare against.

### 16.1 The Python VM is the semantic reference implementation, permanently

- It defines what a program *means*: opcode behaviour, evaluation order, error
  text, printing format, iteration order.
- It is never deleted. `--vm=python` remains available after the Rust VM becomes
  the default, because a reference implementation that no longer ships cannot be
  used to adjudicate a disputed case.
- It is the oracle for every differential test (§16.7). When the two disagree, the
  Python VM is right until a written decision says otherwise — and that decision
  is recorded in this document, not in a commit message.

### 16.2 The stable internal contract

This is what the Rust VM must implement. It is an internal contract: not a
compatibility promise to users (the *language* is that), but the interface between
two implementations.

**Container.** `.sbc`: magic `SILICABC`, `FORMAT_MAJOR` 1, `FORMAT_MINOR` 0,
CRC-32 over the payload, constant pool, per-function line table, verified before
execution.

**Function record** (`docs/BYTECODE.md`): `name`, `arity`, `n_locals`,
`max_stack`, `ret_type`, `code`, `lines`.

**Values.** `Unit`, `Bool`, `Int` (64-bit signed, **wraps on overflow**), `Float`
(f64), `String`, `List`, `Map`, `Instance` (struct or class). Numbers follow
Python's rules: `Int / Int` truncates toward zero, `%` keeps the dividend's sign,
division by zero is a runtime error.

**Frames.** `fn`, `index`, `ip`, `locals` (`n_locals` slots), `stack`
(`max_stack` slots). Explicit frames, so recursion depth is bounded by
`max_frames` (4096), not by the host stack.

**Opcode set — 43 instructions.** The Rust VM implements exactly this table; the
stack-effect column is the verifier's contract and the Rust decoder must enforce
it identically.

| Op | Name | Operands | Stack |
|---|---|---|---|
| 0x00 | `NOP` | — | 0 → 0 |
| 0x01 | `CONST` | `u` pool index | 0 → 1 |
| 0x02 | `UNIT` | — | 0 → 1 |
| 0x03 | `TRUE` | — | 0 → 1 |
| 0x04 | `FALSE` | — | 0 → 1 |
| 0x05 | `LOAD_LOCAL` | `u` slot | 0 → 1 |
| 0x06 | `STORE_LOCAL` | `u` slot | 1 → 0 |
| 0x07 | `LOAD_GLOBAL` | `u` slot | 0 → 1 |
| 0x08 | `STORE_GLOBAL` | `u` slot | 1 → 0 |
| 0x09 | `POP` | — | 1 → 0 |
| 0x0A–0x0E | `ADD` `SUB` `MUL` `DIV` `MOD` | — | 2 → 1 |
| 0x0F | `NEG` | — | 1 → 1 |
| 0x10 | `NOT` | — | 1 → 1 |
| 0x11–0x16 | `EQ` `NE` `LT` `LE` `GT` `GE` | — | 2 → 1 |
| 0x17 | `JUMP` | `j` target | 0 → 0 |
| 0x18 | `JUMP_IF_FALSE` | `j` target | 1 → 0 |
| 0x19 | `CALL` | `u` fn, `u` argc | argc → 1 |
| 0x1A | `CALL_NATIVE` | `u` module, `u` name, `u` argc | argc → 1 |
| 0x1B | `RET` | — | 1 → 0 |
| 0x1C | `PRINT` | — | 1 → 0 |
| 0x1D | `DIT` | — | 1 → 0 |
| 0x1E | `MAKE_LIST` | `u` n | n → 1 |
| 0x1F | `MAKE_MAP` | `u` n | 2n → 1 |
| 0x20 | `INDEX_GET` | — | 2 → 1 |
| 0x21 | `LEN` | — | 1 → 1 |
| 0x22 | `ITER_START` | — | 1 → 1 |
| 0x23 | `ITER_NEXT` | `j` exit | 1 → 1 |
| 0x24 | `HALT_OK` | — | 0 → 0 |
| 0x25 | `HALT_POP` | — | 1 → 0 |
| 0x26 | `MAKE_STRUCT` | `u` type, `u` n | n → 1 |
| 0x27 | `GET_FIELD` | `u` field | 1 → 1 |
| 0x28 | `SET_FIELD` | `u` field | 2 → 0 |
| 0x29 | `FREEZE` | — | 0 → 0 (peeks) |
| 0x2A | `CALL_METHOD` | `u` name, `u` argc | argc+1 → 1 |

**Error semantics.** Every diagnostic carries `file`, `line`, `col`, a message and
an optional hint, rendered as:

```
file.sc:3:5: type error: cannot assign to 'x': it is a constant
  hint: declare it with 'let' instead of 'const'
```

Runtime errors abort the program; there is no unwinding (§12, decision 1).
**The Rust VM must reproduce these strings byte-for-byte** — they are part of the
contract, and the differential suite compares them exactly.

### 16.3 Parity hazards — measured, not assumed

These are the places a second implementation silently diverges. Every value in
the "Silica behaviour" column below was **measured by running the reference VM**
on 2026-11-03, not inferred from the source, and each is pinned by an executable
case in `tests/parity/` (`tests/test_parity_contract.py`).

| Hazard | Silica behaviour (measured) | Pinned by | What Rust does by default |
|---|---|---|---|
| Int overflow | `9223372036854775807 + 1` → `-9223372036854775808`; `max * 2` → `-2` — **wraps, 64-bit signed** | `int_overflow_add` | `+` panics in debug, wraps in release |
| Int literal range | `9223372036854775808` is a **compile error**, not a wrap: `type error: integer literal … does not fit in Int (64-bit)` with a range hint | `int_literal_range` | `i64` literal overflow is a compile error too, but the message differs |
| Division | `-7 / 2` → `-3`, `7 / -2` → `-3` — **truncates toward zero** | `int_division` | `i64::div` truncates — matches |
| Modulo | `-7 % 2` → `-1`, `7 % -2` → `1` — **sign follows the dividend (C-style)**; this is **not** Python's `%` | `int_division` | Rust `%` matches; a Python-shaped implementation would not |
| Conversions | `int("42")` → 42, `int(3.9)` → 3, `int(-3.9)` → -3 (truncation), `float(2)` → 2.0, `str(oui)` → `oui`, `int(oui)` → runtime error | `int_conversions` | each needs an explicit case |
| String length | `len("héllo")` → **5**, `len("😀")` → **1**, `len("e" + U+0301)` → **2** — code points, no grapheme clustering | `unicode_len_index` | `String::len()` is **bytes** |
| String index | `"héllo"[1]` → `é`, `"😀"[0]` → `😀`, `-1` → runtime error `string index -1 out of range (length 3)` | `unicode_len_index`, `unicode_negative_index` | byte indexing; negative indices would panic or wrap |
| Slicing | **does not exist** — `s[1:3]` is `parse error: expected ']' but found ':'` | `unicode_slicing` | n/a |
| Float printing | `0.1 + 0.2` → `0.30000000000000004`; `1e300` → `1e+300`; `1e-7` → `1e-07`; `1e16` → `1e+16`; `1/3.0` → `0.3333333333333333` — Python shortest round-trip, **two-digit exponents** | `float_format` | `Display` differs in exponent formatting and precision |
| Negative zero | `-0.0` prints `-0.0`; `0.0 - 0.0` in variables prints `0.0` | `float_negative_zero` | same, but only if constants are keyed by bits (see §16.13.5) |
| Special floats | `float("inf")` → `inf`, `float("-inf")` → `-inf`, `float("nan")` → `nan`; `inf + 1.0` → `inf`; `inf - inf` → `nan` | `float_specials` | same text, but they are only reachable through `float(String)` |
| Float division by zero | **runtime error** `division by zero` with a hint — never `inf` | `float_div_by_zero` | IEEE would give `inf`; Silica does not |
| Map order | insertion order in printing, `keys()` and `per` iteration | `map_order` | `HashMap` is unordered |
| Map indexing | `m["k"] = v` is a **parse error** (no index assignment); a missing key is a runtime error | `map_missing_key` | n/a |

The consequence for R1 is stated plainly: **a straightforward port fails at least
eight of these**, and the corpus is the only thing that will catch it.


### 16.4 Rust crate structure

Nine crates, each with one job and no circular dependencies:

| Crate | Responsibility | Depends on |
|---|---|---|
| `silica-value` | `Value`, `Object`, `Key`, string interning, printing/formatting (the §16.3 parity routines) | — |
| `silica-bytecode` | `.sbc` decode, CRC-32, operand schemas, the verifier (port of `verify_chunk`) | `silica-value` |
| `silica-heap` | arenas for objects and cells, free lists, mark-sweep collector, root registration (§13.10.5) | `silica-value` |
| `silica-frames` | operand stack, call frames, `max_frames` enforcement | `silica-value` |
| `silica-exec` | the dispatch loop: one function per opcode, no `unsafe` | `silica-bytecode`, `silica-frames`, `silica-heap` |
| `silica-fn` | closures, cells, capture vectors, `MAKE_CLOSURE`/`CALL_VALUE` semantics | `silica-heap`, `silica-value` |
| `silica-native` | native-function ABI, registry, signature metadata, **the capability choke point** (§16.6) | `silica-value`, `silica-caps` |
| `silica-caps` | capability set, path containment (port of the Python rules), deny-by-default | — |
| `silica-runtime` | host embedding: CLI driver, `.sbc` loading, PyO3 bridge to the Python natives, C ABI | all of the above |

`silica-exec` must not depend on `silica-native` directly: it calls through a
trait, so a host can substitute natives (the Python bridge in R1, Rust natives in
R2) without touching the loop.

### 16.5 Standard library and Python interop

**R1 (first Rust VM): every native stays in Python.** The Rust VM embeds CPython
via PyO3 and calls the *existing* `natives.py` registry. Nothing is reimplemented,
so the standard library cannot drift. The cost is that native calls are slower —
which is acceptable because the win being measured is in the dispatch loop.

**R2: pure natives move to Rust, one module at a time**, in this order:
`math` → `string` → `collections` → `path` → `time` → `random` → `json`. Each move
requires its module's tests plus the differential suite to pass.

**Never moves (initially):** `ui`, `tui`, `gui`, `speech`, `voice` — they are
host-bound by definition. `python` interop stays Python because it *is* Python.
`fs` moves last, because the capability enforcement path is the one place a
reimplementation could weaken a security boundary (§16.6).

**Python interop is preserved unchanged** in every stage: the worker process,
`SIW1` framing and the handle registry are host-side concerns. A Rust VM runs the
same worker and speaks the same frames; the Silica-visible module does not change.

### 16.6 Capability enforcement cannot be bypassed

The rule: **a capability check is a property of native dispatch, not of the VM
implementation.** Four mechanisms make that true rather than aspirational:

1. **One choke point.** `silica-native` exposes exactly one way to call a native:
   `invoke(caps, module, name, args)`. It checks the module's declared capability
   before dispatch. The registry is private; `silica-exec` has no path to a native
   function pointer.
2. **Immutable grants.** `CapabilitySet` is constructed once, before execution, and
   passed as `&CapabilitySet`. No native receives `&mut` access to it, so a native
   cannot grant itself or another module anything.
3. **No `unsafe` in the dispatch path.** `silica-native` and `silica-caps` are
   `#![forbid(unsafe_code)]`. A check cannot be optimised away because it is
   ordinary safe code on the call path.
4. **Path containment ported once, tested by differential.** `is_within` and the
   component-prefix comparison are reimplemented in `silica-caps` and compared
   against the Python implementation on a corpus of traversal cases (`..`,
   absolute paths, NUL bytes, symlinks that must *not* be resolved).

**Acceptance for the capability claim:** a Rust VM constructed without `fs.read`
returns the documented capability error for `fs.read_text` — not a panic, not a
silently empty string — and the differential suite includes that case for every
capability-gated native.

### 16.7 Differential testing

The strategy is one property: **the same program produces the same observable
result on both VMs.**

| Dimension | What is compared |
|---|---|
| Corpus | `tests/silica/*.sc`, `examples/*.sc`, `benchmarks/silica/*.sc`, plus generated programs |
| Output | stdout, byte-for-byte |
| Diagnostics | stderr, byte-for-byte, including the `hint:` line |
| Exit code | exact |
| Side effects | files created, with hashes; files *not* created when a capability is denied |
| Bytecode | the Rust VM must consume the **unmodified** `.sbc` produced by the Python compiler — no recompilation step |
| Errors of interest | capability denials, division by zero, missing map key, arity through `Any`, GC stress runs |

Runner: `tools/differential.py` (design only) executes each case twice and reports
the first divergence with a minimal reproducer. CI runs three jobs: Python VM only,
Rust VM only, and both-with-comparison; the third is the gate.

**GC-specific differential:** with `SILICA_GC_STRESS=1` on the Rust VM, every case
must still match. This is what catches a missing root — the failure mode that
otherwise appears as a rare, unreproducible corruption.

### 16.8 Gradual migration, and what stays working

| Guarantee | How |
|---|---|
| `silica` CLI unchanged | `--vm=python` or `--vm=rust` selects the engine; the default stays `python` until R3 |
| `.sc` syntax unchanged | the front end is not rewritten in this plan |
| `.sbc` compatibility | the Rust VM reads format 1.0 as-is; no format change is required or allowed by this section |
| Package unchanged | the pure-Python wheel remains the default install; a Rust build is an **optional** wheel (`silica-vm-rust`, abi3), never a new required dependency |
| Tests unchanged | the existing suite runs against both VMs; `test_compat_093.py` is the compatibility guard |
| Reference VM retained | `--vm=python` stays available permanently (§16.1) |

**Install story.** `pip install silica-lang` keeps working with no compiler. A user
who wants the fast VM installs `silica-lang[rust]`, which pulls the prebuilt
extension for their platform. If the extension is missing or fails to load, the CLI
falls back to the Python VM with a warning — never a hard failure.

### 16.9 Benchmarks, and no promises

- Reuse `benchmarks/bench.py`; add `--vm` so the same corpus runs on both.
- Report, per workload: median of 3 runs, absolute times, and the ratio
  `python_vm / rust_vm`. Record the machine.
- Publish the table in `docs/PERFORMANCE.md` before any claim is made anywhere
  else.
- **Decision threshold, deliberately unset:** to become the default, the Rust VM
  must (a) be differential-green, (b) be no slower on any workload, and (c) beat
  an improvement factor that will be fixed *after* the first honest measurement —
  not guessed now. If the measured speedup does not justify the maintenance cost,
  the recommendation is to stop at R1 and keep the Rust VM as an optional engine.
- **The R1 report must contain four numbers, not one:** measured performance
  (§16.14 row 9), build size (row 10), bridge overhead against the 2.2 µs baseline
  (row 11), and maintenance cost (row 13). A speedup quoted without the other
  three is not a result.

### 16.10 What moves first, and what stays Python

| Component | R1 | R2 | R3+ | Why |
|---|---|---|---|---|
| Dispatch loop, frames, operand stack | **Rust** | Rust | Rust | the actual cost centre |
| Bytecode decode + verify | **Rust** | Rust | Rust | must read the same `.sbc` |
| Heap, cells, closures | **Rust** | Rust | Rust | §13.10 |
| `math`, `string`, `collections`, `path`, `time`, `random`, `json` | Python | **Rust** | Rust | pure, easy to compare |
| `fs` | Python | Python | **Rust** | capability boundary moves last |
| `ui`, `tui`, `gui`, `speech`, `voice` | Python | Python | Python | host-bound |
| `python` interop | Python | Python | Python | it is Python |
| Lexer, parser, checker, compiler, formatter | Python | Python | Python | not in scope; rewriting the front end is a separate decision |
| CLI, packaging | Python | Python | Python + optional extension | keeps installs working |

### 16.11 Phases

**R0 — this design.** Gate: approved on its own, separately from §13.

**R1 — read-and-run.** Rust VM executes existing `.sbc`, all natives via PyO3,
`--vm=rust` behind a flag.
*Acceptance:* the fourteen criteria in §16.14, in full. R2 does not begin until
they are met and the report is reviewed.

**R2 — natives in Rust.** Seven pure modules ported, one at a time, each gated by
its own tests plus the differential suite. `fs` still Python.
*Acceptance:* identical results for every ported module; the Python fallback still
passes the full suite; no new required dependency in the default wheel.

**R3 — default.** Rust VM becomes the default when §16.9's threshold is met.
*Acceptance:* the full suite green on both VMs; the Python VM still ships and is
still the oracle; the release notes state the measured numbers and the fallback
behaviour.

**R4 — `fs` and the security path.** `fs` natives move to Rust with the capability
containment ported and differentially tested.
*Acceptance:* the traversal corpus (including symlinks and NUL bytes) matches
Python exactly; a denied capability produces the documented error on both VMs.

**R5 — front end (optional, separately approved).** A Rust lexer/parser/checker.
Not part of this plan; listed so the boundary is explicit.

### 16.12 Rust-specific risks

| Risk | Why it is real | Mitigation |
|---|---|---|
| Silent divergence on formatting | `0.1 + 0.2` and float edge cases | shared formatting corpus of 1,000 doubles, compared |
| Unicode indexing mismatch | bytes versus scalar values | contract term (§16.3) + tests with multi-byte strings |
| Map ordering | `HashMap` is unordered | `IndexMap` everywhere a Map is exposed |
| GC pauses under load | stop-the-world | threshold tuning, stress mode in CI, nursery later (§14.3) |
| Missing roots | the classic GC bug, rare and late | `SILICA_GC_STRESS=1` in CI; root registration is an explicit API |
| PyO3 overhead in R1 makes it look slow | native calls dominate early benchmarks | benchmark R1 separately from R2; judge the loop, not the bridge |
| Two implementations drift over years | the real long-term cost | Python VM stays the oracle; divergence is a bug, not a preference |
| Build complexity for users | optional native wheel | default install stays pure Python; graceful fallback |

### 16.13 Measured contract facts

Everything here was produced by running the reference VM. The commands are given
so each figure can be re-derived, and each fact has a case in `tests/parity/`.

#### 16.13.1 Integers

| Question | Measured answer |
|---|---|
| Width | 64-bit signed; literals must fit or the program does not compile |
| Addition overflow | **wraps** — `9223372036854775807 + 1` → `-9223372036854775808` |
| Multiplication overflow | **wraps** — `9223372036854775807 * 2` → `-2` |
| Division | truncates toward zero: `-7 / 2` → `-3`, `7 / -2` → `-3` |
| Modulo | sign follows the **dividend**: `-7 % 2` → `-1`, `7 % -2` → `1` |
| `int(String)` | decimal only: `int("42")` → `42` |
| `int(Float)` | truncates toward zero: `int(3.9)` → `3`, `int(-3.9)` → `-3` |
| `int(Bool)` | runtime error: `int expects a String, Float or Int, got Bool` |
| `float(Int)` | `2` → `2.0` |

The modulo rule is the one to note: **it is C semantics, not Python's**. A port
that reuses Python's `%` produces `1` where Silica produces `-1`.

#### 16.13.2 Unicode

| Question | Measured answer |
|---|---|
| `len("héllo")` | `5` — code points, not bytes |
| `"héllo"[1]` | `é` |
| Supplementary plane | `len("😀")` → `1`; `"😀"[0]` → `😀` — one code point, not a surrogate pair |
| Combining sequence | `len("e" + U+0301)` → `2`; index 0 → `e`, index 1 → the combining mark — **no grapheme clustering** |
| Slicing | **unsupported**: `s[1:3]` is a parse error (`expected ']' but found ':'`) |
| Negative index | runtime error: `string index -1 out of range (length 3)` |

So Silica follows **Python 3 `str` semantics**: indexing and length are in code
points. Rust must index by `char`, not by byte, and must not normalise or cluster.

#### 16.13.3 Floating point

| Expression | Output |
|---|---|
| `0.1 + 0.2` | `0.30000000000000004` |
| `1e300` | `1e+300` |
| `1e-7` | `1e-07` |
| `1.0e16` | `1e+16` |
| `1.0e17` | `1e+17` |
| `1.0 / 3.0` | `0.3333333333333333` |
| `2.0` | `2.0` — an integral float keeps its `.0` |
| `-0.0` | `-0.0` |
| `0.0 - 0.0` (via variables) | `0.0` |
| `float("inf")`, `float("-inf")`, `float("nan")` | `inf`, `-inf`, `nan` |
| `inf + 1.0` / `inf - inf` | `inf` / `nan` |
| `1.0 / 0.0` | **runtime error** `division by zero` — never `inf` |

Formatting is Python's shortest round-trip representation, with a **two-digit
minimum exponent** (`1e-07`, not `1e-7`). Infinity and NaN are reachable only
through `float(String)`; arithmetic cannot produce them, because division by zero
is an error. A Rust implementation needs one shared formatting routine and a
1,000-double corpus, not `Display`.

#### 16.13.4 Maps

| Question | Measured answer |
|---|---|
| Insertion order | preserved — `{"zebra": 1, "apple": 2, "mango": 3}` prints and iterates in that order |
| `keys(m)` | same order |
| `per k in m` | same order |
| Updating a key | **not expressible**: `m["k"] = v` is a parse error (no index assignment) |
| Missing key | runtime error `map key 'b' not found`, with a `has` hint |

Because there is no index assignment, a map's order is fixed at construction and
cannot be disturbed. Rust still needs an insertion-ordered map, because `HashMap`
would not even reproduce construction order.

#### 16.13.5 A defect found while measuring: float constants were interned by `==`

**Status: fixed** — see §16.13.6. The record below is kept because the reasoning is
why the fix is what it is, and because a future VM implementer needs to know the
shape of the trap.

Measuring §16.13.3 surfaced a real bug in the Python VM:

```
$ silica run negzero.sc            # sprint(-0.0) then sprint(0.0 - 0.0)
-0.0
-0.0                              # wrong: IEEE says 0.0
$ SILICA_NO_OPT=1 silica run negzero.sc
-0.0
0.0                               # correct
```

**Cause.** The optimizer folds `0.0 - 0.0` to the constant `0.0` and interns
constants by equality. Since `0.0 == -0.0` is `True`, both expressions resolve to
the *first* constant inserted, and its sign bit wins. The reverse order shows the
same defect in the other direction.

**Why it matters for this design.** It is exactly the class of bug a second
implementation will either inherit or silently disagree with. The contract cannot
say "match the bug", so:

- the **correct** behaviour is IEEE-754: `-0.0` and `0.0` are distinct values that
  print differently;
- the constant pool must be keyed on the **bit pattern** (`struct.pack(">d", v)` in
  Python, `f64::to_bits` in Rust), not on `==`;
- `tests/parity/float_negative_zero_intern.sc` records the correct expectation and
  is marked `# xfail:`, so the suite stays green today, fails loudly when the
  defect is fixed, and the Rust VM is required to pass it from the start.

This is a **recommended fix to the Python VM** before R1 freezes parity, and it is
the only known divergence between the documented contract and the current
implementation.

#### 16.13.6 The float correction — landed, and the contract is frozen

The defect above is a **Python optimizer bug**, and it was fixed on its own track,
as a separate pull request, before the parity baseline was frozen. Bundling it into the Rust VM work would make the parity baseline move at
the same time as the thing being measured, and there would be no way to tell
which change caused a difference.

**The correction, as landed.** Intern the constant pool by bit pattern, not by
equality — `silica/bytecode.py`, `constant_key`:

```python
tag = constant_tag(value)
if tag == TAG_FLOAT:
    return (tag, struct.pack(">d", value))   # 0.0 and -0.0 are different keys
return (tag, value)
```

The emitted pool now carries both zeros (verified directly: index 0 is `-0.0`,
index 1 is `0.0`), so `.sbc` files round-trip the sign correctly.

**Exact expected output after the fix.** For the program

```silica
sfn main() {
    sprint(-0.0)
    sprint(0.0 - 0.0)
}
```

| | Output |
|---|---|
| today | `-0.0` then `-0.0` |
| after the fix | `-0.0` then `0.0` |
| with `SILICA_NO_OPT=1` today | `-0.0` then `0.0` — already correct, which is how the defect was isolated |

**Compatibility impact — stated precisely, because it is a behaviour change:**

| Question | Answer |
|---|---|
| Do any *values* change? | No. Only the printed sign of a zero. |
| Which programs are affected? | Only those that print a zero-valued float produced by a folded expression, in a compilation unit that also contains a `-0.0` constant inserted first. |
| Does `.sbc` change? | No. The format, the opcodes and the byte layout are untouched; only which pool entry an equal-valued constant resolves to. |
| Does the language change? | No. IEEE-754 already says `-0.0` and `0.0` are distinct values with distinct renderings. |
| Is it observable today? | Yes — `SILICA_NO_OPT=1` already produces the corrected output, so a user can see the discrepancy without waiting for a fix. |
| Release note | A bugfix. No migration, no version bump of the bytecode format. |
| Test impact | `tests/test_optimizer.py` holds three regression tests; the strict xfail marker in `tests/parity/float_negative_zero_intern.sc` was removed **after** the corrected behaviour passed, and the case is now enforced normally. |

**The tests that ship with the correction**, added now so the fix has a target:

| Test | What it asserts |
|---|---|
| `test_the_defect_is_present_and_documented` | today's output (`-0.0`, `-0.0`), so an accidental change is noticed |
| `test_without_folding_the_vm_is_correct` | with `SILICA_NO_OPT=1`, the VM prints `-0.0` then `0.0` — proving the defect is in the folder, not the VM |
| `test_ieee_negative_zero_is_preserved` | marked `@unittest.expectedFailure`: the correct output. Under `python -m unittest` an unexpected success **exits 1**, so the fix fails the suite until the marker is removed — strict xfail without pytest |

**Order of work — done.** The correction landed as its own pull request, the
marker was removed once the corrected behaviour passed, and the suite is green:
1,318 tests, 7 skipped, 0 failures, 0 expected failures. **The corrected parity
contract is now frozen for R1** — the Rust VM must match the corrected output and
the corpus is the arbiter. There is no allowance for the old behaviour.

### 16.14 R1 acceptance criteria

R1 is "read-and-run": the Rust VM executes unmodified `.sbc`, with every native
still in Python through PyO3, behind `--vm=rust`. It is accepted only when every
row below is true and the evidence is attached to the pull request. R2 does not
begin automatically.

| # | Criterion | How it is checked |
|---|---|---|
| 1 | Consumes unmodified `.sbc` | `silica compile x.sc` with the **Python** compiler, then run `x.sbc` on the Rust VM; identical stdout |
| 2 | Parity corpus matches | all 14 cases in `tests/parity/` pass under the Rust VM (13 enforced, 1 `# xfail:` which the Rust VM **must** pass) |
| 3 | Differential corpus matches | `tests/silica/*.sc` + `examples/*.sc`: identical stdout, stderr (including `hint:` lines) and exit code |
| 4 | Capability denials match | every gated native, run without its grant, returns the documented capability error — not a panic, not an empty value |
| 5 | GC stress passes | the whole differential corpus passes with `SILICA_GC_STRESS=1` |
| 6 | No changes to the Python side | `git diff --stat` touches nothing under `silica/`; `.sbc` format unchanged |
| 7 | Not the default | `silica run` still uses the Python VM; `--vm=rust` is required |
| 8 | No security migration | no Rust `fs` native; capability logic untouched |
| 9 | Performance reported | four workloads, median of 3, machine named, ratio against the Python VM |
| 10 | Build size reported | wheel size, binary size, per platform built |
| 11 | Bridge overhead reported | measured PyO3 call cost against the **2.2 µs** Python-VM native-call baseline (below) |
| 12 | Platform constraints stated | OS/architecture actually built and tested, and what was not |
| 13 | Maintenance cost stated | lines of Rust, crates, CI minutes added, who owns them |
| 14 | Scope respected | no closures, no async, no WASM, no new modules |
| 15 | Exit codes and hints compared | the parity runner compares stdout, stderr **including `hint:` lines**, and the exit code; `RunnerSelfTests` proves each of those comparisons actually fires |
| 16 | Strict xfail honoured | the optimizer defect has a dedicated regression test and an `@unittest.expectedFailure` case; an XPASS exits 1 (§16.13.6) |

**The bridge baseline (criterion 11).** Measured on the reference VM, 200,000
iterations of a loop containing one `math.sqrt` call:

| Program | Wall time | Per iteration |
|---|---|---|
| empty program (startup + compile) | 0.322 s | — |
| 200,000 iterations, no native call | 1.856 s | ≈ 7.7 µs |
| 200,000 iterations, one `math.sqrt` each | 2.295 s | ≈ 9.9 µs |

So a native call currently costs ≈ **2.2 µs** through the Python path. R1 must
report its own figure; if a PyO3 call lands in the tens of microseconds, the
bridge — not the dispatch loop — becomes the measurement, and the R1 benchmark
must say so rather than attributing the difference to the VM.

#### 16.14.1 Reporting rule: product failures versus environment failures

An R1 report that counts an un-runnable test as a pass is worthless, so the rule
is explicit. Every suite result is classified into exactly one of three buckets,
and only the first counts as evidence:

| Bucket | Meaning | How it is reported |
|---|---|---|
| **Product** | the test ran and passed or failed on its merits | counted; a failure blocks acceptance |
| **Environment-limited** | the test could not run because a tool, service or filesystem precondition is absent | **not counted as passing**; the report names the missing precondition and the command that demonstrates it |
| **Not run** | deliberately excluded | listed with the reason |

Measured on the reference tree during this review, so an R1 report has a known
baseline to compare against:

| Condition | Result |
|---|---|
| `pytest`, `build`, `setuptools`, `wheel` installed, and a **git working tree** present | **1,318 tests: 1,311 pass, 7 skipped, 0 failures, 0 expected failures** |
| `build` missing | `test_packaging_silica` and `test_install.EndToEndTests` fail with `No module named build` — environment, not product |
| `pytest` missing | `tests.test_interop_python` fails at import (`ModuleNotFoundError: pytest`) — environment |
| tree unpacked from a tarball, no `.git` | `test_packaging_silica…test_the_shipped_tree_passes_every_check` fails with `facts carry no tracked list`, because `tools/package/facts.py` compares against `git ls-files`; initialising a git tree and re-running makes all 44 tests in that file pass — **proven, not assumed** |

The three failures above are the only ones observed, and all three are
environmental. **None of them may appear as a passing test in an R1 report.**

**The recorded baseline.** The command and its output, verbatim, so an R1 report
can be compared against the same measurement rather than a remembered one:

```
$ cd <checkout> && python3 -m unittest discover -s tests -t .
...................................................................
----------------------------------------------------------------------
Ran 1318 tests in 136.746s

OK (skipped=7)
```

Environment for that run: Python 3.12.13, `pytest` 9.2.0, `build`, `setuptools`
and `wheel` installed, and a **git working tree** (264 tracked files) — the last
two conditions matter, per the table above. There are no expected failures: the strict-xfail case for the float intern defect
became a real pass when the defect was fixed (§16.13.6), which is what the marker
was for.

#### 16.14.2 Normative parity statement

> The Rust implementation **must** reproduce the measured behaviour in §16.13
> exactly: 64-bit wrapping integers, truncating division, dividend-signed
> remainder, Unicode code-point indexing and length, Python shortest-round-trip
> float formatting with two-digit exponents, `inf`/`nan` only through
> `float(String)`, division by zero as an error, and insertion-ordered maps.
>
> Where the two implementations disagree, the **Python VM is correct** unless a
> written decision in this document says otherwise. The parity corpus in
> `tests/parity/` is the arbiter, and a disagreement is a bug in the Rust
> implementation until the corpus is amended by review.
>
> The one recorded exception — the float constant-intern defect (§16.13.5) — is
> **closed**: the correction landed (§16.13.6), `-0.0` and `0.0` are now distinct
> pool entries, and the corpus case is enforced. There are no remaining exceptions:
> the Rust implementation must match the corpus exactly, with no allowance for
> defects.

#### 16.14.3 The four R1 measurements: **not measured**

No Rust implementation exists, so none of these has been measured. They are
recorded here as blank fields with the figures they will be compared against, so
that an R1 report cannot quietly substitute an estimate for a measurement.

| Measurement | Status | Baseline it will be compared against |
|---|---|---|
| Performance (four workloads) | **not measured** | reference VM: 46.9×–111.1× slower than CPython (`docs/PERFORMANCE.md`, 2026-10-28) |
| Build size (wheel, binary, per platform) | **not measured** | reference install is a pure-Python wheel with no compiled component |
| Bridge overhead (PyO3 call cost) | **not measured** | ≈2.2 µs per native call through the Python path (§16.14, measured) |
| Maintenance cost (Rust LOC, crates, CI minutes, ownership) | **not measured** | zero Rust in the tree today |

A row stays "not measured" until a run exists to fill it. An estimate, a
projection, or a figure carried over from another project is not a measurement.
