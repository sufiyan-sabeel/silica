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
| Colour | **Works** — hex theme colours mapped to the terminal's palette, verified by reading SGR escapes from a pty |
| Mouse | **Works** — click to focus, click to activate, verified with a real SGR mouse event |
| Arrow keys | **Works** — including on terminals whose terminfo has no arrow capabilities (decoded by hand) |
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

### Focus

Focus has exactly one source of truth: the app's focus index, resolved by
`tui.focus(app)`. A widget never decides for itself whether it is focused — an
earlier version kept a per-widget flag that nothing set, so the marker never
moved.

* **up / down** move through focusable widgets (buttons, fields, lists,
  checkboxes); containers are skipped
* **left / right** are reserved for horizontal selectors
* focus wraps at both ends
* a disabled widget is skipped and drawn greyed
* **enter / space** activate the focused widget once — `tui.pressed(app)`
  returns the label and clears it, so one keypress cannot fire twice
* typing appends to a focused field; backspace deletes; delete clears

Arrow keys are decoded from their escape sequence by hand. curses only translates
them when the terminal's terminfo declares the capability, and on a minimal
terminfo it returns `ESC`, `[`, `B` as three keys — which silently broke arrow
navigation. The TUI now reads the sequence itself, so arrows work either way.

### Mouse

Where the terminal reports mouse events, **clicking a widget focuses it**, and
clicking a button activates it. If the terminal refuses mouse reporting,
`app.mouse` stays false and nothing else changes. There is no hover, no drag and
no wheel handling.

---

## The calculator example

`examples/tui_calculator.sc` is a working demonstration: two numeric fields, four
operation buttons, a result panel, input validation and division-by-zero
handling.

```bash
silica run examples/tui_calculator.sc --allow-tui
```

| Key | Action |
|---|---|
| Tab / up / down | move focus between the fields and the buttons |
| typing, backspace | edit the focused field |
| enter / space | run the focused operation |
| escape | clear both fields |
| q | quit |

The arithmetic lives in `compute(...)`, apart from rendering and event handling,
so it can be tested without a terminal.

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

The theme holds hex colours. Rendering emits a *style token* per segment and the
driver maps tokens to curses colour pairs at paint time, so a theme change is
visible on the next frame.

```silica
tui.theme(app, {"accent": "#45C6B0", "error": "#F87171"})
```

The default is a dark palette:

| Token | Colour | Used for |
|---|---|---|
| `background` | `#0B0D10` | the page behind widgets |
| `surface` | `#15191E` | widget fill |
| `border` | `#262C36` | panel borders and dividers |
| `text` | `#F3F4F6` | body text |
| `text_muted` | `#9CA3AF` | secondary text, disabled widgets |
| `accent` | `#45C6B0` | titles, focus |
| `error` | `#F87171` | errors |
| `success` | `#4ADE80` | success |
| `warning` | `#FBBF24` | warnings |

Named colours (`"cyan"`, `"red"`, …) are still accepted, so an older theme keeps
working.

### Colour fallback

`tui.colour_mode(app)` reports what the terminal supports:

| Mode | When | Behaviour |
|---|---|---|
| `256` | `COLORS >= 256` | nearest colour in the xterm-256 cube and grey ramp |
| `basic` | 8 or 16 colours | nearest of the eight ANSI colours |
| `none` | no colour support | default attributes; the layout is identical |

Mapping is nearest-colour, so `#45C6B0` becomes index 79 on a 256-colour
terminal and green on an 8-colour one. Nothing is hard-coded: every colour goes
through the theme.

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
