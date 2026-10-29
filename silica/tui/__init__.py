"""The Silica TUI: real terminal applications, built on curses.

Two layers, deliberately separated:

* a **layout engine** that turns a widget tree into styled segments. It touches
  no terminal, so the whole layout and styling path is testable without a pty.
* a **terminal driver** on curses that paints those segments in colour, reads
  keys and mouse events, handles resizing and restores the terminal on the way
  out.

Focus
-----
There is exactly one source of truth: `App.focus_index`, resolved by
`App.focused()`. Rendering asks the app which widget is focused; a widget never
decides that for itself. (An earlier version had a per-widget `focused` flag that
nothing ever set, so the focus marker never moved.)

Colour
------
The theme holds hex colours. Rendering emits a *style token* per segment
(`text`, `accent`, `border`, …) and the curses driver maps tokens to colour pairs
at paint time. On a terminal without colour the same segments are drawn with
default attributes — the layout is identical, only the colour is missing.

Events are polled rather than dispatched through callbacks: Silica has no
first-class functions, and calling one from inside a native would mean
re-entering the VM mid-instruction.
"""

import atexit
import os
import sys

BORDER = "\u2500"
VERTICAL = "\u2502"
TOP_LEFT = "\u250c"
TOP_RIGHT = "\u2510"
BOTTOM_LEFT = "\u2514"
BOTTOM_RIGHT = "\u2518"

# The professional dark theme, as specified.
DEFAULT_THEME = {
    "background": "#0B0D10",
    "surface": "#15191E",
    "border": "#262C36",
    "text": "#F3F4F6",
    "text_muted": "#9CA3AF",
    "accent": "#45C6B0",
    "error": "#F87171",
    "success": "#4ADE80",
    "warning": "#FBBF24",
}

# Named colours are accepted too, so a theme written with "cyan" keeps working.
NAMED = {
    "black": "#000000", "red": "#C0392B", "green": "#27AE60",
    "yellow": "#F1C40F", "blue": "#2980B9", "magenta": "#8E44AD",
    "cyan": "#45C6B0", "white": "#F3F4F6", "default": None,
    "grey": "#9CA3AF", "gray": "#9CA3AF",
}

# style token -> (foreground theme key, background theme key)
STYLES = {
    "text": ("text", "surface"),
    "muted": ("text_muted", "surface"),
    "accent": ("accent", "surface"),
    "error": ("error", "surface"),
    "success": ("success", "surface"),
    "warning": ("warning", "surface"),
    "border": ("border", "surface"),
    "title": ("accent", "surface"),
    "focus": ("background", "accent"),
    "button": ("text", "surface"),
    "button_focus": ("background", "accent"),
    "button_disabled": ("text_muted", "surface"),
    "field": ("text", "background"),
    "field_focus": ("text", "border"),
}


class TUIError(RuntimeError):
    pass


# Every application whose terminal is currently open. Restored on interpreter
# exit, including the uncaught-exception path — otherwise a runtime error inside
# a TUI leaves the user's terminal in curses mode with no echo and no cursor.
_OPEN_APPS = []


def _restore_all():
    for app in list(_OPEN_APPS):
        try:
            _close(app)
        except Exception:  # pragma: no cover - best effort during shutdown
            pass


atexit.register(_restore_all)


