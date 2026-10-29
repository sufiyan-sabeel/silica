"""Tests for the expanded TUI widget library and terminal cleanup.

Covers the widgets added in this pass (progress, spinner, status, radio,
textarea) and the two behaviours that were broken or missing:

* the terminal must be restored even when the program raises — an uncaught
  Silica error used to leave the user's terminal in curses mode;
* colours must be exact where the terminal allows palette redefinition, and
  nearest-match where it does not.
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

from silica.tui import App, Node, _Palette, nearest_256

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")


def app_with(*children):
    app = App("Test")
    for child in children:
        app.add(child)
    return app


def run_source(source, capture=True):
    """Run Silica source; returns its output, or the exception it raised.

    The tui.run capability is granted: tui.render is gated on it, and without a
    real terminal it simply returns the rendered lines, which is what these tests
    inspect. Nothing here opens a terminal.
    """
    import io
    from silica.capabilities import TUI_RUN, CapabilitySet
    from silica.engine import compile_source, run_chunk
    capabilities = CapabilitySet.empty().grant(TUI_RUN, ".")
    out = io.StringIO()
    try:
        chunk = compile_source(source, "<test>").chunk
        run_chunk(chunk, "<test>", stdin=io.StringIO(""), stdout=out,
                  stderr=io.StringIO(), capabilities=capabilities)
    except Exception as exc:  # noqa: BLE001
        return exc
    return out.getvalue() if capture else None


class ProgressTests(unittest.TestCase):
    def node(self, value, maximum=100):
        node = Node("progress")
        node.props["value"] = value
        node.props["max"] = maximum
        return node

    def test_zero_percent_is_empty(self):
        line = app_with(self.node(0)).render_lines(30, 1)[0]
        self.assertIn("0%", line)
        self.assertNotIn("\u2588", line)

    def test_fifty_percent_is_half_filled(self):
        line = app_with(self.node(50)).render_lines(30, 1)[0]
        self.assertIn("50%", line)
        filled = line.count("\u2588")
        empty = line.count("\u2591")
        self.assertGreater(filled, 0)
        self.assertLess(abs(filled - empty), 4)

    def test_full_uses_the_success_style(self):
        rows = app_with(self.node(100)).render_segments(30, 1)
        self.assertIn("success", {segment.style for segment in rows[0]})

    def test_values_outside_the_range_are_clamped(self):
        for value in (-50, 500):
            with self.subTest(value=value):
                line = app_with(self.node(value)).render_lines(30, 1)[0]
                self.assertTrue("0%" in line or "100%" in line, line)

    def test_a_zero_maximum_is_refused(self):
        error = run_source('use tui\nsfn main() {\n'
                           '    let p = tui.progress(5, 0)\n}\n')
        self.assertIn("greater than zero", str(error))

    def test_set_progress_updates_the_bar(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let p = tui.progress(0, 10)\n'
                  '    tui.add(app, p)\n'
                  '    tui.set_progress(p, 7)\n'
                  '    per line in tui.render(app) {\n'
                  '        sprint(line)\n'
                  '    }\n}\n')
        self.assertIn("70%", run_source(source))


class SpinnerAndStatusTests(unittest.TestCase):
    def test_spinner_cycles_through_its_frames(self):
        node = Node("spinner", "loading")
        app = app_with(node)
        seen = set()
        for frame in range(4):
            node.props["frame"] = frame
            line = app.render_lines(20, 1)[0]
            seen.add(line.strip()[0])
        self.assertEqual(len(seen), 4, "the spinner should show four frames")

    def test_each_status_level_has_its_own_style(self):
        for level, style in [("info", "accent"), ("success", "success"),
                             ("warning", "warning"), ("error", "error")]:
            with self.subTest(level=level):
                node = Node("status", "message")
                node.props["level"] = level
                rows = app_with(node).render_segments(30, 1)
                self.assertIn(style, {segment.style for segment in rows[0]})

    def test_an_unknown_status_level_is_refused(self):
        error = run_source('use tui\nsfn main() {\n'
                           '    let s = tui.status("x", "loud")\n}\n')
        self.assertIn("level must be", str(error))


class RadioTests(unittest.TestCase):
    def build(self):
        node = Node("radio")
        node.items = ["Small", "Medium", "Large"]
        node.props["selected"] = 0
        return node

    def test_it_renders_one_line_per_option(self):
        lines = app_with(self.build()).render_lines(30, 4)
        self.assertIn("Small", lines[0])
        self.assertIn("Medium", lines[1])
        self.assertIn("Large", lines[2])

    def test_the_selected_option_is_marked(self):
        lines = app_with(self.build()).render_lines(30, 4)
        self.assertIn("(o)", lines[0])
        self.assertIn("( )", lines[1])

    def test_select_changes_the_choice_and_returns_the_label(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let r = tui.radio(["a", "b", "c"])\n'
                  '    tui.add(app, r)\n'
                  '    sprint(tui.select(r, 2))\n'
                  '    sprint(str(tui.selected_index(r)))\n}\n')
        self.assertEqual(run_source(source).split(), ["c", "2"])

    def test_an_out_of_range_choice_is_refused(self):
        source = ('use tui\nsfn main() {\n'
                  '    let r = tui.radio(["a"])\n'
                  '    tui.select(r, 5)\n}\n')
        self.assertIn("out of range", str(run_source(source)))

    def test_an_empty_radio_is_refused(self):
        self.assertIn("at least one option",
                      str(run_source('use tui\nsfn main() {\n'
                                     '    let r = tui.radio([])\n}\n')))


class TextareaTests(unittest.TestCase):
    def test_it_renders_every_line(self):
        node = Node("textarea")
        node.value = "first\nsecond\nthird"
        lines = app_with(node).render_lines(30, 4)
        self.assertIn("first", lines[0])
        self.assertIn("second", lines[1])
        self.assertIn("third", lines[2])

    def test_value_and_set_text_round_trip(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let t = tui.textarea("one")\n'
                  '    tui.add(app, t)\n'
                  '    tui.set_text(t, "two\\nthree")\n'
                  '    sprint(tui.value(t))\n}\n')
        self.assertIn("two", run_source(source))

    def test_its_height_follows_its_line_count(self):
        node = Node("textarea")
        node.value = "a\nb\nc"
        app = App("t")
        self.assertEqual(app.height_of(node), 3)
        node.value = ""
        self.assertEqual(app.height_of(node), 1)


class CleanupTests(unittest.TestCase):
    """The terminal must be usable again after the program ends, however it ends."""

    def drive(self, source, keys, timeout=40):
        directory = tempfile.mkdtemp(prefix="silica-tui-cleanup-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "app.sc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        master, slave = pty.openpty()
        env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=ROOT,
                   LANG="C.UTF-8", LC_ALL="C.UTF-8")
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

        try:
            end = time.time() + 20
            while len(output) < 300 and time.time() < end:
                pump(0.1)
            for key in keys:
                os.write(master, key)
                pump(0.6)
            deadline = time.time() + timeout
            while time.time() < deadline and process.poll() is None:
                pump(0.2)
            process.wait(timeout=10)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
        errors = process.stderr.read().decode("utf-8", "replace")
        process.stderr.close()
        return process.returncode, output.decode("utf-8", "replace"), errors

    CRASH = ('use tui\nuse tui.lib.widgets\n'
             'sfn main() {\n'
             '    let app = tui.app("Crash")\n'
             '    tui.add(app, tui.text("ready"))\n'
             '    tant oui {\n'
             '        let key = tui.poll(app)\n'
             '        si key == "q" {\n'
             '            tui.close(app)\n'
             '            halt\n'
             '        }\n'
             '        si key == "x" {\n'
             '            sprint(str(float("abc")))\n'
             '        }\n'
             '    }\n'
             '}\n')

    def test_the_terminal_is_restored_after_a_runtime_error(self):
        code, output, errors = self.drive(self.CRASH, [b"x"])
        self.assertEqual(code, 1, "the program should fail")
        self.assertIn("cannot convert", errors)
        self.assertIn("\x1b[?1049l", output, "the alternate screen was never left")
        self.assertIn("\x1b[?25h", output, "the cursor was never restored")

    def test_the_terminal_is_restored_after_a_clean_exit(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("Clean")\n'
                  '    tui.add(app, tui.text("ready"))\n'
                  '    tui.run(app)\n'
                  '}\n')
        code, output, _errors = self.drive(source, [b"q"])
        self.assertEqual(code, 0)
        self.assertIn("\x1b[?1049l", output)
        self.assertIn("\x1b[?25h", output)


class ExactColourTests(unittest.TestCase):
    def test_exact_palette_slots_are_used_when_available(self):
        calls = []

        class FakeCurses:
            COLORS = 256
            def has_colors(self):
                return True
            def can_change_color(self):
                return True
            def init_color(self, slot, r, g, b):
                calls.append((slot, r, g, b))
            def init_pair(self, pair, fg, bg):
                pass
            def color_pair(self, pair):
                return pair

        app = App("t")
        palette = _Palette(app, FakeCurses())
        index = palette.index((0x45, 0xC6, 0xB0))
        self.assertGreaterEqual(index, 16, "should take an exact slot")
        self.assertTrue(calls, "init_color should have been called")
        slot, r, g, b = calls[0]
        self.assertAlmostEqual(r, round(0x45 * 1000 / 255), delta=1)
        self.assertAlmostEqual(g, round(0xC6 * 1000 / 255), delta=1)

    def test_it_falls_back_to_the_nearest_256_colour(self):
        class FakeCurses:
            COLORS = 256
            def has_colors(self):
                return True
            def can_change_color(self):
                return False
            def init_pair(self, *a):
                pass
            def color_pair(self, pair):
                return pair

        app = App("t")
        palette = _Palette(app, FakeCurses())
        self.assertEqual(palette.index((0x45, 0xC6, 0xB0)),
                         nearest_256((0x45, 0xC6, 0xB0)))


class ExampleTests(unittest.TestCase):
    def test_the_new_examples_compile(self):
        for name in ("tui_calculator.sc", "tui_settings.sc", "tui_dashboard.sc"):
            with self.subTest(example=name):
                completed = subprocess.run(
                    [sys.executable, "-m", "silica", "check",
                     os.path.join(EXAMPLES, name)],
                    cwd=ROOT, capture_output=True, text=True, timeout=120)
                self.assertEqual(completed.returncode, 0, completed.stderr[-500:])

    def test_every_tui_call_in_every_example_exists(self):
        from silica.natives import MODULES
        for name in ("tui_calculator.sc", "tui_settings.sc", "tui_dashboard.sc"):
            source = open(os.path.join(EXAMPLES, name), encoding="utf-8").read()
            for call in set(re.findall(r"\btui\.([a-z_]+)\(", source)):
                with self.subTest(example=name, call=call):
                    self.assertIn(call, MODULES["tui"])


if __name__ == "__main__":
    unittest.main()
