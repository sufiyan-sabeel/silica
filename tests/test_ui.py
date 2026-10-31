"""Tests for the UI DSL: grammar, namespaces, theme, style, markup and events.

The grammar tests are the important ones, because the whole design rests on the
claim that the three changes are additive: every new form was a parse error or a
type error in 0.1.0, so no existing program can change meaning.
"""

import io
import os
import re
import shutil
import tempfile
import unittest

from silica.capabilities import FS_WRITE, CapabilitySet
from silica.checker import Checker
from silica.engine import compile_source, run_chunk
from silica.errors import ParseError, SilicaError, SilicaTypeError
from silica.lexer import tokenize
from silica.natives import MODULES, get_native
from silica.parser import parse
from silica.ui import style as ui_style
from silica.ui import theme as ui_theme
from silica.ui.natives_ui import (ADAPTER_MODULES, CORE_PRIMITIVES, EVENT_ACTIONS,
                                  RESERVED_MODULES)


def parse_source(source):
    tokens, _comments = tokenize(source, "<test>")
    return parse(tokens, "<test>")


def program(body, uses=("ui",)):
    return "".join("use %s\n" % u for u in uses) + "sfn main() {\n" + body + "\n}\n"


class GrammarG1Tests(unittest.TestCase):
    """Dotted module paths in `use`."""

    def test_dotted_use_parses(self):
        parsed = parse_source("use ui.lib.widgets\nsfn main() {\n}\n")
        self.assertEqual(parsed.stmts[0].module, "ui.lib.widgets")

    def test_deeply_dotted_use(self):
        parsed = parse_source("use a.b.c.d\nsfn main() {\n}\n")
        self.assertEqual(parsed.stmts[0].module, "a.b.c.d")

    def test_single_name_use_still_works(self):
        parsed = parse_source("use math\nsfn main() {\n}\n")
        self.assertEqual(parsed.stmts[0].module, "math")

    def test_trailing_dot_is_an_error(self):
        with self.assertRaises(ParseError):
            parse_source("use ui.\nsfn main() {\n}\n")

    def test_dotted_import_requires_the_module(self):
        source = "use ui.lib.nope\nsfn main() {\n}\n"
        with self.assertRaises(SilicaTypeError):
            compile_source(source, "<test>")


