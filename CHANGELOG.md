# Changelog

All notable changes to Silica are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning for its toolchain; the language surface is `0.x` until
`1.0.0`.

## [0.8.0] — 2026-10-28

Script Mode IDE: a real editor and runner for `.sc` files, in the browser.

### Added
- **`silica ide`**: serves a local web IDE bound to 127.0.0.1 with a per-session
  token. File list, tabs, unsaved indicators, syntax highlighting driven by
  `silica.tokens`, line numbers, and a Run button.
- **The runner is the real toolchain.** `Run` starts `python -m silica run <file>`
  as a subprocess with an argument array — no shell — and streams that process's
  actual stdout, stderr and exit code. Stop terminates it.
- **Structured diagnostics.** `file.sc:12:4: parse error: ...` is parsed into
  `{path, line, col, kind, message}` and rendered as clickable problems that jump
  the editor to the location. Unparseable stderr passes through unchanged.
- **`silica/ide/`**: `Workspace` (path confinement), `Runner` (subprocess +
  polling), HTTP routes, and `app.html` — one self-contained page with no
  dependencies, no build step and no CDN.
- **27 tests** in `tests/test_ide.py`, driving the real HTTP API: token
  enforcement, path traversal in four forms, file CRUD, metadata taken from the
  implementation, real script output, compile and runtime errors with parsed
  locations, and stopping a running script.
- **`docs/IDE.md`**: architecture, API, security model, platform matrix.

### Fixed
- The runner prepends the package's parent directory to `PYTHONPATH`, so
  `python -m silica` works from a checkout as well as an installed wheel. Without
  it a checkout failed with `No module named silica`, which looked like a broken
  IDE rather than a path problem.
- `stop()` recorded the outcome itself instead of waiting for the executor thread
  to notice, so it can no longer return `running` after killing the process.

### Not implemented
- Search and replace, code folding, autocomplete.
- No screenshot: no browser exists in this environment to capture one.

### Platforms
- Linux was executed end to end. Termux, Alpine, macOS, Windows and iOS are
  expected to work — pure Python, no compiled parts — but were **not** run.

## [0.7.0] — 2026-10-28

A compile-time optimizer: constant folding. The first measured performance change
in the project, with the numbers and the command that produced them.

### Added — optimizer
- **`silica/optimizer.py`**: folds literal arithmetic, string concatenation and
  unary minus at compile time. `2 + 3 * 4` becomes one constant instead of four
  opcodes.
- Folding mirrors the VM exactly rather than using Python's semantics: `Int`
  wraps at 64 bits, `Bool` is not a number, integer division truncates toward
  zero, and mixed Int/Float promotes to Float. Where there is any doubt — division
  by a literal zero, non-finite floats, type combinations the VM would reject —
  it declines and the expression compiles as before, so the runtime error keeps
  its source location.
- **`SILICA_NO_OPT=1`** disables folding. This exists so the test suite can
  compare folded and unfolded programs against each other.
- **`benchmarks/optimizer.py`**: reproducible measurement of instructions, bytecode
  size and wall clock.

### Measured

| What | Folding off | Folding on | Change |
|---|---|---|---|
| Instructions, 200 literal expressions | 1602 | 402 | **−74.9%** |
| Bytecode, same program | 5214 B | 3145 B | **−39.7%** |
| Hot loop, 300k iterations | 3.496 s | 2.163 s | **−38.1%** |

Output is byte-identical in every case. A 200-expression program shows no
wall-clock gain because interpreter start-up dominates it; the hot loop is where
folding pays, and the changelog says so rather than quoting the best-looking
number.

### Tests
- **13 tests** in `tests/test_optimizer.py`, including a differential test: 32
  expressions are compiled with folding on and off and must produce identical
  stdout, stderr and exit code. That compares the optimizer against the VM rather
  than against a hand-written table of expected values.
- Regression test that every example still runs.

## [0.6.0] — 2026-10-27

Desktop GUI, and the audit the language roadmap asked for.

### Added — GUI
- **`use gui`** with `gui.lib.widgets`, `gui.lib.layout` and `gui.lib.theme`:
  windows, labels, headings, buttons with click handlers, text fields,
  checkboxes, rows, columns, spacers and colour tokens, backed by tkinter.
- **Click handlers are Silica functions by name** (`gui.on_click(button,
  "handle_click")`), resolved against the compiled chunk and run on a VM sharing
  the parent's globals and widget registry. No `eval`, no `exec`, no language
  change.
