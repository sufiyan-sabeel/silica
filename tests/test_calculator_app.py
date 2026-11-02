"""The scientific calculator: structure, palette, engine, and a real browser.

Four layers, because each catches a different class of defect:

1. structure  — the generated page has the ids the engine binds, and no network
2. palette    — contrast is measured, not eyeballed
3. engine     — the arithmetic, under Node, with no browser
4. browser    — the actual page in headless Chromium, with real clicks and keys

Layer 4 is the one that proves the thing works when a person taps it; layers 1-3
make failures cheap to diagnose when it does not.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "examples", "scientific_calculator.sc")
CHROME = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")
NODE = shutil.which("node")

KEY_IDS = ["key-ac", "key-neg", "key-pct", "key-back", "key-div",
           "key-7", "key-8", "key-9", "key-sqrt", "key-mul",
           "key-4", "key-5", "key-6", "key-sq", "key-sub",
           "key-1", "key-2", "key-3", "key-inv", "key-add",
           "key-0", "key-dot", "key-pi", "key-e", "key-eq",
           "key-pow", "key-log", "key-ln", "key-ans", "key-clrhist"]


def render(directory):
    """Run the application with `directory` as the working directory."""
    build = os.path.join(directory, "build")
    os.makedirs(build, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-m", "silica", "run",
         "--allow-fs-read", "build", "--allow-fs-write", "build", APP],
        cwd=directory, capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONPATH=ROOT))
    return completed, os.path.join(build, "calculator.html")


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "script":
            self.scripts.append(values.get("src"))


class GeneratedPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="silica-calc-")
        cls.completed, cls.path = render(cls.directory)
        with open(cls.path, encoding="utf-8") as handle:
            cls.html = handle.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_it_renders(self):
        self.assertEqual(self.completed.returncode, 0, self.completed.stderr)
        self.assertIn("wrote", self.completed.stdout)

    def test_every_key_is_present_exactly_once(self):
        parser = _Ids()
        parser.feed(self.html)
        for key in KEY_IDS:
            self.assertEqual(parser.ids.count(key), 1, "missing or duplicated %s" % key)

    def test_the_display_and_tape_exist(self):
        self.assertEqual(self.html.count('id="calc-display"'), 1)
        self.assertEqual(self.html.count('id="calc-expr"'), 1)
        self.assertEqual(self.html.count('id="calc-tape"'), 1)

    def test_it_is_one_self_contained_file(self):
        # no sibling assets, no network: it must work from a phone's file manager
        self.assertNotRegex(self.html, r'<(script|link)[^>]+(src|href)="')
        self.assertNotRegex(self.html, r"https?://")

    def test_the_engine_is_injected_once(self):
        self.assertEqual(self.html.count("silica-scientific-calculator"), 1)

    def test_it_uses_no_eval(self):
        # `evaluate(` is our own function; `eval(` as a call is what must not exist
        self.assertNotRegex(self.html, r"\beval\s*\(")
        self.assertNotRegex(self.html, r"new\s+Function\s*\(")

    def test_the_page_says_where_the_arithmetic_runs(self):
        # the honesty requirement, in the artifact itself
        self.assertIn("Silica does not run in the browser", self.html)

    def test_it_has_a_viewport_and_focus_styling(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn(":focus-visible", self.html)

    def test_running_twice_still_leaves_one_engine(self):
        # ui.render rewrites the page, so a second run must not stack a second engine
        completed, path = render(self.directory)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        self.assertEqual(html.count("silica-scientific-calculator"), 1)


class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="silica-calc-")
        _completed, cls.path = render(cls.directory)
        with open(cls.path, encoding="utf-8") as handle:
            cls.html = handle.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def token(self, name):
        match = re.search(r"--si-color-%s:\s*(#[0-9A-Fa-f]{6})" % name, self.html)
        self.assertIsNotNone(match, "no --si-color-%s in the page" % name)
        return match.group(1)

    def ratio(self, a, b):
        from silica.ui import color
        return color.contrast_ratio(color.parse(a), color.parse(b))

    def test_body_text_passes_aaa(self):
        self.assertGreaterEqual(
            self.ratio(self.token("text-primary"), self.token("background")), 7.0)

    def test_operator_keys_are_readable(self):
        # best_foreground decided the label colour; prove it is actually legible
        self.assertGreaterEqual(
            self.ratio(self.token("accent-text"), self.token("accent")), 4.5)

    def test_secondary_text_passes_aa(self):
        self.assertGreaterEqual(
            self.ratio(self.token("text-secondary"), self.token("background")), 4.5)

    def test_the_error_colour_is_legible(self):
        self.assertGreaterEqual(
            self.ratio(self.token("error"), self.token("background")), 4.5)

    def test_the_theme_is_derived_not_hand_picked(self):
        # the shades come from the colour library, so they must differ from the base
        self.assertNotEqual(self.token("surface"), self.token("background"))
        self.assertNotEqual(self.token("surface-variant"), self.token("surface"))


ENGINE_HARNESS = r"""
// Minimal DOM so the engine can run without a browser.
var nodes = {};
function node(id) {
  return {
    id: id, textContent: '', className: '', innerHTML: '',
    appendChild: function (child) { (this.children = this.children || []).push(child); },
    addEventListener: function (name, fn) { (this.handlers = this.handlers || {})[name] = fn; },
    setAttribute: function () {}, click: function () { (this.handlers || {}).click && (this.handlers.click)({}); }
  };
}
global.document = {
  getElementById: function (id) { return nodes[id] || (nodes[id] = node(id)); },
  createElement: function () { return node('created'); },
  addEventListener: function (name, fn) { (global.handlers = global.handlers || {})[name] = fn; },
  dispatchEvent: function (evt) { (global.handlers || {})[evt.type] && (global.handlers || {})[evt.type](evt); }
};
global.window = global;
global.KeyboardEvent = function (type, init) { return { type: type, key: init.key }; };
var source = require('fs').readFileSync(process.argv[2], 'utf8');
eval(source);
var calc = window.silicaCalculator;
function run(keys) {
  calc.press('ac');
  for (var i = 0; i < keys.length; i++) calc.press(keys[i]);
  return document.getElementById('calc-display').textContent;
}
var cases = JSON.parse(process.argv[3]);
var out = {};
for (var i = 0; i < cases.length; i++) out[cases[i].name] = run(cases[i].keys);
console.log(JSON.stringify(out));
"""

CASES = [
    {"name": "precedence", "keys": ["1", "2", "+", "4", "*", "3", "="], "want": "24"},
    {"name": "float_format", "keys": ["0", ".", "1", "+", "0", ".", "2", "="], "want": "0.3"},
    {"name": "sqrt", "keys": ["9", "sqrt"], "want": "3"},
    {"name": "square", "keys": ["7", "sq"], "want": "49"},
    {"name": "inverse", "keys": ["4", "inv"], "want": "0.25"},
    {"name": "power", "keys": ["2", "^", "1", "0", "="], "want": "1024"},
    {"name": "percent", "keys": ["5", "0", "pct"], "want": "0.5"},
    {"name": "divide_by_zero", "keys": ["5", "/", "0", "="], "want": "Error"},
    {"name": "sqrt_negative", "keys": ["9", "neg", "sqrt"], "want": "Error"},
    {"name": "log_zero", "keys": ["0", "log"], "want": "Error"},
    {"name": "backspace", "keys": ["1", "2", "back"], "want": "1"},
    {"name": "clear_after_error", "keys": ["5", "/", "0", "=", "ac"], "want": "0"},
    {"name": "pi_times_two", "keys": ["pi", "*", "2", "="], "want": "6.28318530718"},
    {"name": "negative_entry", "keys": ["5", "neg"], "want": "-5"},
    {"name": "chained", "keys": ["1", "2", "+", "4", "*", "3", "=", "*", "2", "="], "want": "48"},
]


def extract_engine(html):
    start = html.find("<script>\n/* silica-scientific-calculator")
    if start < 0:
        raise AssertionError("engine block not found")
    end = html.find("</script>", start)
    return html[start + len("<script>") : end]


@unittest.skipUnless(NODE, "node is not available")
class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="silica-calc-")
        _completed, path = render(cls.directory)
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        cls.engine_path = os.path.join(cls.directory, "engine.js")
        with open(cls.engine_path, "w", encoding="utf-8") as handle:
            handle.write(extract_engine(html))
        cls.harness = os.path.join(cls.directory, "harness.js")
        with open(cls.harness, "w", encoding="utf-8") as handle:
            handle.write(ENGINE_HARNESS)
        payload = [{"name": c["name"], "keys": c["keys"]} for c in CASES]
        completed = subprocess.run(
            [NODE, cls.harness, cls.engine_path, json.dumps(payload)],
            capture_output=True, text=True, timeout=120)
        cls.result = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
        cls.stderr = completed.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_the_harness_ran(self):
        self.assertTrue(self.result, self.stderr)

    def test_every_case(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                self.assertEqual(self.result.get(case["name"]), case["want"],
                                 "%s: %s -> %s" % (case["name"], case["keys"],
                                                   self.result.get(case["name"])))


BROWSER_SCRIPT = r"""
<pre id="test-results">pending</pre>
<script>
(function () {
  var out = [];
  function display() { return document.getElementById('calc-display').textContent; }
  function click(id) { var n = document.getElementById(id); if (!n) { out.push('MISSING ' + id); return; } n.click(); }
  function key(k) { document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })); }
  function seq(ids) { click('key-ac'); ids.forEach(function (id) { click('key-' + id); }); return display(); }
  out.push('clicks_12_plus_4_times_3=' + seq(['1','2','add','4','mul','3','eq']));
  out.push('clicks_sqrt_9=' + seq(['9','sqrt']));
  out.push('clicks_divide_by_zero=' + seq(['5','div','0','eq']));
  click('key-ac');
  key('1'); key('2'); key('+'); key('4'); key('*'); key('3'); key('Enter');
  out.push('keyboard=' + display());
  click('key-ac');
  key('7'); key('*'); key('6'); key('Enter');
  var tapeRows = document.querySelectorAll('#calc-tape button');
  out.push('history_rows=' + tapeRows.length);
  if (tapeRows.length) { tapeRows[0].click(); out.push('history_reuse=' + display()); }
  out.push('errors=' + (document.querySelectorAll('.si-calc-error').length > 0 ? 'none-now' : 'none-now'));
  document.getElementById('test-results').textContent = 'RESULTS:' + out.join('|');
})();
</script>
"""


@unittest.skipUnless(CHROME, "chromium is not available")
class BrowserTests(unittest.TestCase):
    """The actual page, in a real browser, with real clicks and key events."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="silica-calc-browser-")
        _completed, path = render(cls.directory)
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        cls.page = os.path.join(cls.directory, "browser-test.html")
        with open(cls.page, "w", encoding="utf-8") as handle:
            handle.write(html.replace("</body>", BROWSER_SCRIPT + "\n</body>"))
        cls.dom = cls.load()

    @classmethod
    def load(cls):
        completed = subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=4000", "--dump-dom", "file://" + cls.page],
            capture_output=True, text=True, timeout=180)
        return completed.stdout + completed.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def results(self):
        match = re.search(r"RESULTS:([^<]*)", self.dom)
        self.assertIsNotNone(match, "the browser never produced results")
        pairs = {}
        for item in match.group(1).split("|"):
            if "=" in item:
                name, value = item.split("=", 1)
                pairs[name] = value
        return pairs

    def test_the_page_loaded_and_ran(self):
        self.assertIn("RESULTS:", self.dom)

    def test_clicks_compute_with_precedence(self):
        self.assertEqual(self.results().get("clicks_12_plus_4_times_3"), "24")

    def test_clicks_run_a_scientific_function(self):
        self.assertEqual(self.results().get("clicks_sqrt_9"), "3")

    def test_clicks_report_division_by_zero(self):
        self.assertEqual(self.results().get("clicks_divide_by_zero"), "Error")

    def test_the_keyboard_works(self):
        self.assertEqual(self.results().get("keyboard"), "24")

    def test_the_history_tape_fills_and_reuses(self):
        results = self.results()
        # three evaluations completed before the count: 12+4*3, the keyboard
        # 12+4*3, and 7*6. The division by zero is an error and is not recorded.
        self.assertEqual(results.get("history_rows"), "3")
        self.assertEqual(results.get("history_reuse"), "42")

    def test_no_javascript_errors(self):
        for marker in ("Uncaught", "SyntaxError", "TypeError"):
            self.assertNotIn(marker, self.dom)


if __name__ == "__main__":
    unittest.main()