def parse_colour(value):
    """'#RRGGBB' or a colour name -> (r, g, b), or None for the default."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in NAMED:
            value = NAMED[text]
            if value is None:
                return None
            text = value                      # now a hex string, or still a name
        if text.startswith("#") and len(text) == 7:
            try:
                return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
            except ValueError:
                return None
    return None


def nearest_256(rgb):
    """Map an RGB triple onto the xterm-256 palette (16-231 cube, 232-255 greys)."""
    red, green, blue = rgb
    levels = [0, 95, 135, 175, 215, 255]
    best, best_distance = 16, None
    for index in range(216):
        r = levels[index // 36]
        g = levels[(index % 36) // 6]
        b = levels[index % 6]
        distance = (r - red) ** 2 + (g - green) ** 2 + (b - blue) ** 2
        if best_distance is None or distance < best_distance:
            best, best_distance = 16 + index, distance
    for step in range(24):
        level = 8 + step * 10
        distance = (level - red) ** 2 + (level - green) ** 2 + (level - blue) ** 2
        if distance < best_distance:
            best, best_distance = 232 + step, distance
    return best


def nearest_basic(rgb):
    """Map an RGB triple onto the eight ANSI colours, for 8/16-colour terminals."""
    red, green, blue = rgb
    bright = (red + green + blue) / 3 > 128
    if max(red, green, blue) - min(red, green, blue) < 32:
        return 7 if bright else 0
    index = 1 if red > green else 0
    if green > red:
        index = 2
    if blue > max(red, green):
        index = 4
    return index


class Segment:
    """A run of text with one style token."""

    __slots__ = ("text", "style")

    def __init__(self, text, style="text"):
        self.text = text
        self.style = style

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Segment(%r, %r)" % (self.text, self.style)

    def __eq__(self, other):
        return (isinstance(other, Segment) and self.text == other.text
                and self.style == other.style)


class Node:
    __slots__ = ("kind", "text", "props", "children", "parent", "value",
                 "items", "rows", "scroll", "box")

    def __init__(self, kind, text="", props=None):
        self.kind = kind
        self.text = text
        self.props = dict(props or {})
        self.children = []
        self.parent = None
        self.value = ""
        self.items = []
        self.rows = []
        self.scroll = 0
        self.box = (0, 0, 0, 0)   # x, y, width, height — filled in while painting

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
        if self.kind in ("button", "input", "list", "checkbox", "radio",
                         "textarea"):
            return not self.props.get("disabled")
        return False

    def label(self):
        if self.kind in ("input", "textarea"):
            return self.value
        if self.kind in ("list", "radio"):
            if not self.items:
                return ""
            index = max(0, min(int(self.props.get("selected", 0)), len(self.items) - 1))
            return self.items[index]
        return self.text


class App:
    """One terminal application: a widget tree plus its terminal state."""

    def __init__(self, title="Silica", theme=None):
        self.title = title
        self.theme = dict(DEFAULT_THEME)
        if theme:
            self.apply_theme(theme)
        self.root = Node("column")
        self.focus_index = 0
        self.closed = False
        self._screen = None
        self.size = (80, 24)
        self.last_pressed = ""
        self._pressed_once = ""
        self.mouse = False
        self._pairs = {}
        self._colour_mode = "none"

    # -- theme ---------------------------------------------------------------
    def apply_theme(self, values):
        for key, value in values.items():
            key = str(key)
            self.theme[key] = value
        return self.theme

    def colour(self, token):
        return parse_colour(self.theme.get(token))

    # -- tree ----------------------------------------------------------------
    def add(self, node):
        self.root.add(node)
        return node

    def widgets(self):
        return list(self.root.walk())[1:]

    def focusables(self):
        return [n for n in self.widgets() if n.focusable()]

    def focused(self):
        """The one source of truth for focus. None when nothing can take it."""
        items = self.focusables()
        if not items:
            return None
        self.focus_index %= len(items)
        return items[self.focus_index]

    def focus_next(self, step=1):
        items = self.focusables()
        if not items:
            self.focus_index = 0
            return None
        self.focus_index = (self.focus_index + step) % len(items)
        return items[self.focus_index]

    def focus_widget(self, node):
        items = self.focusables()
        if node in items:
            self.focus_index = items.index(node)
        return self.focused()

    def press(self):
        """Activate the focused widget once. Returns its label, or ""."""
        node = self.focused()
        if node is None or node.props.get("disabled"):
            return ""
        if node.kind not in ("button", "checkbox"):
            return ""
        self.last_pressed = node.label()
        self._pressed_once = node.label()
        return self.last_pressed

    def take_pressed(self):
        """Consume the last activation, so one keypress activates exactly once."""
        value = self._pressed_once
        self._pressed_once = ""
        return value

    # -- layout --------------------------------------------------------------
    def height_of(self, node):
        if node.kind in ("text", "heading", "button", "input", "divider",
                         "checkbox", "progress", "spinner", "status", "radio"):
            if node.kind == "radio":
                return max(1, len(node.items))
            return 1
        if node.kind == "textarea":
            return max(1, len((node.value or "").split("\n")))
        if node.kind == "spacer":
            return max(0, int(node.props.get("height", 1)))
        if node.kind == "progress":
            maximum = float(node.props.get("max", 100) or 100)
            value = float(node.props.get("value", 0))
            ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
            width_used = max(1, width - 6)
            filled = int(round(ratio * width_used))
            style = "success" if ratio >= 1.0 else "accent"
            bar = "\u2588" * filled + "\u2591" * (width_used - filled)
            self._put(canvas, x, y, bar, width_used, style)
            self._put(canvas, x + width_used, y,
                      " %3d%%" % int(round(ratio * 100)), width - width_used, "muted")
            return
        if node.kind == "spinner":
            frames = "|/-\\"
            frame = frames[int(node.props.get("frame", 0)) % len(frames)]
            self._put(canvas, x, y, "%s %s" % (frame, node.text), width, "accent")
            return
        if node.kind == "status":
            level = node.props.get("level", "info")
            style = {"info": "accent", "success": "success", "warning": "warning",
                     "error": "error"}.get(level, "accent")
            mark = {"info": "i", "success": "+", "warning": "!", "error": "x"}.get(level, "i")
            self._put(canvas, x, y, "[%s] %s" % (mark, node.text), width, style)
            return
        if node.kind == "radio":
            focused = node is focus
            chosen = int(node.props.get("selected", 0))
            for index, item in enumerate(node.items[:height]):
                mark = "(o)" if index == chosen else "( )"
                style = "button_focus" if (focused and index == chosen) else "text"
                self._put(canvas, x, y + index, " %s %s" % (mark, item), width, style)
            return
        if node.kind == "textarea":
            focused = node is focus
            style = "field_focus" if focused else "field"
            lines = (node.value or "").split("\n")
            for index, line in enumerate(lines[:height]):
                prefix = "\u2588 " if (focused and index == 0) else "  "
                self._put(canvas, x, y + index, prefix + line, width, style)
            return
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

    def render_segments(self, width=None, height=None):
        """Lay the tree out as rows of styled Segments. No terminal involved."""
        width = width or self.size[0]
        height = height or self.size[1]
        canvas = [[Segment(" ", "text") for _ in range(width)] for _ in range(height)]
        focus = self.focused()
        self._paint(self.root, canvas, 0, 0, width, height, focus)
        return canvas

    def render_lines(self, width=None, height=None):
        """Plain text, for tests and for terminals without colour."""
        return ["".join(s.text for s in row).rstrip()
                for row in self.render_segments(width, height)]

    def _paint(self, node, canvas, x, y, width, height, focus):
        node.box = (x, y, width, height)
        if y >= len(canvas) or width <= 0 or height <= 0:
            return
        if node.kind == "column":
            cursor = y
            for child in node.children:
                child_height = self.height_of(child)
                if cursor + child_height > y + height:
                    break
                self._paint(child, canvas, x, cursor, width, child_height, focus)
                cursor += child_height
            return
        if node.kind == "row":
            count = max(1, len(node.children))
            each = max(1, width // count)
            for index, child in enumerate(node.children):
                self._paint(child, canvas, x + index * each, y, each,
                            self.height_of(child), focus)
            return
        if node.kind == "text":
            self._put(canvas, x, y, node.text, width, "text")
            return
        if node.kind == "heading":
            self._put(canvas, x, y, node.text.upper(), width, "title")
            return
        if node.kind == "divider":
            self._put(canvas, x, y, BORDER * width, width, "border")
            return
        if node.kind == "spacer":
            return
        if node.kind == "button":
            disabled = node.props.get("disabled")
            focused = node is focus
            if disabled:
                style, marker = "button_disabled", " "
            elif focused:
                style, marker = "button_focus", "\u25b8"
            else:
                style, marker = "button", " "
            label = " %s %s " % (marker, node.text)
            self._put(canvas, x, y, label, width, style)
            return
        if node.kind == "checkbox":
            box = "[x]" if node.props.get("checked") else "[ ]"
            focused = node is focus
            style = "button_focus" if focused else "button"
            self._put(canvas, x, y, " %s %s " % (box, node.text), width, style)
            return
        if node.kind == "input":
            focused = node is focus
            style = "field_focus" if focused else "field"
            shown = node.value or node.props.get("placeholder", "")
            text = "%s %s" % ("\u2588" if focused else " ", shown)
            self._put(canvas, x, y, text, width, style)
            return
        if node.kind == "progress":
            maximum = float(node.props.get("max", 100) or 100)
            value = float(node.props.get("value", 0))
            ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
            width_used = max(1, width - 6)
            filled = int(round(ratio * width_used))
            style = "success" if ratio >= 1.0 else "accent"
            bar = "\u2588" * filled + "\u2591" * (width_used - filled)
            self._put(canvas, x, y, bar, width_used, style)
            self._put(canvas, x + width_used, y,
                      " %3d%%" % int(round(ratio * 100)), width - width_used, "muted")
            return
        if node.kind == "spinner":
            frames = "|/-\\"
            frame = frames[int(node.props.get("frame", 0)) % len(frames)]
            self._put(canvas, x, y, "%s %s" % (frame, node.text), width, "accent")
            return
        if node.kind == "status":
            level = node.props.get("level", "info")
            style = {"info": "accent", "success": "success", "warning": "warning",
                     "error": "error"}.get(level, "accent")
            mark = {"info": "i", "success": "+", "warning": "!", "error": "x"}.get(level, "i")
            self._put(canvas, x, y, "[%s] %s" % (mark, node.text), width, style)
            return
        if node.kind == "radio":
            focused = node is focus
            chosen = int(node.props.get("selected", 0))
            for index, item in enumerate(node.items[:height]):
                mark = "(o)" if index == chosen else "( )"
                style = "button_focus" if (focused and index == chosen) else "text"
                self._put(canvas, x, y + index, " %s %s" % (mark, item), width, style)
            return
        if node.kind == "textarea":
            focused = node is focus
            style = "field_focus" if focused else "field"
            lines = (node.value or "").split("\n")
            for index, line in enumerate(lines[:height]):
                prefix = "\u2588 " if (focused and index == 0) else "  "
                self._put(canvas, x, y + index, prefix + line, width, style)
            return
        if node.kind == "list":
            focused = node is focus
            visible = node.items[node.scroll:node.scroll + height]
            for index, item in enumerate(visible):
                chosen = focused and index == 0
                style = "button_focus" if chosen else "text"
                self._put(canvas, x, y + index,
                          " %s %s" % ("\u25b8" if chosen else " ", item), width, style)
            return
        if node.kind == "table":
            if node.rows:
                self._put(canvas, x, y,
                          "  ".join(str(c) for c in node.rows[0]), width, "title")
                for index, row in enumerate(node.rows[1:height]):
                    self._put(canvas, x, y + 1 + index,
                              "  ".join(str(c) for c in row), width, "text")
            return
        if node.kind == "panel":
            self._put(canvas, x, y, TOP_LEFT + BORDER * max(0, width - 2) + TOP_RIGHT,
                      width, "border")
            if node.text:
                self._put(canvas, x + 2, y, " %s " % node.text,
                          max(0, width - 4), "title")
            for row in range(1, height - 1):
                self._put(canvas, x, y + row, VERTICAL, 1, "border")
                self._put(canvas, x + width - 1, y + row, VERTICAL, 1, "border")
            self._put(canvas, x, y + height - 1,
                      BOTTOM_LEFT + BORDER * max(0, width - 2) + BOTTOM_RIGHT,
                      width, "border")
            inner_height = max(0, height - 2)
            for child in node.children:
                child_height = self.height_of(child)
                inner_height -= child_height
                if inner_height < 0:
                    break
                self._paint(child, canvas, x + 2,
                            y + 1 + (height - 2 - inner_height - child_height),
                            max(1, width - 4), child_height, focus)
            return

    @staticmethod
    def _put(canvas, x, y, text, limit, style):
        if y < 0 or y >= len(canvas):
            return
        row = canvas[y]
        for offset, char in enumerate(text[:max(0, limit)]):
            column = x + offset
            if 0 <= column < len(row):
                row[column] = Segment(char, style)


# --- terminal driver ---------------------------------------------------------
def _curses():
    try:
        import curses
    except ModuleNotFoundError:  # pragma: no cover - Windows without curses
        raise TUIError(
            "the curses module is unavailable, so terminal applications cannot run")
    return curses


def _colour_mode(curses):
    if not curses.has_colors():
        return "none"
    try:
        return "256" if curses.COLORS >= 256 else "basic"
    except Exception:  # pragma: no cover
        return "basic"


class _Palette:
    """Maps (foreground token, background token) to a curses colour pair."""

    def __init__(self, app, curses):
        self.app = app
        self.curses = curses
        self.mode = _colour_mode(curses)
        self.pairs = {}
        self.next_pair = 1
        self.index_cache = {}
        # A terminal that lets us redefine palette entries can show the theme's
        # exact colours instead of the nearest neighbour in the standard cube.
        self.exact = False
        self.exact_slots = {}
        self.next_slot = 16
        if self.mode == "256":
            try:
                self.exact = bool(curses.can_change_color())
            except Exception:  # pragma: no cover
                self.exact = False

    def exact_index(self, rgb):
        """Define a palette slot holding this exact colour, if the terminal allows."""
        if rgb in self.exact_slots:
            return self.exact_slots[rgb]
        if not self.exact or self.next_slot >= 256:
            return None
        slot = self.next_slot
        try:
            self.curses.init_color(slot, *(int(round(c * 1000 / 255)) for c in rgb))
        except Exception:  # pragma: no cover - terminal refused
            self.exact = False
            return None
        self.exact_slots[rgb] = slot
        self.next_slot += 1
        return slot

    def index(self, rgb):
        if rgb is None:
            return -1
        if rgb in self.index_cache:
            return self.index_cache[rgb]
        if self.mode == "256":
            exact = self.exact_index(rgb)
            if exact is not None:
                self.index_cache[rgb] = exact
                return exact
            value = nearest_256(rgb)
        elif self.mode == "basic":
            value = nearest_basic(rgb)
        else:
            value = -1
        self.index_cache[rgb] = value
        return value

    def pair(self, style):
        if self.mode == "none":
            return 0
        key = style
        if key in self.pairs:
            return self.pairs[key]
        foreground, background = STYLES.get(style, STYLES["text"])
        fg = self.index(self.app.colour(foreground))
        bg = self.index(self.app.colour(background))
        try:
            self.curses.init_pair(self.next_pair, fg, bg)
            attribute = self.curses.color_pair(self.next_pair)
        except Exception:  # pragma: no cover - pair table full
            attribute = 0
        self.pairs[key] = attribute
        self.next_pair += 1
        return attribute


def _open(app):
    curses = _curses()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise TUIError("a TUI needs a real terminal: stdin or stdout is not a tty")
    try:
        screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        screen.keypad(True)
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except Exception:  # pragma: no cover
                pass
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            app.mouse = True
        except Exception:  # pragma: no cover - terminal without mouse support
            app.mouse = False
        try:
            curses.curs_set(0)
        except Exception:  # pragma: no cover - some terminals refuse
            pass
    except Exception as exc:
        raise TUIError("cannot initialise the terminal: %s" % exc)
    app._screen = screen
    if app not in _OPEN_APPS:
        _OPEN_APPS.append(app)
    app._palette = _Palette(app, curses)
    app._colour_mode = app._palette.mode
    return screen


def _close(app):
    if app._screen is None:
        return
    curses = _curses()
    try:
        app._screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        try:
            curses.curs_set(1)
        except Exception:  # pragma: no cover
            pass
        curses.endwin()
    finally:
        app._screen = None
        app.closed = True
        if app in _OPEN_APPS:
            _OPEN_APPS.remove(app)


def render(app):
    """Paint one frame. Works on a real terminal; returns the plain-text lines."""
    rows = app.render_segments()
    screen = app._screen
    if screen is not None:
        try:
            height, width = screen.getmaxyx()
            app.size = (width, height)
            rows = app.render_segments(width, height)
            palette = getattr(app, "_palette", None)
            screen.erase()
            for index, row in enumerate(rows[:height]):
                column = 0
                for segment in row:
                    if column >= width - 1:
                        break
                    text = segment.text[:max(0, width - 1 - column)]
                    attribute = palette.pair(segment.style) if palette else 0
                    try:
                        screen.addstr(index, column, text, attribute)
                    except Exception:  # pragma: no cover - bottom-right cell quirk
                        pass
                    column += len(text)
            screen.refresh()
        except TUIError:
            raise
        except Exception as exc:  # pragma: no cover
            raise TUIError("cannot draw to the terminal: %s" % exc)
    return ["".join(s.text for s in row).rstrip() for row in rows]


KEY_NAMES = {
    "KEY_UP": "up", "KEY_DOWN": "down", "KEY_LEFT": "left", "KEY_RIGHT": "right",
    "KEY_RESIZE": "resize", "KEY_BACKSPACE": "backspace", "KEY_HOME": "home",
    "KEY_END": "end", "KEY_PPAGE": "pageup", "KEY_NPAGE": "pagedown",
    "KEY_DC": "delete", "KEY_ENTER": "enter",
}


def _key_name(curses, code):
    try:
        raw = curses.keyname(code)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    except Exception:  # pragma: no cover
        return ""
    if text in KEY_NAMES:
        return KEY_NAMES[text]
    # curses reports Enter as "^J" (10) or "^M" (13) depending on the terminal;
    # mapping those to "ctrl-j"/"ctrl-m" meant Enter never activated a button.
    if text in ("\n", "\r", "^J", "^M"):
        return "enter"
    if text == "\t":
        return "tab"
    if text in ("^C",):
        return "ctrl-c"
    if text in ("^D",):
        return "ctrl-d"
    if text.startswith("^") and len(text) == 2:
        return "ctrl-" + text[1].lower()
    if text == " ":
        return "space"
    return text


# Escape sequences for keys, decoded by hand.
#
# curses only translates these when the terminal's terminfo entry declares them
# (kcuu1 and friends). On a minimal terminfo — common on small systems, and the
# case in the sandbox these tests run in — curses returns ESC, "[", "B" as three
# separate keys and arrow navigation silently never works. Decoding the sequence
# here makes arrow keys work regardless of the terminfo database.
CSI_KEYS = {
    "[A": "up", "[B": "down", "[C": "right", "[D": "left",
    "OA": "up", "OB": "down", "OC": "right", "OD": "left",
    "[H": "home", "[F": "end", "OH": "home", "OF": "end",
    "[1~": "home", "[2~": "insert", "[3~": "delete", "[4~": "end",
    "[5~": "pageup", "[6~": "pagedown", "[Z": "backtab",
}


def _read_escape(screen, first_timeout=60):
    """After a bare ESC, collect the rest of a CSI sequence and name the key."""
    screen.timeout(first_timeout)
    try:
        second = screen.getch()
        if second == -1:
            return "escape"
        character = chr(second) if 0 <= second < 256 else ""
        if character not in ("[", "O"):
            return "escape"
        screen.timeout(first_timeout)
        third = screen.getch()
        if third == -1:
            return "escape"
        sequence = character + chr(third)
        # a few sequences carry a parameter and end with '~'
        if sequence[-1] == "~" or (len(sequence) == 2 and sequence[1].isdigit()):
            screen.timeout(first_timeout)
            fourth = screen.getch()
            if fourth != -1:
                sequence += chr(fourth)
        return CSI_KEYS.get(sequence, "escape")
    finally:
        screen.timeout(-1)


def _hit(app, x, y):
    """The focusable widget whose box contains a screen position, or None."""
    best = None
    for node in app.widgets():
        if not node.focusable():
            continue
        bx, by, bw, bh = node.box
        if bx <= x < bx + max(1, bw) and by <= y < by + max(1, bh):
            best = node
    return best


def poll(app, timeout=None):
    """Block for one event, redraw, and return its name."""
    curses = _curses()
    if app._screen is None:
        _open(app)
        # Draw before blocking. Without this the first frame only appeared after
        # the first keypress, so a program driven by poll() showed a blank
        # terminal until the user touched something.
        render(app)
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

    if code == curses.KEY_MOUSE:
        name = "click"
        try:
            _id, mx, my, _z, state = curses.getmouse()
        except Exception:  # pragma: no cover - terminal refused the event
            render(app)
            return "click"
        node = _hit(app, mx, my)
        if node is not None:
            app.focus_widget(node)
            if node.kind in ("button", "checkbox"):
                if state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED
                            | curses.BUTTON1_RELEASED):
                    app.press()
    else:
        name = _key_name(curses, code)
        if code == 27:
            # ESC: either the Escape key, or the start of a sequence curses did
            # not translate (see _read_escape)
            name = _read_escape(screen)
        if name == "up":
            app.focus_next(-1)
        elif name == "down":
            app.focus_next(1)
        elif name in ("enter", "space"):
            node = app.focused()
            if name == "enter" and node is not None and node.kind == "textarea":
                node.value = (node.value or "") + "\n"
            else:
                app.press()
        elif name in ("left", "right"):
            node = app.focused()
            if node is not None and node.kind == "radio" and node.items:
                chosen = int(node.props.get("selected", 0))
                step = -1 if name == "left" else 1
                node.props["selected"] = (chosen + step) % len(node.items)
        elif name == "backspace":
            node = app.focused()
            if node is not None and node.kind == "textarea":
                node.value = (node.value or "")[:-1]
            elif node is not None and node.kind == "input":
                node.value = node.value[:-1]
        elif name == "delete":
            node = app.focused()
            if node is not None and node.kind == "input":
                node.value = ""
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
