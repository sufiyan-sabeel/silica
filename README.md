# Silica

A small, statically typed programming language with its own bytecode engine:
short keywords, braces, a real type checker, a versioned `.sbc` format, a
verifying VM, and a toolchain you can actually run.

```silica
sfn square(n: Int) -> Int {
    ret n * n
}

sfn main() {
    sprint(square(12))
}
```

```
$ silica run examples/square.sc
144
```

**Status: v0.1.0 — a working reference implementation, not a finished language.**
Everything documented here works and is covered by 227 automated tests. What is
planned but absent is listed in [Limitations](#limitations-and-what-is-not-done)
and in `docs/ROADMAP.md`. Nothing in this repository claims to be faster than
Python, C or Rust — see `docs/PERFORMANCE.md` for the measured truth.

## Quick start

Requires Python 3.9+ (the reference engine is written in Python; see
[Implementation language](#implementation-language)).

```bash
git clone https://github.com/sufiyan-sabeel/silica.git silica
cd silica

# run straight from the checkout
python3 -m silica run examples/hello.sc
python3 -m silica --version

# or install the `silica` command
pip install .
silica run examples/hello.sc

# or use the launcher without installing
sh bin/silica run examples/hello.sc
```

## Commands

| Command | What it does |
|---|---|
| `silica run <file.sc>` | Compile, verify and execute a source file. |
| `silica run <file.sbc>` | Verify and execute compiled bytecode. |
| `silica check <file.sc>` | Parse and type-check only; silent on success. |
| `silica compile <file.sc> [-o out.sbc]` | Write versioned bytecode next to the source. |
| `silica repl` | Interactive session with persistent globals and functions. |
| `silica fmt <file.sc> [--check]` | Rewrite in canonical style, or check without writing. |
| `silica test [dir]` | Run every `*_test.sc` under `dir` (default `tests`). |
| `silica --version` / `--help` | Version and usage. |

`silica new/add/remove/install/build` are **not implemented** (Milestone E) and
say so instead of pretending.

## The language in one page

| Purpose | Keyword | Example |
|---|---|---|
| Print a line | `sprint` | `sprint("hi")` |
| Print inline | `dit` | `dit("total: ")` |
| Read input | `input` | `let name: String = input("name? ")` |
| If / else | `si` / `sino` | `si x > 0 { ... } sino { ... }` |
| And / or / not | `und` / `ou` / `non` | `si ready und non blocked { ... }` |
| True / false | `oui` / `nein` | `let ok: Bool = oui` |
| While | `tant` | `tant n < 10 { n = n + 1 }` |
| For-each | `per` | `per item in [1, 2, 3] { ... }` |
| Function | `sfn` | `sfn add(a: Int, b: Int) -> Int { ret a + b }` |
| Return | `ret` | `ret n * n` |
| Import | `use` | `use math` |
| End a block | `fin` | optional, allowed before `}` |
| Stop the program | `halt` | `halt(2)` |

Bindings are `let` (mutable) or `const` (immutable); assignment is `x = expr`.
Blocks use braces. Every condition must be `Bool` — Silica has no truthiness.

Full details: `docs/LANGUAGE_SPEC.md`, grammar in `docs/GRAMMAR.md`, standard
library in `docs/STANDARD_LIBRARY.md`.

## Examples

Ten runnable programs live in `examples/`:

```bash
python3 -m silica run examples/conditionals.sc   # Pass
python3 -m silica run examples/loops.sc          # 55 / 5 4 3 2 1
python3 -m silica run examples/fibonacci.sc      # 0 1 1 2 3 5 8 13 21 34 55
python3 -m silica run examples/collections.sc    # lists, maps, sorting
python3 -m silica run examples/strings.sc        # split/join/upper
python3 -m silica run examples/math_demo.sc      # math module
python3 -m silica run examples/calculator.sc     # reads stdin
```

`examples/calculator.sc` in action:

```
$ printf '12\n*\n4\n' | python3 -m silica run examples/calculator.sc
first number: operator (+ - * /): second number: 48.0
```

## Architecture

```
source .sc
   │
   ├─ lexer            tokens with line/column          silica/lexer.py
   ├─ parser           AST                              silica/parser.py
   ├─ checker          scopes, symbols, static types     silica/checker.py
   ├─ compiler         bytecode + constant pool          silica/compiler.py
   ├─ serializer       .sbc v1.0, magic + version + CRC  silica/bytecode.py
   ├─ verifier         opcodes, operands, jumps, stack   silica/bytecode.py
   └─ VM               stack machine, explicit frames    silica/vm.py
```

* Locals are compiled to numbered slots; globals to a flat slot array initialised
  by a synthetic `__init__` function before `main` runs.
* Calls to user functions compile to a function index; calls to natives compile
  to (module name, function name) string constants, so a native is resolved and
  validated by name at load time.
* The verifier runs abstract stack-depth analysis over the control-flow graph
  before execution, and the compiler sizes each function's stack from that same
  analysis.
* Runtime errors carry a source line via a per-function line table.

Format details: `docs/BYTECODE.md`.

## Testing

```bash
python3 -m unittest discover -s tests -t .   # 227 tests
python3 -m silica test tests                 # Silica-level tests
python3 benchmarks/bench.py --runs 3         # benchmarks + correctness check
```

The suite covers the lexer, parser, checker, serializer, verifier (including
deliberately corrupted and hand-crafted invalid bytecode), VM semantics, every
CLI command, every example's documented output, and formatter idempotence.

## Implementation language

The original plan for Silica targets Rust. This repository ships a **Python
reference implementation**, which is what could be built and verified end to end
in the environment it was developed in (no Rust toolchain was available). The
`.sbc` format was designed to be implementation-neutral so a Rust engine can
consume the same files and be validated against this one. See
`docs/ROADMAP.md` (Milestone E) and `docs/PERFORMANCE.md`.

## Project layout

```
silica/            the engine package (lexer, parser, checker, compiler,
                   bytecode, vm, natives, fmt, cli, engine)
examples/          ten runnable programs with documented output
tests/             Python test suite + Silica-level *_test.sc files
benchmarks/        benchmark programs, Python equivalents and runner
docs/              language spec, grammar, bytecode, stdlib, performance,
                   bootstrap, roadmap
bin/silica         launcher for running from a checkout
pyproject.toml     packaging; installs the `silica` command
```

## Limitations and what is not done

* No generics: `List`/`Map` elements check as `Any`.
* No first-class functions, closures, user-defined types, enums or pattern
  matching.
* No exceptions, threads, `async`, file I/O, JSON, networking or process access.
* No package manager, no registry, no CI, no published releases yet.
* Silica UI (CSS-inspired styling) is a design goal, not code.
* Not self-hosted; the compiler is Python (`docs/BOOTSTRAP.md`).
* Slower than CPython on every measured workload (`docs/PERFORMANCE.md`).

## License and credits

MIT — see `LICENSE`. Creator: **Umaiz Sufiyan**. Contributions are welcome; read
`CONTRIBUTING.md` first.
