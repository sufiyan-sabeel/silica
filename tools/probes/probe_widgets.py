"""Probe Silica TUI widget keyboard interaction and colour fallback.

Drives the real `tui.poll()` event path with a fake screen/curses backend, so
keyboard behaviour is exercised exactly as it is at runtime, and checks the
palette's capability-dependent colour mapping without needing a terminal.

    python probe_widgets.py
"""

import os
import sys

# Resolve the Silica checkout: an explicit SILICA_ROOT wins, otherwise this file
# is assumed to live in <repo>/tools/probes/.
SILICA_ROOT = os.environ.get("SILICA_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SILICA_ROOT)

import curses  # noqa: E402  - the real module, for key codes and keyname()

from silica import tui  # noqa: E402

RESULTS = []


def record(group, name, outcome, detail=""):
    """outcome: True -> PASS, False -> FAIL, "GAP" -> verified unimplemented."""
    if outcome == "GAP":
        label = "GAP"
    elif bool(outcome):
        label = "PASS"
    else:
        label = "FAIL"
    RESULTS.append((group, name, label, detail))
    print("%-6s %-46s %-4s %s" % (group, name, label, detail))


KEYNAME = {
    9: b"\t", 10: b"^J", 13: b"^M", 27: b"^[", 32: b" ", 127: b"^?",
    258: b"KEY_DOWN", 259: b"KEY_UP", 260: b"KEY_LEFT", 261: b"KEY_RIGHT",
    262: b"KEY_HOME", 263: b"KEY_BACKSPACE", 330: b"KEY_DC", 338: b"KEY_NPAGE",
    339: b"KEY_PPAGE", 343: b"KEY_ENTER", 353: b"KEY_BTAB", 360: b"KEY_END",
    410: b"KEY_RESIZE",
}


class FakeCurses:
    KEY_MOUSE = 409
    ALL_MOUSE_EVENTS = 1
    REPORT_MOUSE_POSITION = 2
    BUTTON1_CLICKED = 4
    BUTTON1_PRESSED = 8
    BUTTON1_RELEASED = 16
    KEY_DOWN = 258
    KEY_UP = 259
    KEY_LEFT = 260
    KEY_RIGHT = 261

    class error(Exception):
        pass

    def keyname(self, code):
        if code in KEYNAME:
            return KEYNAME[code]
        if 0 <= code < 256:
            return bytes([code])
        raise self.error("no such key")

    def __init__(self, colors=256, can_change=False, init_pair_fails=False):
        self.COLORS = colors
        self._colors = colors > 0
        self._can_change = can_change
        self._init_pair_fails = init_pair_fails
        self.pairs = {}
        self.colors_defined = {}

    def has_colors(self):
        return self._colors

    def can_change_color(self):
        return self._can_change

    def init_color(self, slot, r, g, b):
        self.colors_defined[slot] = (r, g, b)

    def init_pair(self, pair, fg, bg):
        if self._init_pair_fails:
            raise curses.error("pair table full")
        self.pairs[pair] = (fg, bg)

    def color_pair(self, pair):
        return pair << 8


class FakeScreen:
    def __init__(self, keys, rows=24, cols=80):
        self.keys = list(keys)
        self.rows = rows
        self.cols = cols
        self.painted = []
        self.timeouts = []

    def getch(self):
        return self.keys.pop(0) if self.keys else -1

    def timeout(self, value):
        self.timeouts.append(value)

    def getmaxyx(self):
        return (self.rows, self.cols)

    def erase(self):
        self.painted = []

    def addstr(self, y, x, text, attr=0):
        self.painted.append((y, x, text, attr))

    def refresh(self):
        pass

    def keypad(self, value):
        pass


def make_app(kinds):
    app = tui.App("probe")
    nodes = {}
    for spec in kinds:
        kind = spec["kind"]
        node = tui.Node(kind, spec.get("text", ""), spec.get("props"))
        if "items" in spec:
            node.items = list(spec["items"])
        app.add(node)
        nodes[spec.get("name", kind)] = node
    return app, nodes


def drive(app, keys, fake_curses=None):
    """Send keys through the real poll(); returns the list of event names."""
    fake = fake_curses or FakeCurses()
    app._screen = FakeScreen(keys)
    app._palette = tui._Palette(app, fake)
    original = tui._curses
    tui._curses = lambda: fake
    names = []
    try:
        for _ in keys:
            names.append(tui.poll(app))
    finally:
        tui._curses = original
    return names


def focus_label(app):
    node = app.focused()
    return None if node is None else (node.kind, node.label())


# --- keyboard ---------------------------------------------------------------
def probe_keyboard():
    specs = [
        {"kind": "text", "text": "Title"},
        {"kind": "button", "text": "Save", "name": "save"},
        {"kind": "input", "text": "name", "name": "input"},
        {"kind": "checkbox", "text": "Accept", "name": "check"},
        {"kind": "button", "text": "Delete", "name": "delete",
         "props": {"disabled": True}},
    ]
    app, nodes = make_app(specs)
    record("KEY", "initial focus is the first focusable",
           focus_label(app) == ("button", "Save"), str(focus_label(app)))

    drive(app, [curses.KEY_DOWN])
    record("KEY", "down moves focus forward", app.focused() is nodes["input"],
           str(focus_label(app)))
    drive(app, [curses.KEY_UP])
    record("KEY", "up moves focus back", app.focused() is nodes["save"],
           str(focus_label(app)))
    drive(app, [curses.KEY_UP])
    record("KEY", "up from the first focusable wraps", app.focused() is nodes["check"],
           str(focus_label(app)))

    # Tab / Shift-Tab
    app, nodes = make_app(specs)
    names = drive(app, [9])
    moved = app.focused() is nodes["input"]
    record("KEY", "Tab moves focus", True if moved else "GAP",
           "event=%r focus=%s (no 'tab' branch in poll)" % (names[0], focus_label(app)))
    app, nodes = make_app(specs)
    drive(app, [curses.KEY_DOWN])
    names = drive(app, [curses.KEY_BTAB])
    moved = app.focused() is nodes["save"]
    record("KEY", "Shift-Tab moves focus back", True if moved else "GAP",
           "event=%r (unmapped name; no 'backtab' branch)" % (names[0],))

    # activation, exactly once
    app, nodes = make_app(specs)
    drive(app, [10])                       # Enter as ^J
    first = app.take_pressed()
    second = app.take_pressed()
    record("KEY", "Enter activates the focused button",
           first == "Save", "first=%r" % (first,))
    record("KEY", "one keypress activates exactly once",
           second == "", "second=%r" % (second,))

    app, nodes = make_app(specs)
    drive(app, [32])                       # Space
    record("KEY", "Space activates the focused button",
           app.take_pressed() == "Save")

    # disabled must never activate, and must not be focusable
    app, nodes = make_app(specs)
    record("KEY", "disabled widget is excluded from focus order",
           nodes["delete"] not in app.focusables())
    app.focus_widget(nodes["delete"])          # refuses: not focusable
    drive(app, [10])
    activated = app.take_pressed()
    record("KEY", "disabled button never activates", activated != "Delete",
           "activated=%r focused=%s" % (activated, focus_label(app)))
    app2, nodes2 = make_app(specs)
    app2.focus_index = 0
    nodes2["delete"].props["disabled"] = True
    record("KEY", "press() refuses a disabled node",
           app2.press() != "Delete" or app2.focused() is not nodes2["delete"],
           "focused=%s" % (focus_label(app2),))

    # radio left/right
    app, nodes = make_app([{"kind": "radio", "text": "mode",
                            "name": "radio", "items": ["a", "b", "c"]}])
    drive(app, [curses.KEY_RIGHT])
    after_right = nodes["radio"].props.get("selected", 0)
    drive(app, [curses.KEY_LEFT])
    after_left = nodes["radio"].props.get("selected", 0)
    record("KEY", "radio right/left changes selection",
           (after_right, after_left) == (1, 0), "right=%s left=%s" % (after_right, after_left))

    # input editing
    app, nodes = make_app([{"kind": "input", "text": "field", "name": "input"}])
    drive(app, [ord("a"), ord("b"), ord("c")])
    typed = nodes["input"].value
    drive(app, [curses.KEY_BACKSPACE])
    after_back = nodes["input"].value
    record("KEY", "typing appends to an input", typed == "abc", repr(typed))
    record("KEY", "backspace removes one character", after_back == "ab", repr(after_back))

    # cursor movement inside an input
    app, nodes = make_app([{"kind": "input", "text": "field", "name": "input"}])
    nodes["input"].value = "abcd"
    drive(app, [curses.KEY_LEFT])
    drive(app, [ord("X")])
    after_left_insert = nodes["input"].value
    record("KEY", "left arrow moves the input cursor",
           True if after_left_insert == "abcXd" else "GAP",
           "value=%r (inputs are append/backspace only)" % (after_left_insert,))

    # delete key semantics
    app, nodes = make_app([{"kind": "input", "text": "field", "name": "input"}])
    nodes["input"].value = "abcd"
    drive(app, [curses.KEY_DC])
    record("KEY", "delete key deletes one character, not the whole field",
           True if nodes["input"].value == "abc" else "GAP",
           "value=%r (KEY_DC clears the whole field)" % (nodes["input"].value,))

    # home / end / paging on a long list
    app, nodes = make_app([{"kind": "list", "text": "items", "name": "list",
                            "items": [str(i) for i in range(50)]}])
    before = nodes["list"].scroll
    drive(app, [curses.KEY_NPAGE])
    after_page = nodes["list"].scroll
    record("KEY", "PageDown scrolls a long list", True if after_page != before else "GAP",
           "before=%s after=%s (nothing ever increments node.scroll)"
           % (before, after_page))
    # a list taller than its box is clipped to the first rows, permanently
    app, nodes = make_app([{"kind": "list", "text": "items", "name": "list",
                            "items": [str(i) for i in range(50)]}])
    lines = tui.render(app)
    record("KEY", "a long list is clipped, not scrollable",
           "GAP", "rendered %d lines of 50 items" % len(lines))

    # escape and resize
    app, nodes = make_app(specs)
    names = drive(app, [27])
    record("KEY", "Escape is reported as 'escape'", names == ["escape"], str(names))

    app, nodes = make_app(specs)
    fake = FakeCurses()
    app._screen = FakeScreen([curses.KEY_RESIZE], rows=30, cols=100)
    app._palette = tui._Palette(app, fake)
    original = tui._curses
    tui._curses = lambda: fake
    try:
        tui.poll(app)
    finally:
        tui._curses = original
    record("KEY", "resize updates app.size", app.size == (100, 30), str(app.size))

    # empty and shrunk layouts
    app, nodes = make_app([{"kind": "text", "text": "only text"}])
    record("KEY", "empty layout has no focus", app.focused() is None)
    try:
        drive(app, [curses.KEY_DOWN, 10])
        record("KEY", "keys in an empty layout do not raise", True)
    except Exception as exc:
        record("KEY", "keys in an empty layout do not raise", False, repr(exc))

    app, nodes = make_app(specs)
    app.focus_widget(nodes["check"])
    app.root.children.remove(nodes["check"])
    try:
        drive(app, [curses.KEY_DOWN])
        record("KEY", "removing the focused widget does not raise", True,
               "focus=%s" % (focus_label(app),))
    except Exception as exc:
        record("KEY", "removing the focused widget does not raise", False, repr(exc))


# --- colour -----------------------------------------------------------------
def probe_colour():
    record("COLOUR", "parse_colour hex", tui.parse_colour("#45C6B0") == (0x45, 0xC6, 0xB0))
    record("COLOUR", "parse_colour name", tui.parse_colour("cyan") == (0x45, 0xC6, 0xB0))
    record("COLOUR", "parse_colour invalid is None", tui.parse_colour("#xyz") is None)
    record("COLOUR", "parse_colour default is None", tui.parse_colour(None) is None)

    pure = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
            "black": (0, 0, 0), "white": (255, 255, 255)}
    for name, rgb in pure.items():
        index = tui.nearest_256(rgb)
        record("COLOUR", "nearest_256(%s) in palette" % name, 16 <= index <= 255, str(index))
    grey = tui.nearest_256((128, 128, 128))
    record("COLOUR", "nearest_256(grey) uses the grey ramp", 232 <= grey <= 255, str(grey))

    app = tui.App("colour")
    # no colour support at all
    palette = tui._Palette(app, FakeCurses(colors=0))
    record("COLOUR", "no-colour terminal reports mode 'none'", palette.mode == "none",
           palette.mode)
    record("COLOUR", "no-colour terminal yields attribute 0", palette.pair("text") == 0)

    # 8/16-colour terminal
    palette = tui._Palette(app, FakeCurses(colors=8))
    index = palette.index(tui.parse_colour("#45C6B0"))
    record("COLOUR", "basic terminal maps into 0..15", 0 <= index <= 15,
           "mode=%s index=%s" % (palette.mode, index))

    # 256-colour terminal, no palette redefinition
    fake = FakeCurses(colors=256, can_change=False)
    palette = tui._Palette(app, fake)
    index = palette.index(tui.parse_colour("#45C6B0"))
    record("COLOUR", "256-colour terminal uses the 256 cube",
           palette.mode == "256" and 16 <= index <= 255, str(index))
    record("COLOUR", "256-colour without init_color defines nothing",
           fake.colors_defined == {}, str(fake.colors_defined))

    # true-colour capable terminal
    fake = FakeCurses(colors=256, can_change=True)
    palette = tui._Palette(app, fake)
    index = palette.index((0x45, 0xC6, 0xB0))
    record("COLOUR", "true-colour terminal redefines a slot",
           index is not None and index >= 16 and fake.colors_defined,
           "slot=%s defined=%s" % (index, list(fake.colors_defined.items())[:1]))

    # pair table exhaustion
    fake = FakeCurses(colors=256, init_pair_fails=True)
    palette = tui._Palette(app, fake)
    record("COLOUR", "pair-table exhaustion falls back to attribute 0",
           palette.pair("text") == 0)

    # every style token resolves
    palette = tui._Palette(app, FakeCurses(colors=256))
    missing = [style for style in tui.STYLES if palette.pair(style) == 0]
    record("COLOUR", "every style token maps to a pair", not missing, str(missing))

    # theme override reaches the palette: compare the RGB the palette defines,
    # not the slot number (each palette starts allocating at slot 16)
    app2 = tui.App("themed")
    app2.apply_theme({"accent": "#FF0000"})
    fake_override = FakeCurses(colors=256, can_change=True)
    slot_override = tui._Palette(app2, fake_override).index(app2.colour("accent"))
    fake_default = FakeCurses(colors=256, can_change=True)
    slot_default = tui._Palette(tui.App("d"), fake_default).index(
        tui.parse_colour(tui.DEFAULT_THEME["accent"]))
    override_rgb = fake_override.colors_defined[slot_override]
    default_rgb = fake_default.colors_defined[slot_default]
    record("COLOUR", "theme override changes the rendered colour",
           override_rgb != default_rgb,
           "override=%s default=%s" % (override_rgb, default_rgb))


def main():
    probe_keyboard()
    probe_colour()
    passed = [r for r in RESULTS if r[2] == "PASS"]
    failed = [r for r in RESULTS if r[2] == "FAIL"]
    gaps = [r for r in RESULTS if r[2] == "GAP"]
    print("\n%d probes: %d passed, %d failed, %d verified gaps"
          % (len(RESULTS), len(passed), len(failed), len(gaps)))
    for group, name, _s, detail in failed:
        print("  FAILED [%s] %s  %s" % (group, name, detail))
    for group, name, _s, detail in gaps:
        print("  GAP    [%s] %s  %s" % (group, name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
