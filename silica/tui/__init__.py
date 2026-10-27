"""The Silica TUI: real terminal applications, built on curses.

Two layers, deliberately separated:

* a **layout engine** that turns a widget tree into lines of text plus style
  runs. It touches no terminal, so the whole layout and rendering path is
  testable without a pty, and it works even when `TERM` is `dumb`.
* a **terminal driver** on curses that paints those lines, reads keys, handles
  resizing and restores the terminal on the way out.

Events are polled rather than dispatched through callbacks. Silica has no
first-class functions, and calling a Silica function from inside a native would
mean re-entering the VM mid-instruction — a change to the execution model that
this feature does not justify. Instead the program drives the loop::

    let app = tui.app("Demo")
    tui.add(app, tui.heading("Hello"))
    tant oui {
        let key = tui.poll(app)
        si key == "q" { halt }
        si key == "enter" { sprint("pressed enter") }
    }

That is a real event loop with real key handling, and it needs no new language
features. `tui.run(app)` is the convenience form for programs that only need a
quit key.
"""

import os
import sys

BORDER = "\u2500"
VERTICAL = "\u2502"
TOP_LEFT = "\u250c"
TOP_RIGHT = "\u2510"
BOTTOM_LEFT = "\u2514"
BOTTOM_RIGHT = "\u2518"

# Semantic colour tokens, mapped per backend. A terminal without colour support
# simply gets the default attributes; nothing fails.
DEFAULT_THEME = {
    "background": "default",
    "surface": "default",
    "text": "default",
    "text_muted": "cyan",
    "accent": "cyan",
    "border": "cyan",
    "error": "red",
    "success": "green",
    "focus": "reverse",
}

COLOURS = {
    "black": 0, "red": 1, "green": 2, "yellow": 3, "blue": 4,
    "magenta": 5, "cyan": 6, "white": 7, "default": 0,
}


class TUIError(RuntimeError):
    pass


