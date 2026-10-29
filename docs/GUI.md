# GUI: real desktop windows

Silica opens real windows through **tkinter**. Labels, buttons with working click
handlers, text fields, checkboxes, rows, columns, spacing, colours and a clean
lifecycle — driven from Silica source.

```silica
use gui
use gui.lib.widgets

sfn handle_click() {
    sprint("Button clicked")
}

sfn main() {
    let app = gui.app("Silica GUI")
    let window = gui.window(app, "Hello Silica", 640, 420)
    gui.add(window, gui.heading("Hello from Silica"))
    gui.add(window, gui.button("Click me"))
    gui.on_click(button, "handle_click")
    gui.show(window)
    gui.run(app)
}
```

```bash
silica run examples/gui_demo.sc --allow-gui
```

---

## What is real, and what is not

| Claim | Status |
|---|---|
| Real window creation and closing | Works — verified by opening a Tk window |
| Window title, size | Works |
| Labels, buttons, text fields, checkboxes | Works |
| Click handlers that call Silica functions | Works — verified by invoking a real button |
| Rows, columns, spacing | Works |
| Colour theme tokens | Works |
| Resizing, minimum dimensions | Tk default behaviour; no explicit API |
| Menus and dialogs | **Not implemented** |
| Accessibility | **Not addressed** — no roles, no screen-reader work |
| macOS / Windows | Untested. tkinter is cross-platform, but nothing here was run there |
| Termux / Android | **Not supported** — no X server |

---

## Backend status

| Backend | Status |
|---|---|
| tkinter (desktop) | **Implemented and tested** on Linux with a virtual display |
| Android native | **Not implemented.** No Android UI toolkit is reachable from a Termux Python process; a real backend would need an Android app hosting the runtime |
| Web (browser) | Implemented separately as the Script Mode IDE (`docs/IDE.md`), not as a `gui` backend |

The shared layer is the widget tree, the theme tokens and the layout rules; the
tkinter backend only paints them. A second backend would implement the same
small interface (`build`, `run`, `close`) without touching the model.

---

## Why `gui` and not `ui`

The brief's example used `ui.app(...)` for a desktop application. `ui` was
already taken: it is the HTML/UI-DSL namespace from 0.2.0, where `ui.app` builds a
web node tree that `ui.render` turns into HTML. Giving that name a second, window-
based meaning would silently break every existing `ui` program.

So desktop windows live in `gui`, and `ui` keeps its meaning. Everything else
follows the brief's shape: `gui.window(app, title, w, h)`, `gui.add`,
`gui.on_click`, `gui.show`, `gui.run`.

---

## Click handlers

`gui.on_click(button, "handle_click")` takes the **name** of a Silica function.
Silica has no first-class functions, so the runtime resolves the name against the
compiled chunk — it is not `eval` and not `exec`. The chunk already contains the
function; the VM is asked to run it.

The handler runs on a short-lived VM that shares the parent's global slots and its
widget registry, so a handler can reach the same widgets:

```silica
sfn on_press() {
    gui.set_text(label, "pressed")
}
```

**Locals do not persist between invocations** — a handler that needs state must
put it in a global.

---

## Layout

* a **window** stacks its children vertically
* a **row** puts children side by side; a **column** stacks them
* a **spacer** adds a vertical gap

There is no constraint solver and no grid. Tk packs widgets in order, which is
predictable and enough for forms and panels.

---

## Theming

```silica
gui.theme(app, {"accent": "#2F6F5E", "surface": "#FFFFFF"})
```

Tokens: `background`, `surface`, `text`, `text_muted`, `accent`, `border`,
`error`. `gui.status()` reports whether tkinter and a display are actually
available before you build anything.

---

## Security and headless behaviour

Opening a window needs the `gui.run` capability:

```bash
silica run app.sc --allow-gui
```

Building the widget tree needs **no** capability, so on a headless machine you can
still construct and inspect a UI:

```
$ silica run app.sc          # no DISPLAY
["heading", "text", "field", "checkbox", "button"]
app.sc:20: runtime error: gui.show: tkinter is present but cannot load its Tk
libraries (libtk8.6.so: cannot open shared object file). On Debian/Ubuntu:
sudo apt install python3-tk libtk8.6
```

The tree is built, the failure is named, and there is no traceback. The core CLI
is unaffected: `silica check`, `fmt` and `test` never touch a display.

---

## Dependencies

| Platform | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install python3-tk` |
| Fedora | `sudo dnf install python3-tkinter` |
| Arch | `sudo pacman -S tk` |
| Termux | not supported (no X server) |

---

## Testing

`tests/test_gui.py`, two tiers:

1. **Tree and bridge** — build widgets, wire handlers, validate arguments, check
   the errors. No display needed; runs anywhere.
2. **Real windows** — creates an actual Tk window, checks the widgets are there,
   invokes a real button and asserts the Silica handler ran, then closes. Skipped
   when there is no display.

```bash
xvfb-run -a python -m pytest tests/test_gui.py     # with a virtual display
```

That is how it was verified here. This environment had no `python3-tk`, no
`libtk8.6`, no X server and no root, so Tcl/Tk and Xvfb were extracted from
Debian packages into a local prefix, `LD_LIBRARY_PATH`/`TCL_LIBRARY` were pointed
at them, and the X server's hard-coded `xkbcomp` path was redirected to a writable
directory. Under that setup the window tests run for real: a window opens, a click
reaches a Silica function, and the window closes.

CI runs the suite under `xvfb-run` so the window tier executes there too.

---

## Limits

* **No menus or dialogs.**
* **No accessibility work** — no ARIA-equivalent roles, no screen-reader testing.
* **No image or canvas widgets.**
* **One window is focused** in `gui.run`; multiple windows are created but only
  the first is driven by the loop.
* **Handler locals do not persist.**
* **Untested on macOS and Windows.**