- **The `gui.run` capability** (`--allow-gui`) guards opening windows and running
  the loop. Building the tree needs no capability, so a headless machine can
  inspect a UI and gets a named error at `show`.
- **`gui.click(widget)`** activates a button through tkinter's own `invoke()`, so
  the path a test takes is the path a user takes.
- **`docs/GUI.md`**, `examples/gui_demo.sc`, and 19 tests in `tests/test_gui.py`,
  including a real window tier that opens a Tk window, invokes a real button and
  asserts the Silica handler ran.
- **`docs/AUDIT.md`**: the repository audit and prioritised roadmap requested by
  the language brief.

### Notes
- The namespace is `gui`, not `ui`: `ui` is the HTML/UI-DSL from 0.2.0, and giving
  `ui.app` a second meaning would have broken existing programs.
- CI now runs the suite under `xvfb-run` when it is available, so the window tests
  execute rather than skip.
- This environment had no python3-tk, no libtk8.6 and no X server, and no root to
  install them. Tcl/Tk and Xvfb were extracted from Debian packages into a local
  prefix and the X server's hard-coded `xkbcomp` path was redirected, which is
  what made the window tests possible. `docs/GUI.md` records this.

## [0.5.0] — 2026-10-27

Terminal UI, and two fixes to speech.

### Added — TUI
- **`use tui`** with `tui.lib.widgets`, `tui.lib.layout` and `tui.lib.style`:
  panels, headings, text, buttons, editable fields, lists, tables, dividers,
  spacers, rows and columns, drawn on curses with borders, focus and colour
  tokens.
- **`silica/tui/`**: a layout engine that renders a widget tree to plain text
  (testable with no terminal at all) and a curses driver that paints it, reads
  keys, handles resizing and restores the terminal.
- **The `tui.run` capability** (`--allow-tui`), needed to draw and read keys.
  Building widgets needs no capability.
- **`docs/TUI.md`** and `examples/tui_demo.sc`.
- 27 tests in `tests/test_tui.py`, the last tier of which runs a Silica program
  inside a pseudo-terminal, sends keys, and requires exit 0 with the terminal
  restored.

### Changed — speech
- **Pauses.** Synthesis now splits on sentences and on espeak's clause breaks and
  inserts silence between them (60 ms per clause, 140 ms per sentence). Before
  this the whole utterance was one unbroken run of phonemes, which is why it
  sounded rushed. Verified by measuring the gaps in the output audio.
- **STT decoding is deterministic**: `temperature=0` and
  `condition_on_previous_text=False`, which stops Whisper looping or inventing
  text on repeated phrases.

### Fixed
- `tui.field` is not called `input`, because `input` is a reserved Silica
  keyword.
- The TUI widget registry was module-global, so handles from one run leaked into
  the next — two programs in one process (the REPL) would have aliased each
  other's widgets. It is now per-VM.
- A capability error hint was double-formatting its string, raising `TypeError`
  instead of the intended message.

### Not implemented
- **GUI.** No `tkinter`, no display server, no way to install either in the build
  environment, so a window could not be opened or tested. `docs/GUI.md` records
  the constraint, the design it would follow, and how to unblock it.

## [0.4.0] — 2026-10-27

Speech: Silica can talk and listen, offline, with no API key.

### Added
- **`use speech`** with `speak`, `save`, `transcribe`, `voices`, `languages` and
  `status`. Text to speech and speech to text, callable from Silica source.
- **`silica/voice/`**: a Piper TTS frontend (ONNX + espeak-ng phonemes, no
  `piper-tts` dependency), a `faster-whisper` STT backend, a voice catalogue with
  on-demand download, and WAV plumbing with resampling.
- **Two new capabilities**: `speech.speak` and `speech.listen`, each scoped to
  directory roots and enforced by the VM before the function body runs.
- **`silica voice`** CLI: `list`, `languages`, `status`, `install`, `speak`,
  `transcribe`, `info`.
- **`docs/VOICE.md`**: engines, install for Linux and Termux, the language
  matrix, the round-trip verification and every limitation.
- 37 tests in `tests/test_voice.py`, in two tiers: the default tier needs no
  engine, and an opt-in tier synthesises a sentence and transcribes it back.

### Notes
- Speaking covers English, Hindi, Telugu, Bengali, Malayalam and Marathi. Piper
  has **no Tamil, Kannada, Gujarati or Punjabi voices**; listening covers those
  because Whisper is multilingual. The asymmetry is documented, not glossed over.
