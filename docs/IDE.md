# Script Mode IDE

A real editor and runner for `.sc` files, served locally by `silica ide`.

```bash
silica ide                 # opens the IDE for the current directory
silica ide --root ~/scripts
```

The terminal prints a URL with a session token. Open it, and you get a file list,
tabs, a highlighted editor, a Run button that executes the actual toolchain, and
a panel showing that run's real output, diagnostics and exit code.

---

## Why a browser and not a desktop app

The repository has no UI toolkit that reaches every target in the brief. tkinter
needs a display server, which Termux and a phone do not have; a native mobile IDE
would mean three codebases.

A browser is the one interface present on Linux, Ubuntu, Alpine, Windows, macOS,
Termux, Android and iOS. So the **editor** is HTML and the **runner** is Python,
and the two are separate layers because they reach different places:

| Layer | Runs where | What it needs |
|---|---|---|
| Editor | any browser | an HTTP connection to a runner |
| Runner | Python 3.9+ | the Silica package and the files |

On a laptop or in Termux both halves run on the same machine. On iOS, where no
Python process can exist, the browser can point at a runner elsewhere — that is an
explicit, token-authenticated choice, never an open service.

---

## What is real, and what is not

| Claim | Status |
|---|---|
| Create, open, edit, save `.sc` files | Works, tested |
| Run the current script through the real toolchain | Works, tested — real subprocess, real exit code |
| Actual stdout, stderr and exit code shown | Works, tested |
| Compile and runtime errors with `file:line:col` | Works, tested — parsed into clickable diagnostics |
| Jump to the error's location | Works (click a problem) |
| Stop a running script | Works, tested |
| Rerun after editing | Works — Run saves first, then executes |
| Multiple tabs, unsaved indicators | Works |
| Syntax highlighting from the real keyword table | Works — keywords come from `silica.tokens` |
| Line numbers, bracket-friendly editing, Tab inserts spaces | Works |
| Search and replace | **Not implemented** |
| Code folding | **Not implemented** |
| Autocomplete | **Not implemented** — the brief says do not advertise language intelligence that does not exist |
| Recent scripts list | Replaced by the workspace file list |
| Screenshots | None. No browser was available to capture one, so none is shown |

---

## Architecture

```
silica/ide/
  server.py     Workspace (path confinement), Runner (subprocess), HTTP routes
  app.html      the editor: markup, styles and JavaScript in one file
```

* **workspace** — resolves every path against the root and refuses anything that
  escapes it, including `..`, absolute paths and NUL bytes. Only `.sc` files can be
  written.
* **runner** — starts `python -m silica run <file>` as a subprocess with an
  argument array. There is no shell, so a filename cannot become a command. stdout
  and stderr are pumped on separate threads and streamed to the browser.
* **diagnostics** — `file.sc:12:4: parse error: ...` is parsed into
  `{path, line, col, kind, message}`; unparseable stderr is passed through as-is.
* **editor** — a `<textarea>` with a highlighted `<pre>` behind it. No editor
  library, no build step, no CDN.

### Finding the toolchain

The runner prepends the package's parent directory to `PYTHONPATH`, so
`python -m silica` works from a checkout as well as from an installed wheel.
Without that, a checkout would fail with `No module named silica` — which looks
like a broken IDE rather than a path problem.

---

## The API

Every request needs the session token (`?token=` or `X-Silica-Token`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | the editor page |
| GET | `/api/meta` | version, keywords, types, modules — read from the implementation |
| GET | `/api/files` | `.sc` files in the workspace |
| GET | `/api/file?path=` | read a file |
| POST | `/api/file` | write a file `{path, text}` |
| POST | `/api/run` | start `{path}` → `{id}` |
| GET | `/api/run?id=` | poll status, stdout, stderr, exit code, diagnostics |
| POST | `/api/stop` | stop `{id}` |

---

## Security

* binds to **127.0.0.1** by default; `--host 0.0.0.0` prints a warning
* a random 24-byte token per session, compared with `secrets.compare_digest`
* paths confined to the workspace root; `..` and absolute paths are refused
* no shell — argument arrays only
* opening a file never runs it; Run is always explicit
* no cloud account, no telemetry, no outbound network calls

The token is in the URL, so treat the URL as a credential. Anyone who has it can
edit and run files in that workspace.

---

## Platforms

| Platform | Editor | Runner | Verified here |
|---|---|---|---|
| Linux (Debian/Ubuntu) | yes | yes | **yes** — the API and runner were driven end to end |
| Termux (Android) | yes | yes | **no** — no device available |
| Alpine (musl) | yes | yes | **no** — pure Python, no compiled parts, but untested |
| macOS | yes | yes | **no** |
| Windows | yes | yes | **no** |
| iOS | yes (browser) | **no** — needs a runner elsewhere | **no** |

Pure Python with no third-party dependency, so nothing is architecture-specific.
That is a reason to expect it to work, not evidence that it does. Only the Linux
row was executed.

---

## Tests

`tests/test_ide.py` — 27 tests, all driving the real HTTP API:

```bash
python3 -m pytest tests/test_ide.py
```

They cover: token enforcement (three ways), path traversal in four forms, writing
outside the workspace, non-`.sc` writes, file create/read/save, listing, missing
files, metadata matching `silica.tokens`, the served page carrying its token and
referencing the endpoints it uses, a valid script's real output, the optimizer
being live, compile errors with parsed locations, runtime errors, missing scripts,
stopping a running script, and the CLI's own argument handling.

**Not tested: the rendered interface.** No browser exists in this environment, so
the front end is verified structurally and by hand. A visual check is the one
thing a reviewer should do that these tests cannot.

---

## Limits

* No search and replace, code folding or autocomplete.
* One workspace per server; no recent-files history.
* Run executes the whole file — there is no selection-run or REPL integration.
* Output is capped at 512 KB per stream and runs time out after 120 seconds.
* No syntax highlighting inside the output panel.
* The editor is a textarea: no multi-cursor, no column selection.
