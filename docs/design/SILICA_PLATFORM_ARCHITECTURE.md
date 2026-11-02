# Silica Platform Architecture

**Status:** revised for review — design direction approved, decisions recorded
**Applies to:** Silica 0.10.0 (`sufiyan-sabeel/silica`)
**Document version:** 1.1 · 2026-11-02
**Scope:** how Silica becomes able to build web, desktop, Android, GUI/TUI and
eventually system software — without breaking anything that works today

**Revision history**

| Version | Change |
|---|---|
| 1.0 | Initial audit and proposal; six open decisions raised |
| 1.1 | Decisions 1–6 recorded (§12); first-class functions and closures designed (§13); trade-offs that remain open (§14) |

Nothing in this document is implemented. No closure, async, WASM or platform
backend code may be written until this revision is approved.

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

The single largest blocker is not any platform SDK. It is that **Silica has no
first-class functions**, which makes real event handling, callbacks, and any
async model impossible to express in the language. §13 now specifies that work in
full, because it gates everything after it.

Recommended order: **web → desktop → Android → system**, with the compiler and
runtime work sequenced so that no phase requires a breaking change to the
language.

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

Two existing documents are load-bearing here and are not repeated:
`docs/INTEROPERABILITY.md` (the bridge protocol, handles, C ABI, WASI) and
`docs/SECURITY_MODEL.md` (what the capability checks do and do not guarantee).
This document extends them to platforms; where they already decide something,
they win.

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

43 opcodes. The VM is single-threaded and re-entrant only in the sense that a
native may call back into it (the GUI click handler does exactly that).

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
   *Consequence:* every desktop/Android target needs either an embedded CPython
   or a different execution backend. Embedding is the cheap path; a Rust VM is
   the honest long-term one (`docs/BOOTSTRAP.md`).
2. **Speed: 46.9×–111.1× slower than CPython** on the recorded benchmarks
   (`docs/PERFORMANCE.md`, 2026-10-28). *Consequence:* a browser-side VM written
   in JavaScript/WASM must not be a port of this interpreter if it is to run
   interactive UI; it should compile to something the browser executes natively.
3. **No first-class functions.** Handlers are names. *Consequence:* no
   callbacks, no middleware, no closures over UI state — the single biggest
   blocker for real applications. §13 designs the fix.
4. **Single-threaded, no concurrency primitives.** No threads, no async, no
   timers, no promises. *Consequence:* a server cannot serve two requests; a
   GUI cannot do work without freezing; a network call blocks everything.
5. **No exceptions or error values.** A failure aborts the program. *Consequence:*
   any real I/O layer (HTTP, JNI, file pickers) needs a `Result`-shaped value
   before it can be used by application code. Decision 1 fixes the shape (§12).
6. **No FFI.** There is no way to declare or call a C function. *Consequence:*
   platform APIs are reachable only through a bridge process that someone
   maintains, or through a new `extern` mechanism.
7. **No user packages.** `use` resolves the built-in registry only.
   *Consequence:* no ecosystem; every project copies code.
8. **No byte type.** Binary protocols are represented as hex/URL-safe text.
   *Consequence:* networking and image work pay a conversion tax; acceptable for
   v1, documented in `docs/STANDARD_LIBRARY.md`.
9. **The VM is not a sandbox.** Stated in `docs/SECURITY_MODEL.md` and repeated
   here: capability checks stop a *program* from asking for a file; they do not
   stop a malicious *engine build*, and they are not an OS boundary.
10. **No debugger protocol.** Line tables exist; nothing consumes them.

---

## 4. What "build an application" means per target

For each target: what the developer writes, what the build produces, where the
logic runs, and what has to be true before the target may be called supported.

### 4.1 Web

**Definition of done:** `silica build --target web` produces a directory that a
static host serves, and the application's *logic* runs in the browser.

Two sub-targets, deliberately separate:

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
added later without touching application logic. There is no rewrite in this plan.

### 4.3 Android

**Definition of done:** an APK that installs and runs, with the application logic
in `.sc` files compiled to bytecode, executed by an embedded runtime, and
platform APIs reached over JNI through the same handle protocol.

