<p align="center"><img src="assets/logo/silica-logo.png" alt="Silica" width="440"></p>

# Silica

A small, statically typed programming language with its own bytecode engine:
short keywords, braces, a real type checker, a versioned `.sbc` format, a
verifying VM, a toolchain you can actually run, and a UI DSL that renders to
HTML/CSS.

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

**Status: v0.8.0 — a working reference implementation, not a finished language.**
Everything documented here works and is covered by 614 automated tests. What is
planned but absent is listed in [Limitations](#limitations-and-what-is-not-done)
and in `docs/ROADMAP.md`. Nothing in this repository claims to be faster than
Python, C or Rust — see `docs/PERFORMANCE.md` for the measured truth.

## Install

**Linux and Termux, one command:**

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
```

It detects the platform, checks for Python 3.9+, downloads the release wheel,
**verifies its SHA-256** against the published checksum, installs into an isolated
virtual environment and puts `silica` on your `PATH`. No `sudo`, safe to re-run,
and `uninstall.sh` removes exactly what it created.

```bash
silica                  # interactive interpreter
silica hello.sc         # run a file
silica --version
```

**Termux** (native, no proot, no sudo):

```bash
pkg update && pkg install python git curl
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
```

**From source**, if you would rather read what you install:

```bash
git clone https://github.com/sufiyan-sabeel/silica.git
cd silica && python3 -m venv .venv && . .venv/bin/activate
pip install .
```

Piping a script into a shell is not risk-free, and this project does not claim it
is. `install.sh` is short, downloads only from this repository's releases over
HTTPS, and refuses to install an artifact whose checksum does not match. Full
detail, the trust model, Termux caveats and troubleshooting:
**[docs/INSTALL.md](docs/INSTALL.md)**. Release and verification procedure:
**[docs/RELEASING.md](docs/RELEASING.md)**.

## Quick start

Requires Python 3.9+ (the reference engine is written in Python; see
[Implementation language](#implementation-language)).

```bash
git clone https://github.com/sufiyan-sabeel/silica.git silica
cd silica

# run a file directly — no `run` needed
python3 -m silica examples/hello.sc

# or start the interactive interpreter
python3 -m silica

# or install the `silica` command
pip install .
silica examples/hello.sc
silica                       # interactive interpreter

# or use the launcher without installing
sh bin/silica examples/hello.sc
```

### The interpreter

`silica` with no arguments starts the interactive interpreter. It prints its
version once, then uses `¢ ` as the prompt:

```console
$ silica
Silica Interpreter v0.8.0
¢ let n: Int = 21
n: Int = 21
¢ n * 2
42
¢ sfn twice(x: Int) -> Int {
¢     ret x * 2
¢ }
defined twice
¢ twice(5)
10
¢ exit
```

Globals and functions persist for the session; errors are reported and the
session continues. `help`, `exit` and `globals` are the three commands
(`:help`, `:quit` and `:q` also work), and Ctrl+D leaves the session.

The prompt is the Cent sign, so the terminal needs a UTF-8 capable encoding. If
stdout is ASCII-only — a C locale, say — the interpreter switches the stream to
UTF-8 rather than crashing, and falls back to `> ` only if it cannot.

## Commands

| Command | What it does |
|---|---|
| `silica <file.sc>` | Run a source file directly. Same as `silica run`. |
| `silica <file.sbc>` | Verify and execute compiled bytecode directly. |
| `silica` | Start the interactive interpreter. |
| `silica run <file.sc>` | Compile, verify and execute a source file. |
| `silica run <file.sbc>` | Verify and execute compiled bytecode. |
| `silica check <file.sc>` | Parse and type-check only; silent on success. |
| `silica compile <file.sc> [-o out.sbc]` | Write versioned bytecode next to the source. |
| `silica repl` | Interactive session with persistent globals and functions. |
| `silica fmt <file.sc> [--check]` | Rewrite in canonical style, or check without writing. |
| `silica test [dir]` | Run every `*_test.sc` under `dir` (default `tests`). |
| `silica capabilities` | Print the effective capability set for a set of flags. |
| `silica ide` | Script Mode IDE in your browser. |
| `silica voice list` | Voices available, and which are installed. |
| `silica voice install <name>` | Download a voice into the cache. |
| `silica voice speak "text"` | Synthesise and play; `--out PATH` writes a WAV instead. |
| `silica voice transcribe <file.wav>` | Transcribe an audio file. |
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

Fifteen runnable programs live in `examples/`:

```bash
python3 -m silica run examples/conditionals.sc   # Pass
python3 -m silica run examples/loops.sc          # 55 / 5 4 3 2 1
python3 -m silica run examples/fibonacci.sc      # 0 1 1 2 3 5 8 13 21 34 55
python3 -m silica run examples/collections.sc    # lists, maps, sorting
python3 -m silica run examples/strings.sc        # split/join/upper
python3 -m silica run examples/math_demo.sc      # math module
python3 -m silica run examples/json_demo.sc      # JSON parse/serialise
python3 -m silica run examples/calculator.sc     # reads stdin
python3 -m silica run examples/fs_demo.sc --allow-fs-read examples --allow-fs-list examples
python3 -m silica run examples/ui_hello.sc   --allow-fs-write build   # UI -> HTML/CSS
python3 -m silica run examples/ui_tasks.sc   --allow-fs-write build   # events + list
python3 -m silica run examples/ui_animate.sc --allow-fs-write build   # reduced motion
```

`examples/calculator.sc` in action:

```
$ printf '12\n*\n4\n' | python3 -m silica run examples/calculator.sc
first number: operator (+ - * /): second number: 48.0
```

## Editor support and brand assets

The logo lives in `assets/logo/` — the mark, the wordmark, a transparent symbol,
a monochrome variant and a full icon set (16–512px plus `favicon.ico`), all
cropped from the original brand sheet with the design and colours untouched. See
`assets/logo/README.md` for what each file is and the exact colour values.

`.sc` files get the Silica icon in VS Code via `editors/vscode/`, which registers
the `silica` language for `.sc`, contributes a TextMate grammar and contributes a
file icon theme mapping `sc` to the mark. Install it with `vsce package` +
`code --install-extension`, then pick **Silica File Icons** in
*Preferences: File Icon Theme*.

Two things worth knowing:

* **This repository has no editor of its own.** It is a CLI toolchain plus a web
  renderer, so there is no in-project file tree, tab strip or icon theme to
  integrate with. VS Code is where `.sc` files actually get opened, so the
  extension is a new sub-project rather than a change to something existing.
* **A file icon theme is all-or-nothing.** Enabling it replaces your current icon
  theme for every file type, and unmapped files fall back to VS Code's built-in
  icons. `editors/vscode/README.md` shows how to copy just the `.sc` entry into
  your own theme instead.

Rendered Silica UI pages can carry the mark too: `ui.render({..., favicon: oui})`
embeds a 32px copy as a data URI, so the page stays self-contained.

## Performance, measured

Silica is **not** fast. It is a bytecode VM written in Python, and the benchmark
suite says so plainly: it runs 40–90× slower than CPython on arithmetic,
recursion, collections and strings. `docs/AUDIT.md` records the numbers and
`benchmarks/bench.py` reproduces them.

What has changed is that there is now an optimizer. Constant folding runs at
compile time:

```
$ python3 benchmarks/optimizer.py
instructions   off: 1602    on: 402     (-74.9%)
bytecode       off: 5214B   on: 3145B   (-39.7%)
hot loop       off: 3.477s  on: 2.113s  (-39.2%)   output identical
```

Folding mirrors the VM's arithmetic exactly — 64-bit wrapping, integer division
truncating toward zero, mixed Int/Float promoting — and declines whenever the
result would differ from what the VM produces. `SILICA_NO_OPT=1` turns it off,
which is how the differential test compares the two.

## Script Mode IDE

`silica ide` serves a real editor and runner for `.sc` files in your browser.

```bash
silica ide                    # current directory
silica ide --root ~/scripts   # a workspace
```

File list, tabs, syntax highlighting driven by the compiler's own keyword table,
and a **Run** button that executes the actual toolchain — you see the real stdout,
stderr, exit code and clickable `file:line:col` diagnostics. Stop works, and Run
saves before executing.

The editor is HTML so it runs on any browser, including a phone; the runner is
Python, so it stays where your files are. On iOS the browser can point at a runner
on another machine instead — explicitly, with a session token, never as an open
service.

No dependencies, no build step, no cloud account. `docs/IDE.md` covers the API,
the security model, and what is honestly not there yet (search and replace,
folding, autocomplete).

## Desktop and terminal UI

Real terminal applications on `curses` — no dependency beyond the standard
library:

```silica
use tui
use tui.lib.widgets

sfn main() {
    let app = tui.app("Silica Terminal")
    let panel = tui.panel("Welcome to Silica")
    tui.add(panel, tui.heading("Silica TUI"))
    tui.add(app, panel)
    tui.add(app, tui.button("Continue"))
    tui.run(app)
}
```

```bash
silica run examples/tui_demo.sc --allow-tui
```

Panels, headings, text, buttons, editable fields, lists, tables, borders, colour
tokens, arrow-key focus, resizing and clean terminal restore. Events are polled
rather than dispatched through callbacks, because Silica has no first-class
functions and re-entering the VM mid-instruction is not worth the risk — the
program drives the loop and reads key names. `docs/TUI.md` has the details.

**GUI** is real too, through tkinter: windows, labels, buttons with working click
handlers, fields, checkboxes, rows and columns.

```silica
use gui

sfn main() {
    let app = gui.app("Silica GUI")
    let window = gui.window(app, "Hello Silica", 640, 420)
    gui.add(window, gui.heading("Hello from Silica"))
    gui.show(window)
    gui.run(app)
}
```

```bash
silica run examples/gui_demo.sc --allow-gui
```

Click handlers are named Silica functions (`gui.on_click(button, "handle_click")`),
resolved against the compiled chunk — not `eval`. The widget tree builds without a
display, so a headless machine can inspect a UI and gets a clear error at `show`.
`docs/GUI.md` covers the details, and why the namespace is `gui` rather than `ui`.

## Speech

Silica can talk and listen, offline, with no API key. Both directions are
ordinary Silica modules:

```silica
use speech

sfn main() {
    speech.save("Silica can talk.", "out/hello.wav")
    sprint(speech.transcribe("out/hello.wav"))
}
```

```bash
silica voice install en_US-lessac-medium      # one 63 MB download, once
silica voice speak "Silica can talk." --out out/hello.wav
silica voice transcribe out/hello.wav
```

**Speaking** uses Piper voices — a neural ONNX model driven by espeak-ng
phonemes. It deliberately does not depend on the `piper-tts` wheel, which is
glibc-only and cannot be installed in Termux; instead it needs `onnxruntime` and
an espeak-ng library, both of which Termux packages.

**Listening** uses Whisper through `faster-whisper`, which Termux also packages
(`ctranslate2`).

**Languages, honestly.** Piper has voices for English, Hindi, Telugu, Bengali,
Malayalam and Marathi. It has **no Tamil, Kannada, Gujarati or Punjabi** voices.
Whisper is multilingual, so *listening* covers those languages even though
*speaking* does not — the two directions are not symmetric, and
`silica voice languages` prints exactly what exists.

**How good is the voice?** It is a neural voice: clearly better than formant
synthesis, not as natural as a large cloud model. The check that means something
is the round trip — synthesise a sentence, transcribe it, compare — and for
English it comes back word for word. That measures intelligibility, not beauty.

Audio output and audio input are privileged, so they are capabilities:
`speech.speak` and `speech.listen`, granted per directory like `fs.*`.

Full guide: `docs/VOICE.md`.

## Capabilities and file access

A Silica program has **no capabilities by default**. It can compute, print and
read stdin; it cannot open a file. File access is a named capability, granted
outside the program and scoped to a directory:

```bash
silica run app.sc --allow-fs-read data --allow-fs-write out
silica run app.sc --capabilities caps.toml
silica capabilities --allow-fs-read data      # show the effective set
```

```silica
use fs

sfn main() {
    si fs.exists("data/notes.txt") {
        sprint(fs.read_text("data/notes.txt"))
    }
}
```

Three capabilities exist: `fs.read`, `fs.write`, `fs.list`. A grant covers one
root path and its subtree; symlinks are resolved before the check, so a link
inside the root that points outside it is refused. `--deny-fs-read` removes a
capability a config file granted, because deny always wins.

The check is enforced at the VM's native dispatch point, not inside the
filesystem functions: each privileged native declares the capability it needs,
the VM authorises the call, and the native receives the path that was actually
authorised. See `docs/STANDARD_LIBRARY.md` and `SECURITY.md`.

## Silica UI

Silica UI is real Silica — no template language, no markup blobs. A builder block
is a call followed by a `{ ... }` body, and the widgets inside it are ordinary
statements:

```silica
use ui
use ui.lib.widgets

sfn main() {
    let tasks: List = ["Design tokens", "Responsive layout"]

    ui.app("Tasks") {
        ui.screen({padding: {sm: "12px", md: "24px"}}) {
            ui.row({gap: "12px", align: "center"}) {
                ui.text("Tasks", {size: "xl", weight: "600"})
                ui.spacer()
                ui.button("Toggle theme") {
                    ui.on("click") {
                        ui.state.toggle("dark")
                    }
                }
            }
            ui.lib.widgets.scroll({direction: "vertical"}) {
                ui.lib.widgets.list(tasks) {
                    ui.card({padding: "12px"}) {
                        ui.text(item)
                    }
                }
            }
        }
    }

    ui.render({target: "web", out: "build/index.html"})
}
```

```bash
silica run examples/ui_tasks.sc --allow-fs-write build
# wrote build/ui_tasks.html, build/theme.css, build/silica-ui-runtime.js
```

Three grammar additions made this possible, all provably additive — every new
form was a parse error or a type error in 0.1.x:

1. **Dotted imports**: `use ui.lib.widgets`.
2. **Member-path resolution**: longest imported prefix is the module, one member
   follows it.
3. **Builder blocks**: `call { ... }` in statement position, block on the same
   line as the call.

**The honest execution model.** The browser cannot run Silica — the VM is
Python-hosted with no JS or WASM backend. Event bodies are therefore a restricted
action subset (`ui.state.set/toggle/push`, `ui.navigate`, `ui.toggle`) compiled to
a declarative JSON program that a small bundled runtime interprets. Anything
beyond that runs at build time or not at all. Real client-side Silica needs a
WASM build of the VM and is not scheduled.

**The web renderer is the only renderer.** Android, iOS, desktop, terminal and
the framework adapters are specified names that fail loudly, never fake backends.
Layout is CSS — flexbox and grid do the work; the tests assert emitted structure
and CSS rules, not pixels.

**Writing needs a capability.** `ui.render` requires `fs.write` for its output
path, the same capability `fs` uses. A program with no grants cannot write a
file, and that includes a rendered page.

Full reference: `docs/UI.md`.

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
python3 -m unittest discover -s tests -t .   # 614 tests
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
                   bytecode, vm, natives, capabilities, stdlib_fs,
                   stdlib_json, fmt, cli, engine)
silica/ui/         the UI core: node tree, theme, style model, web
                   renderer and the ui.* native functions
silica/voice/      speech: Piper TTS, Whisper STT, the voice catalogue and
                   the speech.* native functions
silica/tui/        terminal UI: widget tree, layout engine, curses driver and
                   the tui.* native functions
silica/gui/        desktop windows: tkinter backend, click handlers and the
                   gui.* native functions
silica/ide/        Script Mode IDE: workspace, subprocess runner, HTTP API and
                   the single-page editor
examples/          fifteen runnable programs with documented output
assets/logo/       the Silica mark, wordmark and icon set
editors/vscode/    VS Code extension: .sc language + file icon
install.sh         Linux/Termux installer (checksum-verified)
uninstall.sh       removes exactly what install.sh created
tests/             Python test suite + Silica-level *_test.sc files
benchmarks/        benchmark programs, Python equivalents and runner
docs/              language spec, grammar, bytecode, stdlib, UI, install,
                   releasing, performance, bootstrap, roadmap
bin/silica         launcher for running from a checkout
pyproject.toml     packaging; installs the `silica` command
```

## Limitations and what is not done

* No generics: `List`/`Map` elements check as `Any`.
* No first-class functions, closures, user-defined types, enums or pattern
  matching.
* No exceptions, threads, `async`, networking or process access.
* File I/O exists but only behind an explicit capability grant; there is no
  ambient authority and no network or environment access at all.
* No package manager and no registry.
* Silica UI ships one renderer (web). No native, terminal or OS-UI target, no
  framework adapters, no client-side Silica, no virtualized lists, no 3D.
* Not self-hosted; the compiler is Python (`docs/BOOTSTRAP.md`).
* Slower than CPython on every measured workload (`docs/PERFORMANCE.md`).

## License and credits

MIT — see `LICENSE`. Creator: **Umaiz Sufiyan**. Contributions are welcome; read
`CONTRIBUTING.md` first.
