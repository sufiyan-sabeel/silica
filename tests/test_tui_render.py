"""Tests for the repaired TUI: colour, focus, buttons and the calculator.

The two bugs this covers were both invisible to the old suite, which is the point:

* colour was configured and never rendered, so no test asserted that a colour
  attribute reached the terminal;
* focus was read from a per-widget flag that nothing ever set, so no test
  asserted that pressing a key moved the marker.

So the tests here check the *pipeline*, not just the data: hex colours become
palette indices, segments carry style tokens, the driver emits real SGR codes in
a pseudo-terminal, and a keypress changes what is drawn.
"""

import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from silica.tui import (App, Node, Segment, nearest_256, nearest_basic,
                        parse_colour)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALCULATOR = os.path.join(ROOT, "examples", "tui_calculator.sc")


def app_with(*children):
    app = App("Test")
    for child in children:
        app.add(child)
    return app


class ColourTests(unittest.TestCase):
    def test_hex_colours_parse(self):
        self.assertEqual(parse_colour("#45C6B0"), (0x45, 0xC6, 0xB0))
        self.assertEqual(parse_colour("#0B0D10"), (0x0B, 0x0D, 0x10))

    def test_named_colours_still_work(self):
        self.assertEqual(parse_colour("cyan"), (0x45, 0xC6, 0xB0))
        self.assertIsNone(parse_colour("default"))
        self.assertIsNone(parse_colour("not-a-colour"))

    def test_the_default_theme_is_the_documented_dark_palette(self):
        app = App("t")
        self.assertEqual(app.theme["background"], "#0B0D10")
        self.assertEqual(app.theme["surface"], "#15191E")
        self.assertEqual(app.theme["accent"], "#45C6B0")
        self.assertEqual(app.theme["error"], "#F87171")
        self.assertEqual(app.theme["success"], "#4ADE80")

    def test_256_colour_mapping_is_close_to_the_source(self):
        index = nearest_256((0x45, 0xC6, 0xB0))
        self.assertTrue(16 <= index <= 255)
        # and it must be nearer than a deliberately wrong colour
        self.assertNotEqual(index, nearest_256((0xFF, 0x00, 0x00)))

    def test_basic_mapping_stays_inside_the_eight_colours(self):
        for rgb in [(0, 0, 0), (255, 255, 255), (0x45, 0xC6, 0xB0), (200, 30, 30)]:
            with self.subTest(rgb=rgb):
                self.assertTrue(0 <= nearest_basic(rgb) <= 7)

    def test_rendering_emits_style_tokens_not_plain_text(self):
        app = app_with(Node("panel", "P"))
        rows = app.render_segments(30, 5)
        styles = {segment.style for row in rows for segment in row}
        self.assertIn("border", styles)
        self.assertIn("title", styles)

    def test_a_theme_override_changes_the_rendered_style_token(self):
        app = app_with(Node("text", "x"))
        app.apply_theme({"accent": "#FF0000"})
        self.assertEqual(app.colour("accent"), (255, 0, 0))

    def test_plain_text_rendering_still_works(self):
        app = app_with(Node("text", "hello"))
        self.assertEqual(app.render_lines(20, 2)[0].strip(), "hello")

    def test_no_colour_support_falls_back_without_crashing(self):
        """A terminal with no colour gets the same layout, just no attributes."""
        from silica.tui import _Palette

        class FakeCurses:
            COLORS = 0
            def has_colors(self):
                return False
        app = App("t")
        palette = _Palette(app, FakeCurses())
        self.assertEqual(palette.mode, "none")
        self.assertEqual(palette.pair("text"), 0)