class GrammarG2Tests(unittest.TestCase):
    """Member-path resolution: longest imported prefix, then one member."""

    def test_imported_module_resolves(self):
        compile_source(program('ui.lib.widgets.text("hi")',
                               uses=("ui.lib.widgets",)), "<test>")

    def test_submodule_is_available_from_the_parent_import(self):
        # `use ui` brings ui.lib.widgets into scope as well
        compile_source(program('ui.lib.widgets.text("hi")', uses=("ui",)), "<test>")

    def test_longest_prefix_wins(self):
        source = program('ui.lib.widgets.text("hi")',
                         uses=("ui", "ui.lib.widgets"))
        compile_source(source, "<test>")

    def test_module_path_as_a_value_is_an_error(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(program("sprint(ui.lib.widgets)", uses=("ui",)), "<test>")
        self.assertIn("module path, not a value", str(ctx.exception))

    def test_two_members_after_the_module_is_an_error(self):
        source = program("sprint(ui.lib.widgets.nope.text(\"x\"))", uses=("ui",))
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(source, "<test>")
        message = str(ctx.exception)
        self.assertIn("only one member may follow it", message)
        self.assertIn("use ui.lib.widgets.nope", ctx.exception.hint)

    def test_unimported_module_is_named(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source("sfn main() {\n ui.card() {\n }\n}\n", "<test>")
        self.assertIn("not imported", str(ctx.exception))


class GrammarG3Tests(unittest.TestCase):
    """Builder blocks: `call { ... }` in statement position."""

    def test_builder_block_parses(self):
        parsed = parse_source("use ui\nsfn main() {\n ui.card() {\n }\n}\n")
        from silica import ast
        self.assertIsInstance(parsed.stmts[1].body.stmts[0], ast.BuilderStmt)

    def test_builder_block_compiles_and_runs(self):
        source = program('ui.app("t") {\n ui.card() {\n ui.text("x")\n }\n}')
        chunk = compile_source(source, "<test>").chunk
        out = io.StringIO()
        run_chunk(chunk, "<test>", stdin=io.StringIO(""), stdout=out)
        self.assertEqual(out.getvalue(), "")

    def test_head_must_be_a_call(self):
        with self.assertRaises(ParseError) as ctx:
            parse_source("use ui\nsfn main() {\n x { }\n}\n")
        self.assertIn("must follow a call", str(ctx.exception))

    def test_binary_expression_head_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_source("use ui\nsfn main() {\n 1 + 2 { }\n}\n")

    def test_block_must_open_on_the_same_line(self):
        source = "use ui\nsfn main() {\n ui.card()\n {\n }\n}\n"
        with self.assertRaises(ParseError) as ctx:
            parse_source(source)
        self.assertIn("same line", str(ctx.exception))

    def test_block_on_a_non_block_native(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(program('ui.text("hi") {\n}'), "<test>")
        self.assertIn("does not take a block", str(ctx.exception))

    def test_ret_inside_a_builder_block(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(program('ui.app("t") {\n ret\n}'), "<test>")
        self.assertIn("'ret' inside a builder block", str(ctx.exception))

    def test_halt_inside_a_builder_block(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(program('ui.app("t") {\n halt(1)\n}'), "<test>")
        self.assertIn("'halt' inside a builder block", str(ctx.exception))

    def test_nesting_is_unlimited(self):
        body = 'ui.app("t") {\n ui.card() {\n ui.row() {\n ui.text("x")\n }\n }\n}'
        compile_source(program(body), "<test>")

    def test_map_argument_still_works(self):
        compile_source(program('ui.app("t") {\n ui.text("x", {size: "lg"})\n}'),
                       "<test>")

    def test_block_opening_brace_is_never_a_map_literal(self):
        # `{` after a call at statement position is always a builder block
        with self.assertRaises(SilicaError):
            compile_source(program('ui.app("t") {\n ui.text("x") { size: "lg" }\n}'),
                           "<test>")


class AdditivityTests(unittest.TestCase):
    """The three changes must not change the meaning of any 0.1.0 program."""

    def test_existing_programs_still_compile(self):
        source = ('use math\nuse string\n'
                  'sfn square(n: Int) -> Int {\n ret n * n\n}\n'
                  'sfn main() {\n let xs: List = [1, 2, 3]\n'
                  ' per x in xs {\n sprint(square(x))\n }\n'
                  ' sprint(math.sqrt(16.0))\n sprint(string.upper("a"))\n}\n')
        compile_source(source, "<test>")

    def test_bare_brace_statement_is_still_an_error(self):
        with self.assertRaises(ParseError):
            parse_source("sfn main() {\n { }\n}\n")

    def test_bytecode_format_stays_on_major_1(self):
        # Phase 2 added opcodes, so the *minor* version moved to 1.1. The major
        # version is what readers refuse, and 1.0 files must keep loading.
        from silica.bytecode import FORMAT_MAJOR, FORMAT_MINOR
        self.assertEqual(FORMAT_MAJOR, 1)
        self.assertGreaterEqual(FORMAT_MINOR, 0)


class NamespaceTests(unittest.TestCase):
    def test_core_primitives_are_reexported(self):
        for name in CORE_PRIMITIVES:
            with self.subTest(name=name):
                self.assertIsNotNone(get_native("ui", name))

    def test_reexports_never_diverge_from_the_widget_catalogue(self):
        widgets = MODULES["ui.lib.widgets"]
        for name in CORE_PRIMITIVES:
            with self.subTest(name=name):
                self.assertIn(name, widgets)

    def test_every_implemented_name_resolves(self):
        for module, functions in MODULES.items():
            if not module.startswith("ui"):
                continue
            for name in functions:
                with self.subTest(native="%s.%s" % (module, name)):
                    self.assertIsNotNone(get_native(module, name))

    def test_reserved_modules_fail_loudly(self):
        for module, reason in RESERVED_MODULES.items():
            with self.subTest(module=module):
                with self.assertRaises(SilicaTypeError) as ctx:
                    compile_source("use %s\nsfn main() {\n}\n" % module, "<test>")
                self.assertIn("planned but not implemented", str(ctx.exception))
                self.assertIn(reason, str(ctx.exception))

    def test_adapter_modules_fail_loudly(self):
        for module in sorted(ADAPTER_MODULES):
            with self.subTest(module=module):
                with self.assertRaises(SilicaTypeError) as ctx:
                    compile_source("use %s\nsfn main() {\n}\n" % module, "<test>")
                self.assertIn("no adapter installed", str(ctx.exception))

    def test_reserved_modules_are_not_in_the_registry(self):
        for module in list(RESERVED_MODULES) + sorted(ADAPTER_MODULES):
            with self.subTest(module=module):
                self.assertNotIn(module, MODULES)

    def test_internal_names_are_not_callable_from_source(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(program("ui.__end_block()"), "<test>")
        self.assertIn("internal", str(ctx.exception))


class ThemeTests(unittest.TestCase):
    def test_default_theme_passes_aa(self):
        self.assertEqual(ui_theme.contrast_problems(ui_theme.DEFAULT_THEME), [])

    def test_contrast_is_computed_not_assumed(self):
        ratio = ui_theme.contrast_ratio("#FFFFFF", "#000000")
        self.assertAlmostEqual(ratio, 21.0, places=4)
        self.assertAlmostEqual(ui_theme.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0)

    def test_low_contrast_theme_is_an_error(self):
        source = program('ui.theme("Bad", {colors: {background: "#FFFFFF", '
                         'surface: "#FFFFFF", text_primary: "#EEEEEE"}})')
        with self.assertRaises(SilicaError) as ctx:
            run_ui(source)
        self.assertIn("below AA", str(ctx.exception))

    def test_theme_property_is_validated(self):
        with self.assertRaises(SilicaError) as ctx:
            run_ui(program('ui.theme("x", {mode: "neon"})'))
        self.assertIn("light/dark/system", str(ctx.exception).replace(
            '"light", "dark" or "system"', "light/dark/system"))

    def test_unknown_theme_property_suggests(self):
        with self.assertRaises(SilicaError) as ctx:
            run_ui(program('ui.theme("x", {colour: {}})'))
        self.assertIn("did you mean 'colors'", str(ctx.exception))

    def test_tokens_become_css_custom_properties(self):
        css = ui_theme.css_variables(ui_theme.DEFAULT_THEME)
        self.assertIn("--si-color-background: #0B0D10;", css)
        self.assertIn("--si-color-text-primary: #F2F4F6;", css)

    def test_reduced_motion_policy_is_emitted(self):
        css = ui_theme.css_variables(ui_theme.DEFAULT_THEME)
        self.assertIn("prefers-reduced-motion", css)

    def test_blend_and_parse(self):
        self.assertEqual(ui_theme.blend("#000000", "#FFFFFF", 1.0), "#FFFFFF")
        self.assertEqual(ui_theme.parse_color("#FFF"), (1.0, 1.0, 1.0))


class StyleTests(unittest.TestCase):
    def test_property_maps_to_a_declaration(self):
        base, media = ui_style.declarations("card", {"padding": "20px"}, "c")
        self.assertEqual(base, ["padding: 20px;"])
        self.assertEqual(media, [])

    def test_number_becomes_pixels(self):
        base, _ = ui_style.declarations("card", {"padding": 20}, "c")
        self.assertEqual(base, ["padding: 20px;"])

    def test_colour_token_becomes_a_variable(self):
        base, _ = ui_style.declarations("card", {"background": "surface"}, "c")
        self.assertEqual(base, ["background: var(--si-color-surface, surface);"])

    def test_breakpoints_become_media_queries(self):
        base, media = ui_style.declarations(
            "screen", {"padding": {"sm": "12px", "md": "24px"}}, "c")
        self.assertEqual(base, [])
        self.assertEqual([width for width, _ in media], [640, 768])

    def test_unknown_breakpoint_is_an_error(self):
        with self.assertRaises(ui_style.StyleError) as ctx:
            ui_style.validate("screen", {"padding": {"huge": "1px"}})
        self.assertIn("unknown breakpoint", str(ctx.exception))

    def test_unknown_property_suggests_the_nearest_key(self):
        with self.assertRaises(ui_style.StyleError) as ctx:
            ui_style.validate("card", {"padinng": "1px"})
        self.assertIn("did you mean 'padding'", ctx.exception.hint)

    def test_enum_property_rejects_a_bad_name(self):
        with self.assertRaises(ui_style.StyleError):
            ui_style.validate("row", {"align": "middle"})

    def test_elevation_range(self):
        with self.assertRaises(ui_style.StyleError):
            ui_style.validate("card", {"elevation": 9})

    def test_duration_must_be_a_time_string(self):
        with self.assertRaises(ui_style.StyleError) as ctx:
            ui_style.validate("animate", {"duration": 300})
        self.assertIn("300ms", str(ctx.exception))

    def test_animation_always_emits_the_reduced_motion_override(self):
        transition, reduced = ui_style.animation_rule("c", {"duration": "300ms"})
        self.assertIn("transition:", transition)
        self.assertIn("prefers-reduced-motion", reduced)
        self.assertIn("transition: none", reduced)


# --- helpers -----------------------------------------------------------------
def run_ui(source, caps=None, filename="<ui-test>"):
    """Compile and run a UI program, returning the VM."""
    chunk = compile_source(source, filename).chunk
    out = io.StringIO()
    _code, vm = run_chunk_and_vm(chunk, filename, caps, out)
    return vm


def run_chunk_and_vm(chunk, filename, caps, out):
    from silica.vm import VM
    vm = VM(chunk, stdin=io.StringIO(""), stdout=out, stderr=io.StringIO(),
            filename=filename, capabilities=caps)
    code = vm.run(verify=False)
    return code, vm


class RenderTestCase(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.build = os.path.join(self.root, "build")
        os.makedirs(self.build)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def caps(self):
        return CapabilitySet.empty(base=self.root).grant(FS_WRITE, self.root)

    def render(self, body, uses=("ui",), options=None):
        out = os.path.join(self.build, "index.html")
        opts = options or 'out: "%s"' % out
        source = program(body + "\n    ui.render({%s})" % opts, uses=uses)
        chunk = compile_source(source, "<ui-test>").chunk
        stdout = io.StringIO()
        run_chunk_and_vm(chunk, "<ui-test>", self.caps(), stdout)
        with open(out, encoding="utf-8") as handle:
            return handle.read(), stdout.getvalue()


class MarkupTests(RenderTestCase):
    def test_document_shell(self):
        html, _ = self.render('ui.app("My App") {\n ui.text("hello")\n}')
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="en">', html)
        self.assertIn("<title>My App</title>", html)
        self.assertIn('name="viewport"', html)
        self.assertIn("silica-ui-runtime.js", html)
        self.assertIn('id="silica-ui-actions"', html)

    def test_text_is_escaped(self):
        html, _ = self.render('ui.app("t") {\n ui.text("<script>&")}')
        self.assertIn("&lt;script&gt;&amp;", html)
        self.assertNotIn("<script>&", html)

    def test_semantic_roles_are_emitted(self):
        html, _ = self.render('ui.app("t") {\n ui.button("Go")\n}')
        self.assertIn('role="button"', html)
        self.assertIn("<button", html)

    def test_list_items_are_repeated(self):
        body = ('let xs: List = ["a", "b", "c"]\n'
                '    ui.app("t") {\n'
                '        ui.lib.widgets.list(xs) {\n'
                '            ui.text(item)\n'
                '        }\n    }')
        html, _ = self.render(body, uses=("ui",))
        self.assertEqual(html.count(">a<"), 1)
        self.assertEqual(html.count(">b<"), 1)
        self.assertEqual(html.count(">c<"), 1)

    def test_item_is_bound_per_iteration(self):
        body = ('let xs: List = ["one", "two"]\n'
                '    ui.app("t") {\n'
                '        ui.lib.widgets.list(xs) {\n'
                '            ui.text(item)\n'
                '        }\n    }')
        html, _ = self.render(body)
        self.assertIn(">one<", html)
        self.assertIn(">two<", html)

    def test_responsive_padding_emits_media_queries(self):
        html, _ = self.render(
            'ui.app("t") {\n ui.screen({padding: {sm: "12px", md: "24px"}}) {\n }\n}')
        self.assertIn("@media (min-width: 640px)", html)
        self.assertIn("@media (min-width: 768px)", html)

    def test_animation_emits_a_reduced_motion_override(self):
        body = ('ui.app("t") {\n ui.lib.widgets.animate({duration: "300ms"}) {\n'
                ' ui.text("x")\n }\n}')
        html, _ = self.render(body)
        self.assertIn("@media (prefers-reduced-motion: reduce)", html)
        self.assertIn("transition: none", html)

    def test_theme_file_is_written(self):
        self.render('ui.app("t") {\n}')
        with open(os.path.join(self.build, "theme.css"), encoding="utf-8") as handle:
            self.assertIn("--si-color-background", handle.read())

    def test_runtime_file_is_written(self):
        self.render('ui.app("t") {\n}')
        with open(os.path.join(self.build, "silica-ui-runtime.js"), encoding="utf-8") as handle:
            self.assertIn("silica-ui-runtime", handle.read())

    def test_render_prints_the_paths_it_wrote(self):
        _html, stdout = self.render('ui.app("t") {\n}')
        self.assertIn("index.html", stdout)
        self.assertIn("theme.css", stdout)

    def test_image_requires_alt(self):
        with self.assertRaises(SilicaError) as ctx:
            self.render('ui.app("t") {\n ui.lib.widgets.image("a.png")\n}')
        self.assertIn("alt", str(ctx.exception))


class EventTests(RenderTestCase):
    BODY = ('ui.app("t") {\n'
            '    ui.button("Toggle", {id: "b"}) {\n'
            '        ui.on("click") {\n'
            '            ui.state.toggle("dark")\n'
            '            ui.state.set("status", "changed")\n'
            '        }\n'
            '    }\n'
            '    ui.text("", {id: "status", bind_text: "status"})\n'
            '}')

    def test_action_json_is_emitted(self):
        html, _ = self.render(self.BODY)
        match = re.search(r'id="silica-ui-actions">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match)
        payload = match.group(1)
        self.assertIn('"op": "state.toggle"', payload)
        self.assertIn('"op": "state.set"', payload)
        self.assertIn('"value": "changed"', payload)

    def test_handler_attribute_points_at_the_action(self):
        html, _ = self.render(self.BODY)
        self.assertRegex(html, r'data-si-on-click="a\d+"')

    def test_bound_text_is_declarative(self):
        html, _ = self.render(self.BODY)
        self.assertIn('data-si-bind-text="status"', html)

    def test_only_action_names_are_allowed_in_an_event_body(self):
        body = ('ui.app("t") {\n ui.button("b") {\n ui.on("click") {\n'
                ' sprint("nope")\n }\n }\n}')
        with self.assertRaises(SilicaTypeError) as ctx:
            compile_source(program(body), "<test>")
        self.assertIn("only ui.state.set", str(ctx.exception))

    def test_a_computation_before_the_event_body_is_fine(self):
        body = ('let msg: String = "ok"\n'
                '    ui.app("t") {\n        ui.button("b") {\n'
                '            ui.on("click") {\n'
                '                ui.state.set("m", msg)\n'
                '            }\n        }\n    }')
        self.render(body)

    def test_unknown_event_name(self):
        body = ('ui.app("t") {\n ui.button("b") {\n ui.on("explode") {\n'
                ' ui.state.toggle("x")\n }\n }\n}')
        with self.assertRaises(SilicaError) as ctx:
            self.render(body)
        self.assertIn("unsupported event", str(ctx.exception))

    def test_actions_outside_an_event_body(self):
        with self.assertRaises(SilicaError) as ctx:
            self.render('ui.app("t") {\n ui.state.set("a", 1)\n}')
        self.assertIn("ui.on", str(ctx.exception))

    def test_runtime_js_is_dependency_free(self):
        self.render('ui.app("t") {\n}')
        with open(os.path.join(self.build, "silica-ui-runtime.js"), encoding="utf-8") as handle:
            js = handle.read()
        self.assertNotIn("require(", js)
        self.assertNotIn("import ", js)
        self.assertIn("data-si-bind-text", js)


class RendererTests(RenderTestCase):
    def test_web_is_the_only_target(self):
        from silica.ui.web import TARGETS
        self.assertEqual(TARGETS, ("web",))

    def test_unsupported_target_is_rejected(self):
        with self.assertRaises(SilicaError) as ctx:
            self.render('ui.app("t") {\n}', options='target: "android", out: "%s"'
                        % os.path.join(self.build, "x.html"))
        self.assertIn("not implemented", str(ctx.exception))
        self.assertIn("available: web", str(ctx.exception))

    def test_render_needs_fs_write(self):
        out = os.path.join(self.build, "index.html")
        source = program('ui.app("t") {\n}\n    ui.render({out: "%s"})' % out)
        chunk = compile_source(source, "<ui-test>").chunk
        with self.assertRaises(SilicaError) as ctx:
            run_chunk_and_vm(chunk, "<ui-test>", CapabilitySet.empty(base=self.root),
                             io.StringIO())
        self.assertIn("fs.write", str(ctx.exception))

    def test_render_refuses_a_path_outside_the_grant(self):
        out = os.path.join(self.root, "..", "escape.html")
        source = program('ui.app("t") {\n}\n    ui.render({out: "%s"})' % out)
        chunk = compile_source(source, "<ui-test>").chunk
        caps = CapabilitySet.empty(base=self.root).grant(FS_WRITE, self.build)
        with self.assertRaises(SilicaError):
            run_chunk_and_vm(chunk, "<ui-test>", caps, io.StringIO())

    def test_missing_output_directory(self):
        out = os.path.join(self.root, "nope", "index.html")
        source = program('ui.app("t") {\n}\n    ui.render({out: "%s"})' % out)
        chunk = compile_source(source, "<ui-test>").chunk
        with self.assertRaises(SilicaError) as ctx:
            run_chunk_and_vm(chunk, "<ui-test>", self.caps(), io.StringIO())
        self.assertIn("does not exist", str(ctx.exception))

    def test_unknown_render_option(self):
        with self.assertRaises(SilicaError) as ctx:
            self.render('ui.app("t") {\n}',
                        options='out: "%s", targett: "web"'
                        % os.path.join(self.build, "x.html"))
        self.assertIn("unknown option", str(ctx.exception))

    def test_nothing_is_written_without_render(self):
        source = program('ui.app("t") {\n ui.text("x")\n}')
        chunk = compile_source(source, "<ui-test>").chunk
        run_chunk_and_vm(chunk, "<ui-test>", self.caps(), io.StringIO())
        self.assertEqual(os.listdir(self.build), [])

    def test_widget_outside_app(self):
        with self.assertRaises(SilicaError) as ctx:
            run_ui(program('ui.card() {\n}'))
        self.assertIn("must be inside ui.app", str(ctx.exception))

    def test_two_apps_are_rejected(self):
        body = 'ui.app("a") {\n}\n    ui.app("b") {\n}'
        with self.assertRaises(SilicaError) as ctx:
            run_ui(program(body))
        self.assertIn("only one ui.app", str(ctx.exception))


class CompatibilityMatrixTests(unittest.TestCase):
    """Honesty tests: nothing may claim a capability that is not built."""

    def test_no_renderer_other_than_web_is_claimed(self):
        from silica.ui.web import TARGETS
        self.assertEqual(list(TARGETS), ["web"])

    def test_terminal_is_still_reserved(self):
        self.assertIn("ui.lib.terminal", RESERVED_MODULES)

    def test_no_adapter_is_installed(self):
        for module in sorted(ADAPTER_MODULES):
            self.assertNotIn(module, MODULES)

    def test_event_actions_match_the_runtime_js(self):
        from silica.ui.web import RUNTIME_JS
        for action in EVENT_ACTIONS:
            op = action.split(".", 1)[1] if "." in action else action
            with self.subTest(action=action):
                self.assertIn(op, RUNTIME_JS)


if __name__ == "__main__":
    unittest.main()
