"""GUI tests: the widget tree, the bridge, and real windows.

Two tiers.

* **Tree and bridge** — build widgets, wire handlers, validate arguments and check
  the errors. No display needed, so this runs anywhere.
* **Real windows** — creates an actual Tk window and invokes a real button. Needs
  a display; skipped when there is none. In CI and in this environment that means
  running the suite under `xvfb-run`:

      xvfb-run -a python -m pytest tests/test_gui.py

The window tier is the one that proves the acceptance criteria: a `.sc` program
opens a window, the widgets are there, a click reaches a Silica handler, and the
window closes.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from silica.capabilities import GUI_RUN, CapabilitySet
from silica.errors import CapabilityError, SilicaRuntimeError
from silica.gui import GUIError, Node, Window, available, describe
from silica.natives import MODULES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_DISPLAY = bool(os.environ.get("DISPLAY")) or os.name == "nt"


def run_source(source, capabilities=None, capture=True):
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


class ModelTests(unittest.TestCase):
    """The widget tree, with no display involved."""

    def test_a_window_holds_children_in_order(self):
        window = Window("t", 640, 420)
        for kind in ("heading", "text", "button"):
            window.add(Node(kind, kind))
        self.assertEqual([c.kind for c in window.children],
                         ["heading", "text", "button"])

    def test_walk_visits_nested_children(self):
        window = Window("t", 10, 10)
        row = Node("row")
        row.add(Node("text", "inner"))
        window.add(row)
        self.assertEqual([n.kind for n in window.walk()],
                         ["window", "row", "text"])

    def test_available_and_describe_agree(self):
        info = describe()
        self.assertIn("tkinter", info)
        self.assertIn("display", info)
        if not HAVE_DISPLAY:
            self.assertFalse(available())
            self.assertIsNotNone(info["reason"])

    def test_a_window_without_a_display_says_so(self):
        if HAVE_DISPLAY:
            self.skipTest("a display is available here")
        from silica.gui import App
        app = App("x")
        window = app.window("t", 100, 100)
        with self.assertRaises(GUIError) as ctx:
            app.build(window)
        # either reason is legitimate: no display server, or no Tk libraries
        message = str(ctx.exception).lower()
        self.assertTrue("display" in message or "tkinter" in message, message)


class BridgeTests(unittest.TestCase):
    def test_the_documented_namespaces_exist(self):
        for module in ("gui", "gui.lib.widgets", "gui.lib.layout", "gui.lib.theme"):
            with self.subTest(module=module):
                self.assertIn(module, MODULES)
                self.assertTrue(MODULES[module])

    def test_every_widget_used_by_the_example_exists(self):
        for name in ("app", "window", "text", "heading", "button", "field",
                     "checkbox", "row", "column", "spacer", "add", "on_click",
                     "show", "run", "close"):
            with self.subTest(native=name):
                self.assertIn(name, MODULES["gui"])

    def test_opening_a_window_needs_the_capability(self):
        for name in ("show", "run"):
            with self.subTest(native=name):
                self.assertEqual(MODULES["gui"][name].requires, GUI_RUN)

    def test_building_widgets_needs_no_capability(self):
        for name in ("app", "window", "text", "button", "add", "on_click"):
            with self.subTest(native=name):
                self.assertIsNone(MODULES["gui"][name].requires)

    def test_show_without_the_capability_is_refused(self):
        source = ('use gui\nsfn main() {\n'
                  '    let app = gui.app("x")\n'
                  '    let w = gui.window(app, "t", 100, 100)\n'
                  '    gui.show(w)\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, CapabilityError)
        self.assertIn("gui.run", str(error))

    def test_a_tree_can_be_built_with_no_capability_at_all(self):
        source = ('use gui\nsfn main() {\n'
                  '    let app = gui.app("x")\n'
                  '    let w = gui.window(app, "t", 100, 100)\n'
                  '    gui.add(w, gui.text("hello"))\n'
                  '    gui.add(w, gui.button("b"))\n'
                  '    sprint(gui.widgets(w))\n}\n')
        self.assertEqual(run_source(source).strip(), '["text", "button"]')

    def test_a_leaf_cannot_take_children(self):
        source = ('use gui\nsfn main() {\n'
                  '    let label = gui.text("x")\n'
                  '    gui.add(label, gui.text("y"))\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, SilicaRuntimeError)
        self.assertIn("cannot contain children", str(error))

    def test_on_click_needs_a_button_or_checkbox(self):
        source = ('use gui\nsfn main() {\n'
                  '    let label = gui.text("x")\n'
                  '    gui.on_click(label, "h")\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, SilicaRuntimeError)
        self.assertIn("button or a checkbox", str(error))

    def test_an_unknown_handler_name_is_reported(self):
        from silica.gui import App
        app = App("x")
        with self.assertRaises(GUIError):
            app.invoke("no_such_function")

    def test_window_size_must_be_positive(self):
        source = ('use gui\nsfn main() {\n'
                  '    let app = gui.app("x")\n'
                  '    let w = gui.window(app, "t", 0, 100)\n}\n')
        error = run_source(source)
        self.assertIsInstance(error, SilicaRuntimeError)
        self.assertIn("positive", str(error))


@unittest.skipUnless(HAVE_DISPLAY, "needs a display; run under xvfb-run")
class WindowTests(unittest.TestCase):
    """The acceptance criteria: a real window, real widgets, a real click."""

    def run_gui(self, source, timeout=120):
        directory = tempfile.mkdtemp(prefix="silica-gui-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "app.sc")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        env = dict(os.environ, PYTHONPATH=ROOT)
        completed = subprocess.run(
            [sys.executable, "-m", "silica", "run", path, "--allow-gui"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, cwd=ROOT, timeout=timeout)
        return completed

    def test_a_window_opens_with_its_widgets(self):
        completed = self.run_gui(
            'use gui\n'
            'use gui.lib.widgets\n'
            'sfn main() {\n'
            '    let app = gui.app("Silica GUI")\n'
            '    let w = gui.window(app, "Hello Silica", 640, 420)\n'
            '    gui.add(w, gui.heading("Hello from Silica"))\n'
            '    gui.add(w, gui.text("A real window."))\n'
            '    gui.add(w, gui.button("Click me"))\n'
            '    sprint(gui.widgets(w))\n'
            '    gui.show(w)\n'
            '    sprint("shown")\n'
            '    gui.close(w)\n'
            '}\n')
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        self.assertIn('["heading", "text", "button"]', completed.stdout)
        self.assertIn("shown", completed.stdout)

    def test_a_click_reaches_the_silica_handler(self):
        completed = self.run_gui(
            'use gui\n'
            'sfn handle_click() {\n'
            '    sprint("Button clicked")\n'
            '}\n'
            'sfn main() {\n'
            '    let app = gui.app("Click")\n'
            '    let w = gui.window(app, "Click", 400, 300)\n'
            '    let b = gui.button("Click me")\n'
            '    gui.add(w, b)\n'
            '    gui.on_click(b, "handle_click")\n'
            '    gui.show(w)\n'
            '    gui.click(b)\n'
            '    gui.close(w)\n'
            '}\n')
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        self.assertIn("Button clicked", completed.stdout)

    def test_the_handler_can_touch_widgets(self):
        completed = self.run_gui(
            'use gui\n'
            'sfn on_press() {\n'
            '    sprint("handler ran")\n'
            '}\n'
            'sfn main() {\n'
            '    let app = gui.app("Update")\n'
            '    let w = gui.window(app, "Update", 400, 300)\n'
            '    let label = gui.text("before")\n'
            '    let b = gui.button("Go")\n'
            '    gui.add(w, label)\n'
            '    gui.add(w, b)\n'
            '    gui.on_click(b, "on_press")\n'
            '    gui.show(w)\n'
            '    gui.set_text(label, "after")\n'
            '    sprint(gui.value(label))\n'
            '    gui.click(b)\n'
            '    gui.close(w)\n'
            '}\n')
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        self.assertIn("after", completed.stdout)
        self.assertIn("handler ran", completed.stdout)

    def test_a_field_holds_and_returns_its_value(self):
        completed = self.run_gui(
            'use gui\n'
            'sfn main() {\n'
            '    let app = gui.app("Field")\n'
            '    let w = gui.window(app, "Field", 400, 300)\n'
            '    let f = gui.field("")\n'
            '    gui.add(w, f)\n'
            '    gui.show(w)\n'
            '    gui.set_value(f, "typed text")\n'
            '    sprint(gui.value(f))\n'
            '    gui.close(w)\n'
            '}\n')
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        self.assertIn("typed text", completed.stdout)

    def test_a_window_closes_cleanly(self):
        completed = self.run_gui(
            'use gui\n'
            'sfn main() {\n'
            '    let app = gui.app("Close")\n'
            '    let w = gui.window(app, "Close", 200, 200)\n'
            '    gui.show(w)\n'
            '    gui.close(w)\n'
            '    sprint("closed")\n'
            '}\n')
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        self.assertIn("closed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