class Node:
    __slots__ = ("kind", "text", "props", "children", "parent", "focused",
                 "value", "items", "rows", "scroll")

    def __init__(self, kind, text="", props=None):
        self.kind = kind
        self.text = text
        self.props = dict(props or {})
        self.children = []
        self.parent = None
        self.focused = False
        self.value = ""
        self.items = []
        self.rows = []
        self.scroll = 0

    def add(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def walk(self):
        yield self
        for child in self.children:
            for node in child.walk():
                yield node

    def focusable(self):
        return self.kind in ("button", "input", "list")


class App:
    """One terminal application: a widget tree plus its terminal state."""

    def __init__(self, title="Silica", theme=None):
        self.title = title
        self.theme = dict(DEFAULT_THEME)
        if theme:
            self.theme.update(theme)
        self.root = Node("column")
        self.focus_index = 0
        self.closed = False
        self._screen = None
        self._last_key = ""
        self.size = (80, 24)

    # -- tree ----------------------------------------------------------------
    def add(self, node):
        self.root.add(node)
        return node

    def widgets(self):
        return list(self.root.walk())[1:]

    def focusables(self):
        return [n for n in self.widgets() if n.focusable()]

    def focused(self):
        items = self.focusables()
        if not items:
            return None
        self.focus_index %= len(items)
        return items[self.focus_index]

    def focus_next(self, step=1):
        items = self.focusables()
        if items:
            self.focus_index = (self.focus_index + step) % len(items)
        return self.focused()

    # -- layout --------------------------------------------------------------
    def height_of(self, node):
        if node.kind in ("text", "heading", "button", "input", "divider"):
            return 1
        if node.kind == "spacer":
            return max(0, int(node.props.get("height", 1)))
        if node.kind == "list":
            return max(1, min(len(node.items), int(node.props.get("height",
                                                                  len(node.items)))))
        if node.kind == "table":
            return 1 + len(node.rows)
        if node.kind == "panel":
            inner = sum(self.height_of(c) for c in node.children) or 1
            return inner + 2
        if node.kind == "row":
            return max([self.height_of(c) for c in node.children] or [1])
        return sum(self.height_of(c) for c in node.children) or 1

    def render_lines(self, width=None, height=None):
        """Lay the tree out as plain text lines. No terminal involved."""
        width = width or self.size[0]
        height = height or self.size[1]
        canvas = [[" "] * width for _ in range(height)]
        self._paint(self.root, canvas, 0, 0, width, height)
        return ["".join(row).rstrip() for row in canvas]

    def _paint(self, node, canvas, x, y, width, height):
        if y >= len(canvas) or width <= 0 or height <= 0:
            return
        if node.kind == "column":
            cursor = y
            for child in node.children:
                child_height = self.height_of(child)
                if cursor + child_height > y + height:
                    break
                self._paint(child, canvas, x, cursor, width, child_height)
                cursor += child_height
            return
        if node.kind == "row":
            count = max(1, len(node.children))
            each = max(1, width // count)
            for index, child in enumerate(node.children):
                self._paint(child, canvas, x + index * each, y, each,
                            self.height_of(child))
            return
        if node.kind in ("text", "heading"):
            label = node.text if node.kind == "text" else node.text.upper()
            self._put(canvas, x, y, label, width)
            return
        if node.kind == "button":
            marker = ">" if node.focused else " "
            self._put(canvas, x, y, "%s[ %s ]" % (marker, node.text), width)
            return
        if node.kind == "input":
            shown = node.value or node.props.get("placeholder", "")
            marker = ">" if node.focused else " "
            self._put(canvas, x, y, "%s[ %s" % (marker, shown), width - 1)
            self._put(canvas, x + max(0, width - 1), y, "]", 1)
            return
        if node.kind == "divider":
            self._put(canvas, x, y, BORDER * width, width)
            return
        if node.kind == "list":
            visible = node.items[node.scroll:node.scroll + height]
            for index, item in enumerate(visible):
                marker = ">" if node.focused and index == 0 else " "
                self._put(canvas, x, y + index, "%s %s" % (marker, item), width)
            return
        if node.kind == "table":
            if node.rows:
                self._put(canvas, x, y, "  ".join(str(c) for c in node.rows[0]),
                          width)
                for index, row in enumerate(node.rows[1:height]):
                    self._put(canvas, x, y + 1 + index,
                              "  ".join(str(c) for c in row), width)
            return
        if node.kind == "panel":
            title = node.text
            top = TOP_LEFT + (BORDER * max(0, width - 2)) + TOP_RIGHT
            self._put(canvas, x, y, top, width)
            if title:
                self._put(canvas, x + 2, y, " %s " % title, max(0, width - 4))
            for row in range(1, height - 1):
                self._put(canvas, x, y + row, VERTICAL, 1)
                self._put(canvas, x + width - 1, y + row, VERTICAL, 1)
            self._put(canvas, x, y + height - 1,
                      BOTTOM_LEFT + (BORDER * max(0, width - 2)) + BOTTOM_RIGHT,
                      width)
            inner_height = max(0, height - 2)
            for child in node.children:
                inner_height -= self.height_of(child)
                if inner_height < 0:
                    break
                self._paint(child, canvas, x + 2, y + 1 + (
                    height - 2 - inner_height - self.height_of(child)),
                    max(1, width - 4), self.height_of(child))
            return

    @staticmethod
    def _put(canvas, x, y, text, limit):
        if y < 0 or y >= len(canvas):
            return
        row = canvas[y]
        for offset, char in enumerate(text[:max(0, limit)]):
            column = x + offset
            if 0 <= column < len(row):
                row[column] = char


# --- terminal driver ---------------------------------------------------------
_SCREENS = {}


def _curses():
    try:
        import curses
    except ModuleNotFoundError:  # pragma: no cover - Windows without curses
        raise TUIError(
            "the curses module is unavailable, so terminal applications cannot run")
    return curses


def _open(app):
    curses = _curses()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise TUIError(
            "a TUI needs a real terminal: stdin or stdout is not a tty",
            )
    try:
        screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        screen.keypad(True)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for name, index in COLOURS.items():
                if index:
                    curses.init_pair(index, index, -1)
    except Exception as exc:
        raise TUIError("cannot initialise the terminal: %s" % exc)
    app._screen = screen
    return screen


def _close(app):
    if app._screen is None:
        return
    curses = _curses()
    try:
        app._screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
    finally:
        app._screen = None
        app.closed = True


def render(app):
    """Paint one frame. Works on a real terminal; returns the lines it drew."""
    lines = app.render_lines()
    screen = app._screen
    if screen is not None:
        try:
            height, width = screen.getmaxyx()
            app.size = (width, height)
            lines = app.render_lines(width, height)
            screen.erase()
            for index, line in enumerate(lines[:height]):
                try:
                    screen.addstr(index, 0, line[:width - 1])
                except Exception:  # pragma: no cover - bottom-right cell quirk
                    pass
            screen.refresh()
        except Exception as exc:  # pragma: no cover
            raise TUIError("cannot draw to the terminal: %s" % exc)
    return lines


KEY_NAMES = {
    "KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
    "KEY_RESIZE": "resize", "KEY_BACKSPACE": "backspace", "KEY_HOME": "home",
    "KEY_END": "end", "KEY_PPAGE": "pageup", "KEY_NPAGE": "pagedown",
}


def poll(app, timeout=None):
    """Block for one key, draw the frame, and return the key's name."""
    curses = _curses()
    if app._screen is None:
        _open(app)
    screen = app._screen
    if timeout is not None:
        screen.timeout(int(timeout))
    try:
        code = screen.getch()
    except KeyboardInterrupt:
        return "ctrl-c"
    finally:
        if timeout is not None:
            screen.timeout(-1)

    if code == -1:
        render(app)
        return ""

    name = _key_name(curses, code)
    app._last_key = name
    if name == "up":
        app.focus_next(-1)
    elif name == "down":
        app.focus_next(1)
    elif name == "backspace":
        node = app.focused()
        if node is not None and node.kind == "input":
            node.value = node.value[:-1]
    elif name == "resize":
        try:
            app.size = screen.getmaxyx()[::-1]
        except Exception:  # pragma: no cover
            pass
    elif len(name) == 1:
        node = app.focused()
        if node is not None and node.kind == "input" and name.isprintable():
            node.value += name
    render(app)
    return name


def _key_name(curses, code):
    try:
        raw = curses.keyname(code)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    except Exception:  # pragma: no cover
        return ""
    if text in KEY_NAMES:
        return KEY_NAMES[text]
    if text in ("\n", "\r", "KEY_ENTER"):
        return "enter"
    if text in ("\t",):
        return "tab"
    if text == "^C":
        return "ctrl-c"
    if text == "^D":
        return "ctrl-d"
    if text.startswith("^") and len(text) == 2:
        return "ctrl-" + text[1].lower()
    return text


def run(app, quit_key="q"):
    """Convenience loop: draw, wait for keys, stop on `quit_key` or Ctrl-C."""
    try:
        render(app)
        while not app.closed:
            key = poll(app)
            if key in (quit_key, "ctrl-c", "ctrl-d"):
                break
    finally:
        _close(app)
    return None


def close(app):
    _close(app)
    return None