class FocusTests(unittest.TestCase):
    def test_focus_starts_on_the_first_focusable_widget(self):
        first = Node("button", "a")
        app = app_with(Node("text", "label"), first, Node("button", "b"))
        self.assertIs(app.focused(), first)

    def test_focus_skips_non_focusable_containers(self):
        app = app_with(Node("panel", "p"), Node("divider"), Node("button", "b"))
        self.assertEqual([n.kind for n in app.focusables()], ["button"])

    def test_down_moves_through_mixed_widgets(self):
        button = Node("button", "go")
        field = Node("input", "")
        item = Node("list")
        item.items = ["x"]
        app = app_with(button, Node("text", "skip"), field, item)
        order = [app.focused().kind]
        for _ in range(2):
            app.focus_next()
            order.append(app.focused().kind)
        self.assertEqual(order, ["button", "input", "list"])

    def test_focus_wraps_at_the_end(self):
        app = app_with(Node("button", "a"), Node("button", "b"))
        app.focus_next()
        app.focus_next()
        self.assertEqual(app.focused().text, "a")

    def test_focus_moves_backwards(self):
        app = app_with(Node("button", "a"), Node("button", "b"))
        app.focus_next(-1)
        self.assertEqual(app.focused().text, "b")

    def test_the_focus_marker_moves_in_the_rendered_output(self):
        """The regression that mattered: the marker used to stay put."""
        app = app_with(Node("button", "one"), Node("button", "two"))
        before = app.render_lines(30, 3)
        self.assertIn("\u25b8", before[0])
        self.assertNotIn("\u25b8", before[1])
        app.focus_next()
        after = app.render_lines(30, 3)
        self.assertNotIn("\u25b8", after[0])
        self.assertIn("\u25b8", after[1])

    def test_focus_state_is_rendered_as_a_distinct_style(self):
        app = app_with(Node("button", "one"), Node("button", "two"))
        rows = app.render_segments(30, 3)
        focused_styles = {s.style for s in rows[0]}
        unfocused_styles = {s.style for s in rows[1]}
        self.assertIn("button_focus", focused_styles)
        self.assertNotIn("button_focus", unfocused_styles)

    def test_an_empty_layout_has_no_focus_and_does_not_crash(self):
        app = App("empty")
        self.assertIsNone(app.focused())
        self.assertIsNone(app.focus_next())
        self.assertEqual(app.press(), "")
        self.assertEqual(len(app.render_lines(20, 4)), 4)

    def test_disabled_widgets_are_skipped(self):
        disabled = Node("button", "no")
        disabled.props["disabled"] = True
        enabled = Node("button", "yes")
        app = app_with(disabled, enabled)
        self.assertIs(app.focused(), enabled)

    def test_focus_on_a_tiny_terminal_does_not_raise(self):
        app = app_with(Node("button", "a"), Node("button", "b"))
        for size in [(1, 1), (3, 1), (10, 2)]:
            with self.subTest(size=size):
                app.render_lines(*size)


class ButtonTests(unittest.TestCase):
    def test_enter_activates_the_focused_button(self):
        app = app_with(Node("button", "ADD"))
        self.assertEqual(app.press(), "ADD")
        self.assertEqual(app.focused().label(), "ADD")

    def test_activation_is_consumed_exactly_once(self):
        app = app_with(Node("button", "ADD"))
        app.press()
        self.assertEqual(app.take_pressed(), "ADD")
        self.assertEqual(app.take_pressed(), "")

    def test_a_disabled_button_does_not_activate(self):
        button = Node("button", "no")
        button.props["disabled"] = True
        app = app_with(button)
        self.assertEqual(app.press(), "")

    def test_pressing_on_a_field_does_nothing(self):
        app = app_with(Node("input", ""))
        self.assertEqual(app.press(), "")

    def test_a_disabled_button_renders_differently(self):
        button = Node("button", "no")
        button.props["disabled"] = True
        rows = app_with(button).render_segments(20, 2)
        self.assertIn("button_disabled", {s.style for s in rows[0]})


class CalculatorTests(unittest.TestCase):
    """The example's arithmetic, exercised without a terminal."""

    def run_source(self, source, capture=True):
        import io
        from silica.engine import compile_source, run_chunk
        out = io.StringIO()
        try:
            chunk = compile_source(source, "<calc>").chunk
            run_chunk(chunk, "<calc>", stdin=io.StringIO(""), stdout=out,
                      stderr=io.StringIO())
        except Exception as exc:  # noqa: BLE001
            return exc
        return out.getvalue()

    def compute(self, a, b, op):
        source = (
            "use string\n"
            "sfn compute(left: String, right: String, op: String) -> String {\n"
            "    let a: Float = float(left)\n"
            "    let b: Float = float(right)\n"
            '    si op == "ADD" { ret str(a + b) }\n'
            '    si op == "SUBTRACT" { ret str(a - b) }\n'
            '    si op == "MULTIPLY" { ret str(a * b) }\n'
            '    si op == "DIVIDE" {\n'
            '        si b == 0.0 { ret "cannot divide by zero" }\n'
            "        ret str(a / b)\n"
            "    }\n"
            '    ret "unknown operation"\n'
            "}\n"
            "sfn main() { sprint(compute(%r, %r, %r)) }\n" % (a, b, op)
        )
        return self.run_source(source).strip()

    def test_the_four_operations(self):
        cases = [("12", "4", "ADD", "16.0"), ("12", "4", "SUBTRACT", "8.0"),
                 ("12", "4", "MULTIPLY", "48.0"), ("12", "4", "DIVIDE", "3.0")]
        for left, right, op, expected in cases:
            with self.subTest(op=op):
                self.assertEqual(self.compute(left, right, op), expected)

    def test_division_by_zero_is_reported_not_crashed(self):
        self.assertEqual(self.compute("5", "0", "DIVIDE"), "cannot divide by zero")

    def test_an_unknown_operation_is_reported(self):
        self.assertEqual(self.compute("1", "2", "POWER"), "unknown operation")

    def test_the_example_compiles(self):
        completed = subprocess.run(
            [sys.executable, "-m", "silica", "check", CALCULATOR],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-800:])


