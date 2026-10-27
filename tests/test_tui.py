"""TUI tests: layout, rendering, the native bridge, and a real terminal.

Three tiers, because a terminal library can fail at three different levels:

1. **Layout and rendering** — the widget tree is turned into text with no
   terminal involved, so this runs anywhere, including CI with `TERM=dumb`.
2. **The Silica bridge** — imports resolve, natives are registered with the right
   capability, arguments are validated, and errors are located.
3. **A real terminal** — a pseudo-terminal is opened, a Silica program is run
   inside it, keys are sent, and the program is expected to exit cleanly. This is
   the only tier that proves the thing actually works as a terminal application.
"""

import os
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from silica.capabilities import TUI_RUN, CapabilitySet
from silica.errors import CapabilityError, SilicaRuntimeError
from silica.natives import MODULES
from silica.tui import App, Node, TUIError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_with(*children):
    app = App("Test")
    for child in children:
        app.add(child)
    return app


class LayoutTests(unittest.TestCase):
    def test_panel_draws_a_border_and_a_title(self):
        app = app_with(Node("panel", "Greeting"))
        lines = app.render_lines(40, 8)
        self.assertIn("Greeting", lines[0])
        self.assertTrue(lines[0].startswith("\u250c"))
        self.assertTrue(lines[0].rstrip().endswith("\u2510"))
        self.assertTrue(lines[2].startswith("\u2514"))

    def test_heading_is_upper_cased_and_text_is_not(self):
        app = app_with(Node("heading", "silica"), Node("text", "silica"))
        lines = app.render_lines(40, 4)
        self.assertEqual(lines[0].strip(), "SILICA")
        self.assertEqual(lines[1].strip(), "silica")

    def test_button_shows_a_focus_marker(self):
        button = Node("button", "Continue")
        app = app_with(button)
        self.assertIn("[ Continue ]", app.render_lines(40, 3)[0])
        self.assertNotIn(">", app.render_lines(40, 3)[0])
        button.focused = True
        self.assertIn(">", app.render_lines(40, 3)[0])

    def test_list_renders_every_item(self):
        node = Node("list")
        node.items = ["alpha", "beta", "gamma"]
        lines = app_with(node).render_lines(30, 6)
        for item in node.items:
            self.assertTrue(any(item in line for line in lines), item)

    def test_table_renders_rows(self):
        node = Node("table")
        node.rows = [["name", "value"], ["a", "1"], ["b", "2"]]
        lines = app_with(node).render_lines(30, 6)
        self.assertIn("name", lines[0])
        self.assertIn("value", lines[0])
        self.assertIn("a", lines[1])

    def test_divider_fills_the_width(self):
        line = app_with(Node("divider")).render_lines(20, 2)[0]
        self.assertEqual(line, "\u2500" * 20)

    def test_spacer_occupies_its_height(self):
        app = app_with(Node("text", "top"), Node("spacer"), Node("text", "bottom"))
        app.root.children[1].props["height"] = 3
        lines = app.render_lines(20, 8)
        self.assertEqual(lines[0].strip(), "top")
        self.assertEqual(lines[4].strip(), "bottom")

    def test_row_splits_the_width(self):
        row = Node("row")
        row.add(Node("text", "left"))
        row.add(Node("text", "right"))
        lines = app_with(row).render_lines(40, 3)
        self.assertIn("left", lines[0])
        self.assertIn("right", lines[0])
        self.assertLess(lines[0].index("left"), lines[0].index("right"))

    def test_long_text_is_clipped_not_wrapped_over_the_edge(self):
        app = app_with(Node("text", "x" * 100))
        lines = app.render_lines(20, 2)
        self.assertLessEqual(len(lines[0]), 20)

    def test_an_empty_app_renders_without_crashing(self):
        lines = App("empty").render_lines(20, 4)
        self.assertEqual(len(lines), 4)

    def test_focus_moves_between_focusable_widgets(self):
        button = Node("button", "one")
        field = Node("input", "")
        app = app_with(Node("text", "label"), button, field)
        self.assertIs(app.focused(), button)
        self.assertIs(app.focus_next(), field)
        self.assertIs(app.focus_next(), button)

    def test_focus_skips_widgets_that_cannot_take_it(self):
        app = app_with(Node("text", "label"), Node("divider"), Node("button", "b"))
        self.assertEqual([n.kind for n in app.focusables()], ["button"])