This is the most expensive target and the least reversible: it requires a JNI
bridge, an Android lifecycle adapter, an asset/manifest pipeline, and an
acceptance test on a real device or emulator in CI. It is scheduled after web
and desktop for exactly that reason.

### 4.4 GUI / TUI

**Definition of done:** an application with persistent state, keyboard and
pointer input, and a lifecycle — not a single rendered frame.

TUI is closest to done: `tui` has 39 natives, polling, focus and selection.
What is missing is a state model that survives redraws and an input loop that
can call back into Silica code — which is §13.

### 4.5 Operating system

**Definition of done:** there isn't one that can be claimed in this decade. A
Silica OS requires a freestanding runtime (no CPython), a memory model without a
host GC, drivers, and a boot path. What this document commits to is only this:
**nothing in phases 1–6 may make an eventual freestanding runtime harder** — no
dependency on CPython object identity in the bytecode, no host-pointer values in
the VM, handles everywhere.

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

The requirement is that application logic stays in Silica files. That holds if:

- the `.sc` sources compile to bytecode for host targets and to a browser
  artifact for the web target — one front end, two back ends;
- platform APIs appear as ordinary Silica modules (`web.*`, `desktop.*`,
  `android.*`) whose natives are bridge calls;
- the language surface does not change per target: the same `sfn main()` runs
  everywhere, and a target that cannot support a module fails at *link* time with
  a named error, not at runtime.

### 5.3 What is explicitly rejected

- **Transpiling Silica to Kotlin/Java/Swift source.** It forks the semantics:
  the checker's guarantees would no longer describe the program that runs.
- **Running the Python VM inside an Android app as the primary path.** It works
  and it is a legitimate *prototype*, but it ships a CPython interpreter, a
  process boundary and a ~50–110× slowdown into a phone. If it is built at all,
  it is a stepping stone behind a flag, documented as such.
- **Exposing Python objects as Silica values.** Already forbidden; restated
  because platform bridges make the temptation larger.

---

## 6. Compiler and runtime evolution

Ordered so each step is additive. **No step may change the meaning of an
existing program**; `tests/test_compat_093.py` and the full suite are the gate.

| Phase | Change | Language impact | Bytecode |
|---|---|---|---|
| P0 | Bridges only; no language change | none | unchanged |
| P1 | Module system + package manifest | new `use pkg` resolution | unchanged |
| P2 | First-class functions, closures (§13) | new: function values, capture rules | **minor bump**: `MAKE_CLOSURE`, `CALL_VALUE` |
| P3 | `Result` error values (decision 1) | new: one value type, no unwinding | minor bump if a new tag is needed |
| P4 | Concurrency — async/await (decision 2) | new keywords | bump |
| P5 | `extern` declarations for C ABI | new declaration form | bump |
| P6 | Alternative back end (WASM, then Rust VM) | none | new target, same semantics |

**Ordering is fixed by decision 2:** function values, closures, capture semantics
and their VM representation come first; the event loop and async model are
designed *on top of* that representation, not before it.

**Bytecode policy.** `FORMAT_MAJOR` changes only for an incompatible layout;
adding opcodes bumps `FORMAT_MINOR` and keeps older readers able to *reject*
rather than misread. Every bump updates `docs/BYTECODE.md`, the verifier's stack
table, and the round-trip tests in the same commit.

---

## 7. Standard-library roadmap

Ordered by what unlocks a target, not by what is interesting.

| Order | Modules | Unlocks | Notes |
|---|---|---|---|
| 1 | `process`, `log` | desktop, CLI tools | `process` behind a capability; no shell interpolation |
| 2 | `net` (TCP), `http` (client) | web.app, desktop | TLS via the host, not hand-rolled |
| 3 | `crypto` (hash, HMAC, AEAD) | auth, tokens | never invent primitives; wrap a vetted library |
| 4 | `async` (decision 2 model) | servers, UI responsiveness | must not leak host futures into Silica |
| 5 | `regex` | text tools | define the dialect before implementing |
| 6 | `test` | CI for user projects | `silica test` exists for `.sc` files; this is the assertion library |
| 7 | `web.*`, `desktop.*`, `android.*` | platform APIs | thin, typed, one native per documented behaviour |
| 8 | `ai` | later | out of scope for the platform phases |

