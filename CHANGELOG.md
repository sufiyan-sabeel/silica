# Changelog

All notable changes to Silica are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning for its toolchain; the language surface is `0.x` until
`1.0.0`.

## [0.2.1] — 2026-10-27

Brand integration: the Silica logo is in the repository, and `.sc` files have a
file icon in the one editor that can show one. No language, bytecode or VM change.

### Added
- `assets/logo/`: the mark, the wordmark, a transparent symbol, a monochrome
  variant and a full icon set (16–512px plus a multi-size `favicon.ico`), cropped
  from the supplied brand sheet. Design and colours are unchanged; nothing was
  redrawn.
- `editors/vscode/`: a VS Code extension that registers the `silica` language for
  `.sc`, contributes a TextMate grammar covering the whole keyword vocabulary, and
  contributes a file icon theme mapping `sc` to the Silica mark. This is a new
  sub-project — the repository has no editor of its own to integrate with.
- `ui.render({..., favicon: oui})`: embeds a 32px mark as a data URI so a
  rendered page carries the Silica icon without an extra file. Off by default.
- `tests/test_assets.py`: 28 tests (441 total) covering the asset files, the icon set, the
  editor manifests, the grammar's keyword coverage and the `hello.sc` check.

### Changed
- `pyproject.toml` ships `silica/ui/assets/*.png` as package data and declares a
  `dev` extra (`pytest`, `pillow`) so the image checks can run in CI.
- Version 0.2.1.

### Notes
- A file icon theme is all-or-nothing in VS Code: enabling it replaces the user's
  current theme for every file type. `editors/vscode/README.md` documents this and
  shows how to copy only the `.sc` entry into an existing theme.

## [0.2.0] — 2026-10-27

Silica UI 0.1: the UI DSL, the UI core and the web renderer. Three additive
grammar changes, one new subsystem, and 90 new tests (413 total). The `.sbc`
format is unchanged at 1.0, so every existing bytecode file still loads.

### Added — grammar (all provably additive)
- **Dotted module paths** in `use`: `use ui.lib.widgets`. Was
  `parse error: unexpected '.' after statement`.
- **Member-path resolution**: in a chain, the longest prefix that names an
  imported module is the module and exactly one member may follow it. Was
  `type error: only standard-library modules have members`.
- **Builder blocks**: `call { ... }` in statement position, `{` on the same line
  as the call, head must be a call, contents are ordinary Silica. Was
  `parse error: unexpected '{' after statement`.
- Importing a module now also brings its submodules into scope.

### Added — UI core
- `silica/ui/`: node tree and runtime, theme with WCAG AA contrast validation,
  property-to-CSS style model with responsive breakpoints, and declarative
  events lowered to JSON actions.
- Widget catalogue: `app`, `screen`, `row`, `column`, `stack`, `grid`, `card`,
  `text`, `button`, `image` (with required `alt`), `link`, `spacer`, `divider`,
  `scroll`, `list` (binds `item` per element), `list_item`, `sticky`, `animate`,
  `on`.
- Modules: `ui` (nine re-exported primitives plus `theme`, `set_theme`,
  `navigate`, `toggle`, `render`), `ui.state`, `ui.lib.widgets`, `ui.lib.theme`,
  `ui.lib.colors`, `ui.lib.layout`, `ui.lib.scroll`, `ui.lib.animation`.
- Reserved namespaces (`ui.lib.motion3d`, `navigation`, `gestures`,
  `accessibility`, `platform`, `terminal`, `graphics`, `canvas`) and adapter
  slots (`react`, `flutter`, `compose`, `swiftui`, `css`, `qt`) that fail loudly.
- Diagnostics E1–E11, each with a specific message and, where useful, a hint.

### Added — web renderer
- `ui.render({target: "web", out: "..."})` writes the document, `theme.css` and
  a dependency-free `silica-ui-runtime.js`. Nothing is written unless `render`
  is called.
- `ui.render` requires the `fs.write` capability for its output path, so the
  capability model covers rendering too.
- Responsive properties become media queries; scrolling and sticky map to
  `overflow`, `scroll-snap-type`, `overscroll-behavior` and `position: sticky`;
  every animation also emits a `prefers-reduced-motion` override.
- Event bodies compile to a declarative JSON action list interpreted by the
  bundled runtime. The browser does not run Silica, and the docs say so.

### Added — tooling, docs and examples
- The formatter understands builder blocks.
- `docs/UI.md`: grammar, namespaces, widgets, properties, events, renderer,
  diagnostics and the compatibility matrix.