class BridgeTests(unittest.TestCase):
    def test_the_documented_namespaces_exist(self):
        for module in ("tui", "tui.lib.widgets", "tui.lib.layout", "tui.lib.style"):
            with self.subTest(module=module):
                self.assertIn(module, MODULES)
                self.assertTrue(MODULES[module], "%s has no functions" % module)

    def test_widget_constructors_are_registered(self):
        widgets = MODULES["tui.lib.widgets"]
        for name in ("app", "panel", "text", "heading", "button", "field",
                     "list", "table", "divider", "spacer", "row", "column"):
            with self.subTest(widget=name):
                self.assertIn(name, widgets)

    def test_the_screen_functions_need_the_capability(self):
        for name in ("render", "poll", "run"):
            with self.subTest(native=name):
                self.assertEqual(MODULES["tui"][name].requires, TUI_RUN)

    def test_building_a_widget_needs_no_capability(self):
        for name in ("app", "panel", "text", "button"):
            with self.subTest(native=name):
                self.assertIsNone(MODULES["tui"][name].requires)

    def test_rendering_without_the_capability_is_refused(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let lines = tui.render(app)\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, CapabilityError)
        self.assertIn("tui.run", str(error))

    def test_a_widget_handle_cannot_be_confused_with_a_number(self):
        source = ('use tui\nsfn main() {\n'
                  '    tui.add(1, 2)\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, SilicaRuntimeError)
        self.assertIn("not an application or a widget", str(error))

    def test_adding_a_child_to_a_leaf_widget_is_refused(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let label = tui.text("hi")\n'
                  '    tui.add(label, tui.text("no"))\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, SilicaRuntimeError)
        self.assertIn("cannot contain children", str(error))

    def test_list_needs_a_list(self):
        source = ('use tui\nsfn main() {\n    let l = tui.list("nope")\n}\n')
        from silica.errors import SilicaTypeError
        self.assertIsInstance(run_source(source), SilicaTypeError)

    def test_selected_returns_the_focused_widget_text(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let button = tui.button("Continue")\n'
                  '    tui.add(app, button)\n'
                  '    sprint(tui.selected(app))\n}\n')
        out = run_source(source, capture=True)
        self.assertEqual(out.strip(), "Continue")

    def test_set_text_and_value_round_trip(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let field = tui.field("")\n'
                  '    tui.add(app, field)\n'
                  '    tui.set_text(field, "typed")\n'
                  '    sprint(tui.value(field))\n}\n')
        self.assertEqual(run_source(source, capture=True).strip(), "typed")

    def test_theme_tokens_are_stored(self):
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    tui.theme(app, {"accent": "magenta"})\n'
                  '    sprint(tui.tokens(app)["accent"])\n}\n')
        self.assertEqual(run_source(source, capture=True).strip(), "magenta")

    def test_a_tui_needs_a_terminal(self):
        """poll() on a non-tty must fail clearly, not hang."""
        source = ('use tui\nsfn main() {\n'
                  '    let app = tui.app("x")\n'
                  '    let key = tui.poll(app)\n}\n')
        error = run_source(source, capabilities=CapabilitySet.empty().grant(TUI_RUN, "."))
        self.assertIsInstance(error, SilicaRuntimeError)
        self.assertIn("not a tty", str(error))


class TerminalTests(unittest.TestCase):
    """Drive a real program through a pseudo-terminal."""

    def run_in_pty(self, script, keys=b"q", timeout=25):
        directory = tempfile.mkdtemp(prefix="silica-tui-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "app.sc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)

        master, slave = pty.openpty()
        env = dict(os.environ)
        env.update({"TERM": "xterm-256color", "PYTHONPATH": ROOT,
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
        process = subprocess.Popen(
            [sys.executable, "-m", "silica", "run", path, "--allow-tui"],
            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT,
            close_fds=True)
        os.close(slave)

        output = b""
        deadline = time.time() + timeout
        sent = False
        try:
            while time.time() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                    if not sent and output:
                        # any output means curses has initialised and the first
                        # frame is drawn; the loop is then waiting for a key
                        time.sleep(0.3)
                        os.write(master, keys)
                        sent = True
                if process.poll() is not None:
                    break
            process.wait(timeout=5)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
        return process.returncode, output.decode("utf-8", "replace")

    def test_a_program_renders_and_exits_on_the_quit_key(self):
        script = (
            'use tui\n'
            'use tui.lib.widgets\n'
            'sfn main() {\n'
            '    let app = tui.app("Silica Terminal")\n'
            '    let panel = tui.panel("Welcome")\n'
            '    tui.add(panel, tui.heading("Silica TUI"))\n'
            '    tui.add(app, panel)\n'
            '    tui.add(app, tui.button("Continue"))\n'
            '    tui.run(app)\n'
            '}\n')
        code, output = self.run_in_pty(script)
        self.assertEqual(code, 0, output[-2000:])
        self.assertIn("SILICA TUI", output)  # headings render upper-case
        self.assertIn("Welcome", output)

    def test_keys_reach_the_program(self):
        script = (
            'use tui\n'
            'use tui.lib.widgets\n'
            'sfn main() {\n'
            '    let app = tui.app("Keys")\n'
            '    tui.add(app, tui.text("press q"))\n'
            '    tant oui {\n'
            '        let key = tui.poll(app)\n'
            '        si key == "q" {\n'
            '            tui.close(app)\n'
            '            halt\n'
            '        }\n'
            '        si len(key) > 0 {\n'
            '            sprint("key: " + key)\n'
            '        }\n'
            '    }\n'
            '}\n')
        code, output = self.run_in_pty(script, keys=b"xq")
        self.assertEqual(code, 0, output[-2000:])
        self.assertIn("key: x", output)

    def test_the_terminal_is_restored_after_exit(self):
        script = (
            'use tui\n'
            'sfn main() {\n'
            '    let app = tui.app("Restore")\n'
            '    tui.run(app)\n'
            '    sprint("clean exit")\n'
            '}\n')
        code, output = self.run_in_pty(script)
        self.assertEqual(code, 0, output[-2000:])
        self.assertIn("clean exit", output)
        # curses endwin() restores the cursor; without it the shell prompt is lost
        self.assertTrue(output.rstrip().endswith("clean exit"), output[-200:])


def run_source(source, capture=False, capabilities=None):
    """Run Silica source and return the error it raised, or its output."""
    import io
    from silica.engine import compile_source, run_chunk
    out = io.StringIO()
    try:
        chunk = compile_source(source, "<test>").chunk
        run_chunk(chunk, "<test>", stdin=io.StringIO(""), stdout=out,
                  stderr=io.StringIO(),
                  capabilities=capabilities or CapabilitySet.empty())
    except Exception as exc:  # noqa: BLE001 - the test asserts on the type
        return exc
    return out.getvalue() if capture else None


if __name__ == "__main__":
    unittest.main()
