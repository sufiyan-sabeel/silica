# TUI: terminal applications

Silica builds real terminal applications on `curses`. Panels, headings, buttons,
editable fields, lists, tables, borders, focus, key handling, resizing and clean
shutdown — all driven from Silica source.

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

---

## What is real, and what is not

| Claim | Status |
|---|---|
| Widgets, layout, borders, focus | Works; tested without a terminal |
| Real keyboard input, arrow-key focus | Works; tested through a pseudo-terminal |
| Resizing | Works; `KEY_RESIZE` becomes the `"resize"` event |
| Clean shutdown and terminal restore | Works; tested — the alternate screen is entered and left |
| Colour | Uses curses colours when the terminal reports them |
| GUI (windows) | **Not implemented.** See `docs/GUI.md` for why |

---

## The event model

Events are **polled**, not dispatched through callbacks. Silica has no
first-class functions, and calling a Silica function from inside a native would
mean re-entering the VM in the middle of an instruction — a change to the
execution model this feature does not justify.

So the program drives the loop:

```silica
tant oui {
    let key = tui.poll(app)      # blocks for one key, redraws, returns its name
    si key == "q" {
        tui.close(app)
        halt
    }
    si key == "enter" {
        sprint("selected: " + tui.selected(app))
    }
}
```

That is a real event loop with real key handling, and it needs no new language
features. `tui.run(app)` is the convenience form when a program only needs a quit
key.

### Key names

| Key | Name |
|---|---|
| Printable characters | the character, e.g. `"a"` |
| Enter | `"enter"` |
| Arrows | `"up"`, `"down"`, `"left"`, `"right"` |
| Tab | `"tab"` |
| Backspace | `"backspace"` |
| Page up / down, Home, End | `"pageup"`, `"pagedown"`, `"home"`, `"end"` |
| Terminal resized | `"resize"` |
| Ctrl-C, Ctrl-D | `"ctrl-c"`, `"ctrl-d"` |

Arrow keys move focus between focusable widgets (buttons, fields, lists).
Typing into a focused field appends; backspace deletes. `tui.selected(app)`
returns the focused widget's text, or a field's current value.

---

## Widgets

| Function | Result |
|---|---|
| `tui.app(title)` | the application |
| `tui.panel(title)` | bordered container with a title |
| `tui.text(s)` | one line |
| `tui.heading(s)` | one line, rendered upper-case |
| `tui.button(label)` | focusable button, drawn as `[ label ]` |
| `tui.field(placeholder)` | editable single-line field |
| `tui.list(items)` | focusable list |
| `tui.table(rows)` | rows of columns; first row is the header |
| `tui.divider()` | rule across the width |
| `tui.spacer(n)` | vertical gap |
| `tui.row()` / `tui.column()` | horizontal / vertical containers |
| `tui.add(parent, child)` | attach a child |

`tui.field` is not called `input` because `input` is a reserved Silica keyword.
That is the only place the API bends to the language.

Containers that accept children: `app`, `panel`, `row`, `column`. Adding a child
to a leaf (`text`, `button`, `field`, `divider`, `spacer`, `list`, `table`) is a
runtime error rather than a silent no-op.

---

## Layout

Layout is a simple, predictable flow:

* a **column** stacks its children, each at its natural height
* a **row** places children side by side with equal widths
* a **panel** adds a one-character border and a title, and gives its children the
  space inside
* heights: text/heading/button/field/divider are 1; a list is its item count (or
  `height` if set); a table is 1 + its rows; a panel is its content + 2

Content that does not fit is clipped, never wrapped over the edge.

---

## Theming

Semantic tokens, mapped per backend:

```silica
tui.theme(app, {"accent": "magenta", "text": "white"})
```

Tokens: `background`, `surface`, `text`, `text_muted`, `accent`, `border`,
`error`, `success`, `focus`. `tui.tokens(app)` reads them back. A terminal
without colour support simply gets default attributes — nothing fails.

---

## Security

Drawing to the terminal and reading keys is a privileged act, so it needs the
`tui.run` capability:

```bash
silica run app.sc --allow-tui
```

Building widgets needs no capability; only `tui.render`, `tui.poll` and
`tui.run` do. Without the grant:

```
app.sc:6: capability error: capability 'tui.run' (draw to the terminal and read
keys) is not granted
  hint: grant it with --allow-tui; Silica grants nothing by default
```

`tui.run` and `tui.poll` take no directory: they grant the facility, not a path.

---

## Errors

| Situation | What happens |
|---|---|
| No terminal (stdin or stdout is not a tty) | clear error, not a hang |
| `curses` unavailable | clear error naming the module |
| A program that is not a widget passed to `add` | located runtime error |
| A leaf widget given a child | located runtime error |
| `tui.list` given a non-List | type error at compile time |

The core CLI stays usable on headless devices: nothing outside `tui.*` needs a
terminal, and `silica check`/`fmt`/`test` never touch one.

---

## Testing

`tests/test_tui.py`, in three tiers:

1. **Layout and rendering** — the tree becomes text with no terminal involved, so
   it runs anywhere including CI with `TERM=dumb`.
2. **The Silica bridge** — imports resolve, natives carry the right capability,
   arguments are validated, errors are located.
3. **A real terminal** — a pseudo-terminal is opened, a Silica program runs inside
   it, keys are sent, and the program must exit 0 with the terminal restored.

Tier 3 is the one that proves it works as a terminal application. It checks the
alternate screen is entered and left, that typed characters reach the program,
and that a program exits on its quit key.

---

## Limits

* **Terminal only.** There is no GUI; see `docs/GUI.md`.
* **No scrolling beyond a list's window.** `list` renders a slice, but there is
  no scroll bar or mouse support.
* **No mouse events.**
* **Focus is linear.** No spatial navigation or custom tab order.
* **One application per program.** Two `tui.app` calls in one run share the
  terminal state; the second `run` will fight the first.
* **Not tested on Termux**, though `curses` is part of Python and the code has no
  dependency beyond it.
