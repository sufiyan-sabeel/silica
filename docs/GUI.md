# GUI: not implemented, and why

This page exists because the request was for a GUI library alongside the TUI, and
pretending it shipped would be worse than saying it did not.

## Status

**No GUI library is implemented.** There is no `use gui`, no window, no widget
backend. Nothing in the repository claims otherwise.

## Why

A GUI needs a toolkit and a display server. Neither is available in the
environment this was built in, and neither can be installed there:

```
$ python3 -c "import tkinter"
ImportError: cannot import name '_tkinter'

$ echo $DISPLAY
<empty>

$ command -v Xvfb xvfb-run
(neither present)
```

There is no `sudo` and no `apt`, so `python3-tk` cannot be installed, and without
a display server there would be nothing to draw on even if it could. Every
candidate toolkit has the same problem: they all need a real window system.

## What the brief asked for, and what the constraint means

The requirement was explicit: a `.sc` program must open an **actual window**,
respond to **actual** interaction, and close cleanly — with automated tests, and
"no advertised feature is a placeholder".

Writing a tkinter backend here would produce code that had never once been run.
That is precisely the placeholder the brief forbids, and it would let the
documentation claim a working GUI on the strength of nothing. So it was not done.

## What it would take

The design is already settled by the TUI, and the GUI would mirror it:

1. A `silica/gui/` package with the same node tree and layout engine as
   `silica/tui/`, but a tkinter renderer instead of a curses one. The widget
   model, theming and event model are backend-independent by construction — the
   TUI proves that, because its layout engine already renders to plain text with
   no terminal involved.
2. A `gui` native namespace mirroring `tui`: `gui.app`, `gui.window`,
   `gui.text`, `gui.button`, `gui.field`, `gui.checkbox`, `gui.add`, `gui.show`,
   `gui.run`, `gui.close`.
3. The `gui.run` capability, which already exists in the capability model and is
   registered (`--allow-gui`), so the security boundary is ready.
4. Tests: the layout tier runs anywhere; the window tier needs
   `xvfb-run -a python -m silica run app.sc --allow-gui` on a machine with
   tkinter, and would assert window creation, widget presence, a synthesised
   click reaching the program, and clean shutdown.

That is a focused piece of work — roughly the size of the TUI — and it is
blocked on one thing only: an environment where a window can actually open.

## How to unblock it

Any of these makes the GUI implementable and testable:

```bash
# Debian/Ubuntu, on a machine you control
sudo apt install python3-tk xvfb
xvfb-run -a python -m silica run app.sc --allow-gui
```

or run the build in an environment that already has tkinter (most desktop Python
installations do) and a virtual display.

Say the word once that exists and the GUI can be built against the same
node-tree and layout engine the TUI uses, with the same three-tier test
structure.
