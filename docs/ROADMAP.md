# Silica Roadmap

Status of each milestone in the original plan. "Done" means implemented,
tested and documented in this repository — nothing here is aspirational.

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

Not done: `path`, `time`, `random`, `regex`, `log`. Each needs its own capability
story before it is exposed (`time` and `random` are the easy ones; `path` is
mostly pure string work and could be added without a capability at all).

At 0.1.1 the milestone also delivered `silica capabilities`; the UI work that
followed in 0.2.0 is recorded under Milestone F.

## Milestone E — packaging, CI, release · **not started**

* `silica new / add / remove / install / build` with `silica.toml`, lockfiles,
  reproducible resolution, checksums and provenance.
* Package registry and publishing rules.
* CI matrix, release artifacts, checksums, installation docs.
* Rust port of the engine (the reference implementation is Python; see
  `docs/PERFORMANCE.md` for why this matters and what the baseline is).

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

## Known limitations in v0.2.1

* No generics: `List`/`Map` elements check as `Any`.
* No first-class functions, closures, methods or user-defined types.
* No exceptions; errors are runtime aborts plus `ret`-based conventions.
* `per` loop variables are immutable.
* No negative indexing, no element assignment (`xs[i] = v`); use `push`.
* The REPL compiles each entry from scratch (fine for interactive use, not a
  fast edit-compile loop).
* The formatter is AST-based and therefore refuses files with comments.
* Performance: slower than CPython; see `docs/PERFORMANCE.md`.
