# Silica Platform Architecture

**Status:** draft for review — no implementation may begin until this document is approved
**Applies to:** Silica 0.10.0 (`sufiyan-sabeel/silica`)
**Document version:** 1.0 · 2026-11-02
**Scope:** how Silica becomes able to build web, desktop, Android, GUI/TUI and
eventually system software — without breaking anything that works today

---

## 0. Summary

Silica today is a Python-hosted language: a lexer, parser, checker, bytecode
compiler, verifier and stack VM, 29 standard-library modules, three UI renderers
and a sandboxed Python interop channel. It can run programs, draw a terminal UI,
open a tkinter window, render a web page and drive speech synthesis. It cannot
produce a standalone binary, cannot call a platform API that has no Silica
binding, cannot run two things at once, and has no package ecosystem.

This document proposes how to close that gap. The core claim is:

> **Platforms are reached through host processes, not through the VM.** Silica
> logic stays in `.sc` files and bytecode; every platform API is reached through
> a validated bridge with the same handle discipline the Python interop already
> uses. The VM never gains the ability to touch a raw pointer, a file
> descriptor, a JNI reference or a browser object directly.

The single largest blocker is not any platform SDK. It is that **Silica has no
first-class functions**, which makes real event handling, callbacks, and any
async model impossible to express in the language. That is Phase 2, and it gates
everything after it.

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
own logic in the browser today. §5.2 addresses this directly.

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
   blocker for real applications.
4. **Single-threaded, no concurrency primitives.** No threads, no async, no
   timers, no promises. *Consequence:* a server cannot serve two requests; a
   GUI cannot do work without freezing; a network call blocks everything.
5. **No exceptions or error values.** A failure aborts the program. *Consequence:*
   any real I/O layer (HTTP, JNI, file pickers) needs either a `Result`-shaped
   value or an exception model before it can be used by application code.
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

`web.app` requires compiling Silica to a form the browser executes. Three
options, ranked in §11; the recommendation is **WASM with a small JS host**, not
a JavaScript interpreter written in JavaScript.

### 4.2 Desktop

**Definition of done:** `silica build --target desktop` produces a single
directory or archive that runs on a machine with no Python installed.

Path: embed CPython (or link the future Rust VM) with the `.sbc` chunk, a
platform host process for native dialogs/menus/tray, and the existing tkinter
renderer replaced or supplemented by a native toolkit bridge. Handlers stay
name-based until Phase 2 gives them closures.

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
can call back into Silica code.

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
| **Native host** | C ABI (`dlopen`), OS APIs, dialogs, tray | host process, same frames, typed signatures | 3 |
| **JNI host** | Android/Java | Kotlin host process, same frames, handles | 5 |
| **WASM** | browser, sandboxed compute | compile Silica to `.wasm`, JS host provides imports | 2 |

The rule that makes this tractable: **a bridge exposes a typed surface, not an
object graph.** A Silica program receives an opaque handle or a plain value
(`Int`, `Float`, `String`, `Bool`, `List`, `Map`, struct) — never a host object.
`docs/INTEROPERABILITY.md` §2 already defines the value mapping; every new bridge
reuses it rather than inventing one.

### 5.2 Keeping logic in `.sc`

The requirement is that application logic stays in Silica files. That holds if:

- the `.sc` sources compile to bytecode for host targets and to WASM for the
  browser — one front end, two back ends;
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
  process boundary and a 100× slowdown into a phone. If it is built at all, it is
  a stepping stone behind a flag, documented as such.
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
| P2 | First-class functions, closures | new: function values, capture rules | **minor bump**: `CLOSURE`, `CALL_VALUE` |
| P3 | Error values (`Result`) or exceptions — decision in §12 | new: one of two models | bump if exceptions |
| P4 | Concurrency: async/await **or** green threads | new keywords | bump |
| P5 | `extern` declarations for C ABI | new declaration form | bump |
| P6 | Alternative back end (WASM, then Rust VM) | none | new target, same `.sbc` semantics |

**Bytecode policy.** `FORMAT_MAJOR` changes only for an incompatible layout;
adding opcodes bumps `FORMAT_MINOR` and keeps older readers able to *reject*
rather than misread. Every bump updates `docs/BYTECODE.md`, the verifier's stack
table, and the round-trip tests in the same commit.

**Why first-class functions come before platforms.** Every platform story needs
a callback: a button press that runs Silica code, a fetch that resumes, a
lifecycle event. Name-based handlers got the GUI to 0.9; they cannot carry an
application. P2 is therefore the hinge of this whole plan.

---

## 7. Standard-library roadmap

Ordered by what unlocks a target, not by what is interesting.