Rule carried over from 0.10.0: a module is either implemented and documented
with tests, or it stays in `PLANNED_MODULES` and fails loudly. There is no third
state.

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
silica test
```

Resolution is deterministic and offline-verifiable: `silica.lock` pins every
dependency to a commit and a checksum, and `silica add --locked` must fail if a
remote commit no longer matches its recorded hash. Artifacts are deterministic:
same inputs, same bytes. `docs/SUPPLY_CHAIN.md` already sets that bar for wheels;
app builds inherit it.

---

## 9. Security model per target

The existing model — deny by default, capability checked at native dispatch, path
containment, opaque handles — carries over unchanged. What changes is *what the
capabilities mean* on each platform:

| Target | Additional capabilities | Explicitly not guaranteed |
|---|---|---|
| Web (static) | none; the page is inert data | nothing about what a browser extension can do |
| Web (WASM) | `web.fetch` for network, per-origin in the host | WASM isolation is the browser's, not ours |
| Desktop | `process.spawn`, `desktop.dialogs`, `desktop.tray` | that a signed app cannot be tampered with after install |
| Android | `android.intent`, `android.permissions`, `android.storage` | that the OS permission model maps 1:1 to ours |
| Any | — | **the VM is not an OS sandbox** (unchanged from `SECURITY_MODEL.md`) |

Two new rules for platform work:

1. A bridge must validate **shape and length** before dispatch — the frame
   limits in `INTEROPERABILITY.md` §9 apply to every new bridge.
2. A capability may never be granted implicitly by a platform (for example, an
   Android permission in the manifest must not auto-grant the Silica
   capability). Both must be requested, and the docs must say so.

---

## 10. Phased plan with acceptance criteria

Every phase has a gate that is a command and an expected result. A phase is done
only when its gate passes in CI.

### Phase 0 — this document *(current)*

**Gate:** reviewed and approved; no code merged. Decisions 1–6 recorded (§12).

### Phase 1 — packages and project structure *(no language change)*

- `silica.toml`, `silica.lock`, `silica new`, `silica add` (pinned commits and
  checksums only; no registry — decision 5).
- `use` resolves user modules from the manifest, built-ins unchanged.

**Acceptance:** `silica new demo && cd demo && silica run` prints the scaffolded
greeting; a project depending on a local package builds; `silica add --locked`
fails when a checksum no longer matches; **all 1,201 existing tests still pass**;
`silica fmt --check examples/*.sc` exits 0.

### Phase 2 — first-class functions and closures *(the hinge, §13)*

- Function values, closures, capture rules, `MAKE_CLOSURE`, `CALL_VALUE`.
- Checker: function types, capture analysis, arity through values.
- `gui.on_click` and `tui` handlers accept a function value; the name form keeps
  working unchanged.

**Gate before code:** §13 approved, including the capture and lifetime rules.

**Acceptance:** the per-iteration binding case behaves as specified (tested); a
closure escaping its defining function keeps its captures alive; arity and type
mismatches are compile errors; `.sbc` round-trips a program with closures;
`tests/test_compat_093.py` and the full suite pass; `FORMAT_MINOR` bumped with
verifier tests.

### Phase 3a — WASM feasibility prototype *(decision 4: prove, then decide)*

- A prototype that compiles the existing bytecode representation to WASM for a
  narrow subset (arithmetic, calls, structs, loops) and runs it under Node and in
  a browser.
- No new standard-library surface, no UI, no build command in the CLI.

**Acceptance:** the prototype reproduces the documented output of five existing
`examples/*.sc` programs byte-for-byte; a written comparison against the
alternatives (bytecode-to-WASM lifter vs. new WASM back end vs. JS interpreter)
with measured size and startup numbers. **The full backend is approved only
after this report is reviewed.**

### Phase 3b — web target (`web.app`)

- Back end chosen by 3a; JS host supplies `ui.*` and `web.fetch`.

**Acceptance:** `examples/calculator_app.sc` builds and runs in a headless
Chromium in CI with **zero console errors**; the same program produces identical
stdout under `silica run`; artifact set asserted by a test; no `.sc` file changes
between targets.

### Phase 4 — desktop target

- Toolkit-independent UI interface over the existing tkinter backend (decision
  3); native host for dialogs, menus, tray; `silica build --target desktop`.

**Acceptance:** built app runs on a machine **without Python installed**; opens a
window, reads a file through a granted capability, and refuses it when not
granted (tested both ways); startup to first frame measured and recorded; the
existing `gui` tests pass unchanged.

### Phase 5 — Android target

- Kotlin host, JNI bridge over the existing frame protocol, lifecycle adapter,
  manifest generator, emulator test in CI.

**Acceptance:** APK installs on an emulator; the app starts, handles a lifecycle
event, calls one platform API through a handle, and returns a value; a denied
capability produces the documented error, not a crash.

### Phase 6 — native FFI (`extern`)

- `extern` declarations, C ABI host, typed signatures, ownership rules from
  `INTEROPERABILITY.md` §11.

**Acceptance:** a documented C library is called through a declared signature;
passing a wrong type is a compile error; a length-bounded buffer test passes.

### Phase 7 — system software *(research, not scheduled)*

No acceptance criteria are defined, because none can be honestly promised.
Phase 7 exists so that phases 1–6 keep its door open.

---

## 11. Risks and trade-offs

| Risk | Impact | Mitigation |
|---|---|---|
| Two back ends to keep in step | divergence between host and web behaviour | one front end, shared checker, differential tests on every example |
| Embedding CPython makes desktop builds large and slow to start | 30–60 MB, slow cold start | acceptable for v1; the Rust VM is the long-term answer |
| Android work is unbounded | months, device-specific bugs | strict gate: one app, one lifecycle event, one API |
| First-class functions change semantics subtly | silent behaviour drift | written capture rules + differential tests before the bump (§13) |
| Capability model fragments per platform | security claims become untrue | one capability registry, platform namespaces only add names |
| The 46–111× performance gap makes desktop apps feel broken | user-visible | do not claim performance; measure and publish per phase |
| `Result` everywhere makes ordinary code noisy | developer friction | a narrow, documented set of helpers; no exceptions smuggled back in |

**Alternatives considered and rejected:** transpile-to-Kotlin (§5.3); a
JavaScript interpreter of Silica bytecode in the browser (slow, and it makes the
browser a second VM to maintain); building all targets at once (the brief
forbids it, and it would ship five half-working backends).

---

## 12. Recorded decisions

These were the six open questions in v1.0. Each is now decided; what follows is
the decision, the reasoning as understood, and what it commits the project to.

### Decision 1 — Error model: `Result`, not exceptions

**Decided:** expected failures — I/O, network, interop — return a `Result`-shaped
value. Exceptions are **not** added, not even as an optimisation for
programming errors.

**Programming errors versus recoverable errors.** The distinction is now a
design requirement, not a convention:

| Class | Examples | Behaviour |
|---|---|---|
| Programming error | wrong type (already a compile error), out-of-range index, missing map key, division by zero, arity mismatch | **aborts** with a located diagnostic, as today. Not catchable, not a `Result`. |
| Recoverable failure | file missing, permission denied, connection refused, timeout, malformed JSON from a peer, bridge call rejected | returned as a **failed `Result`** with a stable machine-readable code and a human message. |

**Consequence:** the language needs a `Result` representation before any I/O
module ships. Its syntax, construction and propagation must be specified in a
separate design document (§14, open item 1) and approved before Phase 3.

### Decision 2 — Concurrency: async/await, deferred until after closures

**Decided:** async/await is the intended model; **nothing is implemented yet**.
Function values, closures, capture semantics and their VM representation come
first (§13). The event loop and async model are designed *around* that
representation.

**Consequence:** the `async` module stays reserved and failing. No keyword is
reserved in the parser until the design exists.

### Decision 3 — Desktop: keep tkinter, add a toolkit-independent interface

**Decided:** tkinter remains the desktop backend. The work is to define a
toolkit-independent UI interface (widget tree, layout, event dispatch, theming)
that the current renderer implements, so a native backend can be added later
without changing Silica application logic.

**Explicitly not decided:** rewriting the UI system. `docs/UI.md`'s rule stands —
a target is "supported" only when an acceptance test renders it.

**Consequence:** `gui` keeps its 22 natives and its name-based handlers until
Phase 2; the interface is extracted underneath them, not around them.

### Decision 4 — WASM: a prototype before a commitment

**Decided:** WASM is a proposed strategy. A small feasibility prototype must
prove that the existing compiler representation can target WASM while preserving
Silica semantics, and it must be compared against the alternatives with measured
numbers, before any full backend is approved.

**Consequence:** Phase 3 is split into 3a (prototype + written report) and 3b
(backend, only after the report is reviewed).

### Decision 5 — Packages: lockfile, pinned commits, checksums; no registry

**Decided:** start with a lockfile, pinned Git commit references and checksums.
No public registry. Deterministic resolution and integrity verification first.

**Consequence:** `silica add` resolves a Git URL to an immutable commit and
records its hash; `silica add --locked` fails on a mismatch. A registry, if it
ever exists, is a service layered on this, not a prerequisite.

### Decision 6 — Minimum CPython version: unchanged

**Decided:** the declared minimum stays as published. Raising it requires a
compatibility audit, test evidence, and a documented reason.

**Consequence:** no `match` statements, no 3.11-only standard-library calls, and
CI keeps testing the declared floor.

---

## 13. First-class functions and closures (Phase 2 design)

This section is the gate for Phase 2. It is a **design**, not an implementation:
no syntax here has been added to the parser, and every rule below must be
accepted or amended before code is written.

The goal is narrow and specific: make a Silica function a value that can be
stored, passed, returned and called — with captures that behave the way a reader
expects, and without changing what any existing program does.

### 13.1 Function values and calling conventions

**Value form.** A function value is a first-class value carrying code, an arity,
and a capture list. Named functions declared with `sfn` remain what they are
today: callable by name, unchanged. Used as a value, a named function produces a
closure with **zero captures** — a "static function value", the cheap case.

**Type syntax (proposed).** A function type is written

```
Fn(Int, String) -> Bool
Fn() -> Unit
```

`Fn` is a built-in type form, parsed only in type position, so it cannot collide
with an identifier. It is deliberately not `Fn<T>`: function types are not
generic parameters, and reusing the generic syntax would make
`Fn(Int) -> Int` ambiguous with type arguments.

**Calling.** Two call forms, both explicit in bytecode:

| Form | Source | Opcode |
|---|---|---|
| by name | `add(1, 2)` where `add` is an `sfn` | `CALL` (unchanged) |
| through a value | `f(1, 2)` where `f` holds a function value | `CALL_VALUE` (new) |

The checker resolves which form applies from the binding's type, so the compiler
never guesses. `CALL_VALUE` pops the callee and the arguments, checks the arity
against the closure's recorded arity (a mismatch is a *runtime* error only when
the value came through `Any`; otherwise it is a compile error).

**Calling convention.** Unchanged frame layout: `n_locals` slots, arguments in
the first `arity` slots. A closure call pushes a frame whose locals begin with
its captured cells (see §13.5), so a closure body addresses captures exactly like
locals.

### 13.2 Closure capture semantics

**Lexical, static, and decided by the compiler.** A nested function captures the
free variables it references; the set is computed by free-variable analysis in
the checker and recorded on the chunk. There is no dynamic scoping, no implicit
`self`, and no way for a function to reach a binding it did not name.

**Capture is by cell for mutable bindings, by value for constants.** Concretely:

| Captured binding | Captured as | Mutation visible in the enclosing scope |
|---|---|---|
| `let x: Int = 1` | a shared cell | **yes** — both see the same cell |
| `const x: Int = 1` | the value itself | not applicable; `const` cannot be reassigned |
| parameter `x: Int` | a shared cell | yes, if the parameter is reassigned |
| `struct`/`class` value | the reference | field mutation is visible (identity), regardless of `let`/`const` |

**Loop bodies create a fresh binding per iteration.** `per` and `tant` bodies
that declare a binding capture *that iteration's* cell, so a list of closures
built in a loop captures `1, 2, 3` and not `3, 3, 3`. This is the classic
"closure in a loop" trap and it is specified here so it cannot be decided by
accident. It is the single most important test in §13.9.

**What is not captured.** Globals are not captured — they are looked up at call
time through `LOAD_GLOBAL`, so a closure always sees the current global. Module
members are resolved the same way.

### 13.3 Mutable and immutable captures

- A mutable capture is a **shared cell**: writing inside the closure writes the
  enclosing binding. Reads and writes inside the closure are ordinary
  `LOAD_LOCAL`/`STORE_LOCAL` against the cell slot.
- An immutable capture is **copied** at closure creation. This is not an
  optimisation: it is the observable rule, and it means a `const` read inside a
  closure cannot change because of something the enclosing function did later.
- `const` freezing extends to captures: capturing a `const` struct does not
  unfreeze it, and a frozen struct cannot be mutated through a closure any more
  than through the original binding.
- **No capture-by-copy for `let`.** Copying mutable captures would make two
  closures over the same variable disagree, which is worse than the sharing
  rule above.

### 13.4 Lifetime and memory management

- **Lifetime is reachability.** A closure keeps its captured cells alive for as
  long as the closure is reachable; there is no `free`, no `release`, and no
  lifetime annotation in the language.
- **Today's runtime is CPython**, so values are freed by reference counting and
  reference cycles are collected by CPython's cycle collector. A closure stored
  in a cell it captures is a cycle — legal, collected, and not a leak on this
  runtime.
- **A future non-refcounting VM must answer this explicitly.** If the Rust VM
  uses an arena or a tracing collector, the rule above stays true but the
  mechanism changes; that is a VM-design decision recorded in §14, open item 3,
  and it must not leak into the language surface.
- **Escaping closures are supported**: returning a closure that captures a local
  keeps that cell alive after the defining frame is gone. This is required for
  handlers and is the reason captures are cells rather than frame slots.
- **No finalisers.** A closure cannot run code when it is collected.

### 13.5 VM representation

Proposed shapes (names illustrative; the invariants are the commitment):

```
Closure
  code_index : Int        # index into the chunk's function table
  arity      : Int
  captures   : List[Cell]
  name       : String     # for diagnostics only

Cell
  value      : Any        # one slot, shared by every closure that captured it
```

- **Frame layout stays flat.** A function that has captured locals allocates
  those slots as `Cell` objects at entry, decided at compile time; uncaptured
  locals stay plain slots. The verifier enforces that a slot is never used both
  ways inside one function.
- **New opcodes** (three, `FORMAT_MINOR` bump):
  - `MAKE_CLOSURE` — operand: code index, then capture descriptors (slot index
    or upvalue index per capture).
  - `CALL_VALUE` — operand: argument count.
  - `LOAD_UPVALUE` / `STORE_UPVALUE` — or, equivalently, `LOAD_LOCAL` with a
    cell flag. The design prefers **explicit upvalue opcodes**: the verifier can
    then check capture indices against the recorded capture list instead of
    trusting a flag.
- **Serialization.** Closures are runtime values and are **not** constants: the
  constant pool records the *code* of nested functions and their capture
  descriptors, never a live closure. A `.sbc` file therefore remains
  deterministic and hashable.
- **No host pointers.** A `Closure` holds an index into the chunk, never a
  Python callable. This keeps the bytecode portable and keeps §4.5's promise to
  a future freestanding runtime.

### 13.6 Type checking

- **Function types are checked, not erased**: `Fn(Int) -> Int` is a distinct
  type. Passing `Fn(String) -> String` where `Fn(Int) -> Int` is expected is a
  compile error.
- **Arity is part of the type.** `Fn(Int, Int) -> Int` and `Fn(Int) -> Int` are
  different types and do not unify.
- **Named functions used as values take their declared signature.** An `sfn`
  with an unannotated parameter yields `Any` for that position, consistent with
  existing inference.
- **Invariance, matching generics.** `Fn(Any) -> Unit` is not a supertype of
  `Fn(Int) -> Unit`. Generics in 0.10.0 are invariant; function types follow, so
  there is one rule to learn.
- **`Any` still exists.** Assigning a function value to `Any` loses the
  signature; the call is then checked at runtime and a mismatch is a runtime
  error with a located diagnostic — the same shape as today's `Any` behaviour
  for containers.
- **Capture analysis is a checker responsibility.** A closure that references a
  variable not in scope is a compile error naming the variable; a closure that
  captures nothing is a static function value and is not boxed.

### 13.7 Serialization restrictions

Explicit, because "a function is a value" invites "send it somewhere":

| Situation | Rule |
|---|---|
| Closure as a `.sbc` constant | **forbidden** — closures are runtime values only |
| Closure through `json` | **refused** with a named error (`json` serialises data, not code) |
| Closure across the interop bridge | **refused** — `python.call` and every future bridge reject function values; a handle is never minted for one |
| Closure stored in a struct field | **allowed**; the struct then cannot be JSON-serialised or bridged |
| Closure printed with `sprint` | **allowed**, prints `<fn name>` — stable, documented text |
| Closure compared with `==` | **identity only**; no structural equality, no ordering |
| Closure reconstructed from text | **no such operation**; there is no `eval` and none is planned |

The last two rows matter for security: a value that cannot be serialised, cannot
be compared structurally and cannot be built from text cannot be smuggled across
a trust boundary by accident.

### 13.8 Compatibility with existing named functions

- **`sfn` declarations are unchanged.** Same syntax, same semantics, same
  bytecode (`CALL` by name).
- **Name-based handlers keep working.** `gui.on_click(button, "handle_click")`
  and the TUI equivalents stay exactly as they are; accepting a function value is
  an **added** form, not a replacement. Existing examples must run untouched.
- **No existing program changes meaning.** The checker only gains the ability to
  accept programs it previously rejected; it must not reject anything it accepts
  today. `tests/test_compat_093.py` is the guard, and the full suite runs in CI
  on Python 3.9, 3.11 and 3.12.
- **`type_of` reports `Fn`** for a function value. This is new output only for
  values that could not exist before, so nothing existing changes.
- **Formatter round-trip.** `silica fmt` must print function types and closures
  and re-parse to the same AST; without that, the formatter would corrupt files.

### 13.9 Regression tests

The suite that must exist before Phase 2 is called done. Each row is a test in
`tests/test_closures.py` unless noted.

| # | Case | Expected |
|---|---|---|
| 1 | closure captures a `let` and mutates it | enclosing scope observes the write |
| 2 | closure captures a `const` | value copied; later enclosing mutation is impossible by construction |
| 3 | **closures built in a loop capture per-iteration bindings** | a list of three closures returns `1, 2, 3` |
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
| 17 | full suite on 3.9 / 3.11 / 3.12 | green, including `test_compat_093.py` |

---

## 14. Unresolved trade-offs

Recorded so they are not decided by accident during implementation.

1. **`Result` syntax and propagation.** Needed before Phase 3. Options: a
   `struct`-shaped `Result` with `ok`/`error` fields and `si`-based handling
   (no new syntax), versus a dedicated `si ok = f() sino { ... }` binding form.
   Recommendation: start with the struct and no new syntax; revisit only if
   real code proves it unbearable.
2. **Capture-by-cell versus capture-by-copy for `let`.** Decided as shared cell
   (§13.2). Reversible only with a documented breaking change, so it needs to be
   right now.
3. **Cycle collection on a future VM.** CPython collects closure cycles today.
   A Rust VM needs an explicit answer (arena-per-call-tree, tracing collector,
   or a documented "cycles leak" limit). Language semantics do not change; the
   runtime's promise does.
4. **Function type ergonomics.** `Fn(Int) -> Int` is explicit but verbose in
   parameter lists. A type alias form (`type Handler = Fn(Int) -> Unit`) is
   attractive and is **not** in this design.
5. **Closures in `const` bindings.** Whether `const f = sfn() { ... }` is
   allowed, and what freezing means for a closure with mutable captures.
   Recommendation: allow, and freeze the binding, not the captured cells.
6. **Whether async/await needs `Fn` to be `Send`-like.** On a single-threaded
   event loop, probably not; if green threads ever return, this becomes a real
   question.

---

## 15. What this document does not claim

- That Silica is production-ready, fast, or secure against a hostile host.
- That any phase after Phase 0 is implemented.
- That WASM is the chosen backend — decision 4 requires a prototype first.
- That async/await exists, or will ship in any particular release.
- That Android or system software will be delivered on any date.
- That the current VM is a sandbox.
- That closures behave as described here today — §13 is a design awaiting
  approval, and no parser, checker or VM code for it has been written.

The objective is a working, verifiable foundation — not APIs that look finished.