- `piper-tts` is deliberately not a dependency: its wheels are glibc-only and do
  not install in Termux. `onnxruntime` and espeak-ng are used directly, and both
  are Termux packages. The Termux path is untested on a device.
- Whisper defaults to `tiny` because `base` needs roughly a gigabyte of RAM.
- Audio output and input are capabilities, so a program with no grants cannot
  speak or listen.

## [0.3.0] — 2026-10-27

Global installation and distribution. Silica can now be installed with one
command on Linux and Termux, and the release artifacts are checksum-verified
before anything is written. No language, bytecode or VM change.

### Added — installation
- **`install.sh`** at the repository root: a POSIX `sh` installer that detects
  Termux vs desktop Linux and the CPU architecture, checks for Python 3.9+ and
  the `venv` module, downloads the release wheel **and** `SHA256SUMS.txt`, refuses
  to install on a checksum mismatch, installs into an isolated virtual
  environment, writes a `silica` launcher, and reports exactly what to add to
  `PATH` if needed. Idempotent: a second run is an upgrade. Never uses `sudo`
  unless `SILICA_SYSTEM=1` is set by a root user.
- **`uninstall.sh`**: removes only the paths recorded in the install manifest,
  refuses to delete a launcher it did not create, and refuses to delete a virtual
  environment outside the Silica home directory.
- **`docs/INSTALL.md`**: Ubuntu/Linux and Termux installation, upgrade, uninstall,
  PATH troubleshooting, the trust model, and the supported-platform matrix.
- **`docs/RELEASING.md`**: pre-release checks, version bumping, tagging, artifact
  verification and rollback.
- **`.github/workflows/release.yml`**: on a `v*` tag, runs the tests, checks the
  tag against the package version and the installer default, builds the wheel and
  sdist, generates the checksums and publishes the release.

### Added — command line
- **`silica file.sc`** runs a source file directly; `silica file.sbc` runs
  bytecode. Same code path as `silica run`, so capability flags behave
  identically.
- **`silica` with no arguments starts the interactive interpreter**, printing
  `Silica Interpreter v0.3.0` once and using `¢ ` as its prompt. `help`,
  `exit` and `globals` are its commands; `:help`, `:quit` and `:q` also work.

### Fixed
- A missing file in the direct form reports `error: no such file: x.sc` and exits
  1 — never a Python traceback.
- Invalid syntax reports `file:line:col` in the direct form too.
- Only `.sc` and `.sbc` arguments are treated as files, so a mistyped command is
  still reported as an unknown command.
- The interpreter prompt goes through a helper that switches an ASCII-only stdout
  to UTF-8, so a C locale cannot crash the session on the Cent sign.
- The installer neutralises an exported `PIP_USER=1` and a stray `PYTHONPATH`
  before calling pip, because both break installing into a virtual environment.

### Tests
- `tests/test_install.py`: 22 tests that run the real `install.sh` and
  `uninstall.sh` against throwaway homes and a wheel built from this checkout —
  install, run from outside the repository, interpreter start, idempotent rerun,
  Termux branch, verified download, tampered artifact refusal, and uninstall
  safety. Network-free: the release URL is overridden with a local `file://`
  directory, exercising the same download-and-verify path.

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
- `tests/test_assets.py` covering the asset files, the icon set, the
  editor manifests, the grammar's keyword coverage and the `hello.sc` check.

### Added — command line
- **`silica file.sc`** runs a source file directly; `silica file.sbc` runs
  bytecode. Both are the same code path as `silica run`, so capability flags
  (`--allow-fs-read` and friends) work identically.
- **`silica` with no arguments starts the interactive interpreter**, which prints
  `Silica Interpreter v0.2.1` once and then uses `\u00a2 ` as its prompt. `help`,
  `exit` and `globals` are its commands; `:help`, `:quit` and `:q` also work.
  Ctrl+D leaves the session.

### Fixed — command line
- A missing file in the direct form reports `error: no such file: x.sc` and exits
  1 — never a Python traceback.
- Invalid syntax reports `file:line:col` for the direct form too.
- Only `.sc` and `.sbc` arguments are treated as files, so a mistyped command is
  still reported as an unknown command rather than a missing file.
- The interpreter prompt is written through a helper that switches an ASCII-only
  stdout to UTF-8, so a C locale cannot crash the session on the Cent sign.

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