| Order | Modules | Unlocks | Notes |
|---|---|---|---|
| 1 | `process`, `log` | desktop, CLI tools | `process` behind a capability; no shell interpolation |
| 2 | `net` (TCP), `http` (client) | web.app, desktop | TLS via the host, not hand-rolled |
| 3 | `crypto` (hash, HMAC, AEAD) | auth, tokens | never invent primitives; wrap a vetted library |
| 4 | `async` (or the P4 model) | servers, UI responsiveness | must not leak host futures into Silica |
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
  silica.toml            # name, version, entry, targets, capabilities
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
```

Commands, each of which must exist before its phase is "done":

```
silica new myapp                  # scaffold the tree above
silica add <pkg>                  # resolve, verify checksum, write lockfile
silica build --target web         # emit dist/web
silica build --target desktop     # emit dist/desktop
silica run --capabilities silica.toml
silica test
```

Artifacts are deterministic: same inputs, same bytes, so a release can be
verified by hash. `docs/SUPPLY_CHAIN.md` already sets that bar for wheels; app
builds inherit it.

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

**Gate:** reviewed and approved by the maintainer; no code merged.

### Phase 1 — packages and project structure *(no language change)*

- `silica.toml`, `silica new`, `silica add`, lockfile with checksums.
- `use` resolves user modules from the manifest, built-ins unchanged.

**Acceptance:** `silica new demo && cd demo && silica run` prints the scaffolded
greeting; a project depending on a local package builds; **all 1,201 existing
tests still pass**; `silica fmt --check examples/*.sc` exits 0.

### Phase 2 — first-class functions *(the hinge)*

- Function values, closures over locals, `CALL_VALUE`, `CLOSURE`.
- Checker: capture rules, arity through function types, no implicit `Any`.
- `gui.on_click` accepts a function value; the old name form keeps working.

**Acceptance:** a closure over a loop variable behaves per the written rule
(tested); bytecode `FORMAT_MINOR` bumped with round-trip tests; existing
name-based handlers unchanged; suite green.

### Phase 3 — web target (`web.app`)

- WASM back end for pure Silica code; JS host supplies `ui.*` and `web.fetch`.
- `silica build --target web` emits `index.html`, `app.wasm`, runtime.

**Acceptance:** `examples/calculator_app.sc` builds and runs in a headless
Chromium in CI with **zero console errors**; the same program produces identical
stdout under `silica run`; artifact set asserted by a test; no `.sc` file
changes between targets.

### Phase 4 — desktop target

- Embed the runtime; native host for dialogs, menus, tray; `silica build
  --target desktop` emits a runnable directory/archive.

**Acceptance:** built app runs on a machine **without Python installed**; opens a
window, reads a file through a granted capability, and refuses it when not
granted (tested both ways); startup to first frame measured and recorded.

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
| WASM back end doubles the compiler surface | two back ends to keep in step | one front end, shared checker, differential tests on every example |
| Embedding CPython makes desktop builds large and slow to start | 30–60 MB, slow cold start | acceptable for v1; the Rust VM is the long-term answer |
| Android work is unbounded | months, device-specific bugs | strict gate: one app, one lifecycle event, one API |
| First-class functions change semantics subtly | silent behaviour drift | written capture rules + differential tests before the bump |
| Capability model fragments per platform | security claims become untrue | one capability registry, platform namespaces only add names |
| The 46–111× performance gap makes desktop apps feel broken | user-visible | do not claim performance; measure and publish per phase |

**Alternatives considered and rejected:** transpile-to-Kotlin (§5.3); a
JavaScript interpreter of Silica bytecode in the browser (slow, and it makes the
browser a second VM to maintain); building all targets at once (the brief
forbids it, and it would ship five half-working backends).

---

## 12. Decisions required before Phase 1 starts

1. **Error model:** `Result` values or exceptions? Recommendation: `Result` for
   I/O and bridge failures (no VM unwinding), exceptions deferred indefinitely.
2. **Concurrency:** async/await or green threads? Recommendation: async/await,
   because it maps onto both the browser and Android without a thread scheduler.
3. **Desktop toolkit:** keep tkinter, or bridge to a native toolkit? Recommendation:
   bridge; tkinter stays as the headless-testable fallback.
4. **WASM strategy:** compile `.sbc` to WASM, or add a WASM back end to the
   compiler? Recommendation: the latter — a bytecode-to-WASM lifter is simpler
   and keeps the checker authoritative.
5. **Package registry:** hosted index, or Git URLs plus checksums? Recommendation:
   Git URLs first; a registry is a service, not a feature.
6. **Minimum host:** CPython 3.9+ stays the floor for host targets, or raise it
   to 3.11 to use `match` and faster startup?

---

## 13. What this document does not claim

- That Silica is production-ready, fast, or secure against a hostile host.
- That any phase after Phase 0 is implemented.
- That Android or system software will be delivered on any date.
- That the current VM is a sandbox.
- That adding platforms makes the language more capable than the compiler and
  checker actually are.

The objective is a working, verifiable foundation — not APIs that look finished.