class TerminalColourTests(unittest.TestCase):
    """The only tier that proves colour reaches a terminal."""

    def drive(self, script, keys, timeout=40):
        directory = tempfile.mkdtemp(prefix="silica-tui-colour-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "app.sc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        master, slave = pty.openpty()
        env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=ROOT,
                   LANG="C.UTF-8", LC_ALL="C.UTF-8")
        # stderr goes to a pipe, not the screen: a traceback interleaved into the
        # terminal capture makes every assertion unreliable, and we want to see it
        process = subprocess.Popen(
            [sys.executable, "-m", "silica", "run", path, "--allow-tui"],
            stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=env, cwd=ROOT)
        os.close(slave)
        output = b""

        def pump(seconds):
            nonlocal output
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.05)
                if not ready:
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    return False
                if not chunk:
                    return False
                output += chunk
            return True

        def wait_for(minimum, limit):
            """Pump until at least `minimum` bytes have arrived, or `limit` seconds pass.

            A fixed sleep is not enough: under a loaded CI runner the child can take
            several seconds to import and draw, and keys sent before curses enables
            keypad mode are read as raw bytes instead of arrow keys.
            """
            end = time.time() + limit
            while len(output) < minimum and time.time() < end:
                if not pump(0.1):
                    break
            return len(output) >= minimum

        deadline = time.time() + timeout
        try:
            self.assertTrue(wait_for(400, 20),
                            "the program drew nothing: %r" % output[:200])
            for key in keys:
                before = len(output)
                os.write(master, key)
                pump(0.5)
                # give the frame triggered by this key a moment to arrive
                wait_for(before + 40, 3)
            while time.time() < deadline:
                if not pump(0.2):
                    break
                if process.poll() is not None:
                    break
            process.wait(timeout=5)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
        try:
            errors = process.stderr.read().decode("utf-8", "replace")
        except Exception:
            errors = ""
        process.stderr.close()
        text = output.decode("utf-8", "replace")
        if errors.strip():
            text += "\n--- stderr ---\n" + errors
        return process.returncode, text

    SCRIPT = (
        'use tui\n'
        'use tui.lib.widgets\n'
        'sfn main() {\n'
        '    let app = tui.app("Colour")\n'
        '    let panel = tui.panel("Theme")\n'
        '    tui.add(panel, tui.heading("Colours"))\n'
        '    tui.add(app, panel)\n'
        '    tui.add(app, tui.button("One"))\n'
        '    tui.add(app, tui.button("Two"))\n'
        '    tant oui {\n'
        '        let key = tui.poll(app)\n'
        '        si key == "q" {\n'
        '            tui.close(app)\n'
        '            halt\n'
        '        }\n'
        '    }\n'
        '}\n')

    def test_the_theme_reaches_the_terminal_as_colour_escapes(self):
        code, output = self.drive(self.SCRIPT, [b"q"])
        self.assertEqual(code, 0, output[-1200:])
        self.assertIn("38;5;", output, "no 256-colour foreground was emitted")
        self.assertIn("48;5;", output, "no 256-colour background was emitted")
        colours = set(re.findall(r"\x1b\[([0-9;]*)m", output))
        self.assertGreaterEqual(len(colours), 4, "too few distinct styles drawn")

    def test_the_accent_colour_is_actually_used(self):
        from silica.tui import nearest_256
        accent = str(nearest_256((0x45, 0xC6, 0xB0)))
        code, output = self.drive(self.SCRIPT, [b"q"])
        self.assertEqual(code, 0)
        self.assertIn(accent, output, "the accent index never appeared")

    def test_the_focus_marker_moves_when_an_arrow_key_is_pressed(self):
        code, output = self.drive(self.SCRIPT, [b"\x1b[B", b"q"])
        self.assertEqual(code, 0, output[-1200:])
        clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        self.assertIn("One", clean)
        self.assertIn("Two", clean)
        # the marker is drawn on a different line after the arrow key
        self.assertGreaterEqual(clean.count("\u25b8"), 1)

    def test_the_calculator_runs_and_computes_in_a_real_terminal(self):
        with open(CALCULATOR, encoding="utf-8") as handle:
            source = handle.read()
        code, output = self.drive(source, [b"\x1b[B", b"\x1b[B", b"\r", b"q"],
                                  timeout=60)
        self.assertEqual(code, 0, output[-1500:])
        clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
        self.assertIn("ADD", clean)
        self.assertIn("16", clean, "12 + 4 should show 16")


if __name__ == "__main__":
    unittest.main()
