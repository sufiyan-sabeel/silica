# Silica Roadmap

Status of each milestone in the original plan. "Done" means implemented,
tested and documented in this repository — nothing here is aspirational.

**Corrected 2026-11-09 against the 0.10.1 tree.** Several statuses below had
fallen behind the implementation: `path`, `time` and `random` were still listed
as missing, packaging and CI were still listed as not started, and the
limitations list still said there were no generics, structs or methods. Every
status here was re-checked against the source, and the per-capability
classification now lives in `docs/LANGUAGE_SPEC.md` §13, which is authoritative
if the two ever disagree.

## Milestone A — front end · **done**

* Lexer with source locations (`silica/lexer.py`).
* AST (`silica/ast.py`) and recursive-descent parser (`silica/parser.py`).
* Located diagnostics with hints for lex/parse errors.
* Integer and string expressions, `let`/`const`, `sprint`, `sfn`, `ret`.

## Milestone B — semantics and engine · **done**

* Semantic analysis: scopes, symbol resolution, duplicate detection, entry point.
* Static type checker with `Int`, `Float`, `Bool`, `String`, `Unit`, `List`,
  `Map` and inference from initialisers.
* Conditionals (`si`/`sino`), `und`/`ou`/`non` with short-circuit codegen,
  `tant`, `per`, functions and recursion.
* Bytecode compiler and stack VM with explicit call frames.

## Milestone C — CLI, bytecode, tests, docs · **done**

* Commands: `run`, `check`, `compile`, `run *.sbc`, `repl`, `fmt`, `test`,
  `--version`, `--help`. Planned commands report that they are not implemented.
* Versioned `.sbc` format with magic bytes, version, CRC-32, constant pool,
  function metadata, line table (`docs/BYTECODE.md`).
* Bytecode verifier: opcodes, operands, jump targets, call arities, native
  existence, stack discipline, resource limits.
* REPL with persistent globals and functions.
* Formatter with `--check` mode; refuses to strip comments.
* 227 automated tests at 0.1.0 (`python3 -m unittest discover -s tests -t .`),
  10 example programs, 5 Silica-level test files.
* Documentation set: language spec, grammar, bytecode, stdlib, performance,
  bootstrap, roadmap.

## Milestone D — standard library and I/O · **capability model, fs and json done**

Done: `core`, `math`, `string`, `collections`; the capability model with
`fs.read` / `fs.write` / `fs.list` granted per root path and enforced at the VM
dispatch point; the `fs` module behind those capabilities; the `json` module
with a documented value mapping, position-reporting errors and round trips;
`silica capabilities`; 323 automated tests at 0.1.1.

**Since corrected:** `path`, `time` and `random` are implemented and shipped —
they need no capability (`path` is pure string work, `time` reads the clock and
`random` is seeded). Still not done: `regex` and `log`.

At 0.1.1 the milestone also delivered `silica capabilities`; the UI work that
followed in 0.2.0 is recorded under Milestone F.

## Milestone E — packaging, CI, release · **partly done (packaging, CI and release integrity; no package manager, no Rust port)**

* `silica new / add / remove / install / build` with `silica.toml`, lockfiles,
  reproducible resolution, checksums and provenance.
* Package registry and publishing rules.
* CI matrix, release artifacts, checksums, installation docs.
* Rust port of the engine (the reference implementation is Python; see
  `docs/PERFORMANCE.md` for why this matters and what the baseline is).

**Since corrected:** the CI matrix (Python 3.9, 3.11, 3.12), release artefacts,
checksums, supply-chain and release-integrity checks, and the installation guide
all exist (`docs/PACKAGING.md`, `docs/RELEASE_INTEGRITY.md`,
`docs/SUPPLY_CHAIN.md`, `docs/INSTALL.md`; workflows `ci.yml`, `publish.yml`,
`release.yml`, `verify-release.yml`). The `silica new / add / remove / install /
build` commands do **not** exist, no package manager or registry exists, and
there is no Rust port — those remain open. The Rust VM is designed and gated on a
toolchain: `docs/design/SILICA_R1_IMPLEMENTATION_READINESS.md`.

## Milestone F — Silica UI and self-hosting · **UI 0.1 done, self-hosting not started**

Done (Silica 0.2.0, documented in `docs/UI.md`):

* Three additive grammar changes: dotted imports, member-path resolution and
  builder blocks.
* The UI core: node tree, theme with WCAG contrast validation, property-to-CSS
  style model, and declarative events.
* The web renderer: HTML + `theme.css` + a dependency-free `silica-ui-runtime.js`.
* Responsive breakpoints, scrolling, sticky headers, CSS animation with a
  reduced-motion override, and `ui.list` binding `item` per element.
* Reserved namespaces and adapter slots that fail loudly.

Not done: every other renderer (terminal, Android, iOS, desktop, OS-UI), the
framework adapters, client-side Silica (needs a WASM build of the VM),
virtualized lists, 3D transforms and shared-element transitions.

Self-hosting: see `docs/BOOTSTRAP.md` for the staged plan. Silica does not
compile itself today.

## Milestone G — loop control · **done (0.9.3)**

* `break` and `continue` for `tant` and `per`, compiled to jumps: no new opcode,
  no change to the `.sbc` format.
* Loop-frame stack in the compiler; the `per` iterator is popped on `break`, so
  the verifier's stack-depth analysis still holds.
* `loop_depth` in the checker: a jump outside a loop, or one that tries to cross
  a function boundary, is a compile-time error with a hint.
* 34 tests, an example, a spec section, grammar rules and editor highlighting.

Not done: labelled jumps, `else` on loops, and `break` out of a `call { ... }`
builder block (rejected by design).

## Known limitations in v0.10.1

* `List`/`Map` elements check as `Any`. User-defined generics on functions and
  structs **do** work (`docs/GENERICS.md`), but the built-in containers are not
  generic.
* No first-class functions and no closures: a function can be called, not passed.
  Structs, classes, methods, `static` methods and `private` members all exist.
* No exceptions; errors are runtime aborts. `Result`-shaped recoverable errors are
  a recorded decision, not an implementation.
* `per` loop variables are immutable.
* No labelled `break`/`continue`: they always target the innermost loop.
* No negative indexing, no slicing, no element assignment (`xs[i] = v`); use `push`.
* No enums, tuples, pattern matching or optional types.
* No string interpolation: `"a {x}"` is literal text.
* No threads, no `async`/`await`; the VM is single-threaded.
* No user-defined modules and no package manager: `use` resolves built-ins only.
* The REPL compiles each entry from scratch (fine for interactive use, not a
  fast edit-compile loop).
* The formatter is AST-based and therefore refuses files with comments.
* Performance: slower than CPython; see `docs/PERFORMANCE.md`.