- `examples/ui_hello.sc`, `examples/ui_tasks.sc`, `examples/ui_animate.sc`.

### Changed
- Version 0.2.0. `.sbc` format stays at 1.0.
- `ui` re-exports exactly nine primitives; a test asserts the two lists never
  diverge from `ui.lib.widgets`.

## [0.1.1] — 2026-10-27

Milestone D: the capability model, the `fs` module and the `json` module. The
grammar and the `.sbc` format are unchanged, so every 0.1.0 program and every
existing `.sbc` file still loads and runs.

### Added
- **Capability model** (`silica/capabilities.py`). `fs.read`, `fs.write` and
  `fs.list`, each granted for a root path. Least privilege by default: a program
  with no grants can touch nothing. Grants come from the command line or a TOML
  `[capabilities]` table; `deny` always overrides a grant; `derive()` can only
  narrow. Paths are resolved before the containment check, so `..` and symlink
  escapes are refused.
- **Enforcement at the VM dispatch point.** Privileged natives declare the
  capability they need; the VM authorises the call before the body runs and
  passes the authorised path. Denials are located errors
  (`file:line: capability error: ...`) with a hint naming the flag that would
  grant it.
- **`fs` module** (`use fs`): `fs.read_text`, `fs.write_text`, `fs.exists`,
  `fs.list_dir`.
- **`json` module** (`use json`): `json.parse`, `json.stringify` (compact, or
  indented 0–8). Documented mapping onto the six Silica types, position-reporting
  parse errors, rejection of `NaN`/`Infinity` and of integers outside 64-bit
  range, last-value-wins duplicate keys, and round-trip tests.
- `silica capabilities` command printing the effective capability set.
- `--allow-fs-read`, `--allow-fs-write`, `--allow-fs-list`, `--deny-fs-read`,
  `--deny-fs-write`, `--deny-fs-list` and `--capabilities FILE` flags on
  `silica run` and `silica repl`.
- `examples/json_demo.sc` and `examples/fs_demo.sc`.
- 96 new automated tests (323 total), covering allowed, denied, missing and
  malformed capability configurations, path traversal, symlink escape,
  inheritance that cannot widen, filesystem failure modes, and JSON parsing,
  serialisation, errors and round trips.

### Changed
- `fs` and `json` are no longer listed as planned modules.
- The checker hint for unknown modules now lists `fs` and `json`.
- Version bumped to 0.1.1. `.sbc` format stays at 1.0.

## [0.1.0] — 2026-10-26

First working release: a complete reference implementation of the Silica
language, its bytecode format and its toolchain.

### Added
- Lexer with source locations, comments, string escapes and number literals.
- Recursive-descent parser for the full keyword vocabulary (`sprint`, `dit`,
  `input`, `si`, `sino`, `und`, `ou`, `non`, `oui`, `nein`, `tant`, `per`,
  `sfn`, `ret`, `use`, `fin`, `halt`, plus `let`/`const` bindings).
- Semantic analysis and a static type checker: scopes, duplicate detection,
  arity and type checking, return-path verification, module import rules.
- Bytecode compiler with constant pooling, slot-allocated locals, globals
  initialised by a synthetic `__init__` function, and short-circuit codegen.
- `.sbc` format version 1.0: magic bytes, major/minor version, flags, CRC-32,
  constant pool, globals, function metadata and a source line table.
- Bytecode verifier: opcode/operand validation, jump-target checks, call arity
  checks, native resolution by name, abstract stack-depth analysis and resource
  limits. Deliberately corrupted files are covered by tests.
- Stack VM with explicit call frames (no host recursion), a call-depth limit and
  located runtime errors.
- Standard library: `core` (print, input, conversions, `len`, `range`, `push`,
  `keys`, `values`, `has`, `assert`, `type_of`), `math`, `string`,
  `collections`.
- CLI: `run`, `check`, `compile`, `run *.sbc`, `repl`, `fmt`, `test`,
  `--version`, `--help`. Unimplemented commands report that plainly.
- REPL with persistent globals and functions.
- Canonical formatter with `--check`; refuses to strip comments.
- Ten example programs, five Silica-level test files, 227 automated tests,
  benchmarks with a Python comparison.
- Documentation: language spec, grammar, bytecode format, standard library,
  performance measurements, bootstrap plan, roadmap.

### Notes
- The engine is written in Python. Rust is the planned target for the port; see
  `docs/ROADMAP.md`.
- Measured performance is 25×–85× slower than CPython on the benchmark suite;
  no speed claims are made. See `docs/PERFORMANCE.md`.
