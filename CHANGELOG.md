# Changelog

All notable changes to Silica are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning for its toolchain; the language surface is `0.x` until
`1.0.0`.

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
