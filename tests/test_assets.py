"""Brand assets and editor integration.

The logo is a binary asset, so these tests check the things that can actually be
verified without a browser or an editor: that every file exists and decodes, that
the icon set is complete and square, that the colours survived the crop, that the
editor manifests are valid and every path they name resolves, and that the
grammar covers the whole keyword vocabulary the lexer defines.

What these tests cannot do is prove the icon *looks* right in VS Code's explorer.
That needs an editor, and the README says so.
"""

import json
import os
import unittest

from silica.tokens import BUILTIN_TYPES, KEYWORDS

try:
    from PIL import Image
    HAVE_PILLOW = True
except ModuleNotFoundError:  # pragma: no cover - the extra is optional
    Image = None
    HAVE_PILLOW = False

needs_pillow = unittest.skipUnless(
    HAVE_PILLOW, "Pillow is not installed (pip install .[dev]); image checks skipped")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(ROOT, "assets", "logo")
ICONS = os.path.join(LOGO, "icons")
VSCODE = os.path.join(ROOT, "editors", "vscode")

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class LogoAssetTests(unittest.TestCase):
    def test_the_three_source_variants_exist(self):
        for name in ("silica-logo.png", "silica-symbol.png",
                     "silica-symbol-monochrome.png",
                     "silica-symbol-transparent.png"):
            with self.subTest(name=name):
                self.assertTrue(os.path.exists(os.path.join(LOGO, name)), name)

    @needs_pillow
    def test_assets_decode_as_png(self):
        for name in ("silica-logo.png", "silica-symbol.png",
                     "silica-symbol-monochrome.png",
                     "silica-symbol-transparent.png"):
            with self.subTest(name=name):
                with Image.open(os.path.join(LOGO, name)) as image:
                    image.load()
                    self.assertEqual(image.format, "PNG")
                    self.assertGreater(image.width, 100)
                    self.assertGreater(image.height, 100)

    @needs_pillow
    def test_the_crops_are_not_the_whole_sheet(self):
        """Each variant must be a crop, not the full three-up sheet."""
        with Image.open(os.path.join(LOGO, "silica-logo.png")) as full:
            self.assertLess(full.width, 2816)
        with Image.open(os.path.join(LOGO, "silica-symbol.png")) as symbol:
            self.assertLess(symbol.width, 900)

    @needs_pillow
    def test_the_wordmark_crop_contains_the_accent_colour(self):
        """The terracotta accent must survive the crop, so the brand is intact."""
        with Image.open(os.path.join(LOGO, "silica-logo.png")) as image:
            rgb = image.convert("RGB")
            colours = rgb.getcolors(maxcolors=1 << 24) or []
        # the accent is a warm mid-tone: red clearly above green, green above blue
        warm = [count for count, (r, g, b) in colours
                if r > g > b and r - b > 40 and 120 < r < 230]
        self.assertTrue(warm, "no warm accent pixels found in the full logo")

    @needs_pillow
    def test_the_symbol_has_ink(self):
        """A solid or empty crop would mean the extraction failed."""
        with Image.open(os.path.join(LOGO, "silica-symbol-transparent.png")) as image:
            rgba = image.convert("RGBA")
            raw = rgba.tobytes()
            alphas = raw[3::4]
        opaque = sum(1 for a in alphas if a > 200)
        clear = sum(1 for a in alphas if a < 20)
        self.assertGreater(opaque, 1000, "the mark has almost no opaque pixels")
        self.assertGreater(clear, 1000, "the background was not removed")

    @needs_pillow
    def test_the_monochrome_variant_is_greyscale(self):
        with Image.open(os.path.join(LOGO, "silica-symbol-monochrome.png")) as image:
            raw = image.convert("RGB").tobytes()
        pixels = [tuple(raw[i:i + 3]) for i in range(0, min(len(raw), 15000), 3)]
        for px in pixels:
            self.assertLess(max(px) - min(px), 12, "monochrome crop has colour")


class IconSetTests(unittest.TestCase):
    @needs_pillow
    def test_every_size_exists_and_is_square(self):
        for size in ICON_SIZES:
            path = os.path.join(ICONS, "silica-%d.png" % size)
            with self.subTest(size=size):
                self.assertTrue(os.path.exists(path), path)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (size, size))
                    self.assertEqual(image.mode, "RGBA")

    @needs_pillow
    def test_icons_have_transparent_corners(self):
        """A square with an opaque background looks wrong in a dark theme."""
        for size in (32, 64, 128):
            path = os.path.join(ICONS, "silica-%d.png" % size)
            with self.subTest(size=size):
                with Image.open(path) as image:
                    rgba = image.convert("RGBA")
                    for corner in ((0, 0), (size - 1, 0), (0, size - 1),
                                   (size - 1, size - 1)):
                        self.assertEqual(rgba.getpixel(corner)[3], 0, corner)

    @needs_pillow
    def test_favicon_is_a_multi_size_ico(self):
        path = os.path.join(ICONS, "favicon.ico")
        self.assertTrue(os.path.exists(path))
        with Image.open(path) as image:
            self.assertEqual(image.format, "ICO")
            sizes = sorted({s[0] for s in image.info.get("sizes", set())} or
                           [image.size[0]])
        self.assertGreaterEqual(len(sizes), 2, sizes)

    def test_the_package_ships_the_renderer_favicon(self):
        path = os.path.join(ROOT, "silica", "ui", "assets", "silica-32.png")
        self.assertTrue(os.path.exists(path), path)
        from silica.ui.web import favicon_data_uri
        uri = favicon_data_uri()
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertGreater(len(uri), 200)


class VSCodeExtensionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = read_json(os.path.join(VSCODE, "package.json"))
        self.contributes = self.manifest["contributes"]

    def test_manifest_is_a_valid_extension(self):
        for key in ("name", "publisher", "version", "engines", "contributes"):
            self.assertIn(key, self.manifest)
        self.assertEqual(self.manifest["license"], "MIT")

    def test_the_sc_extension_is_registered_as_silica(self):
        languages = self.contributes["languages"]
        self.assertEqual(len(languages), 1)
        language = languages[0]
        self.assertEqual(language["id"], "silica")
        self.assertIn(".sc", language["extensions"])

    def test_a_grammar_is_contributed_for_that_language(self):
        grammars = self.contributes["grammars"]
        self.assertEqual(grammars[0]["language"], "silica")
        self.assertEqual(grammars[0]["scopeName"], "source.silica")
        path = os.path.join(VSCODE, grammars[0]["path"])
        self.assertTrue(os.path.exists(path), path)
        grammar = read_json(path)
        self.assertEqual(grammar["scopeName"], "source.silica")
        self.assertIn("sc", grammar["fileTypes"])

    def test_the_file_icon_theme_uses_the_documented_contribution_point(self):
        """`fileIconThemes` is not a VS Code contribution point; `iconThemes` is.

        Getting this wrong is silent: the manifest loads, the icon theme is never
        offered, and .sc files keep the default icon.
        """
        self.assertIn("iconThemes", self.contributes)
        self.assertNotIn("fileIconThemes", self.contributes)

    def test_a_file_icon_theme_maps_sc_to_the_logo(self):
        themes = self.contributes["iconThemes"]
        self.assertEqual(len(themes), 1)
        theme_path = os.path.join(VSCODE, themes[0]["path"])
        self.assertTrue(os.path.exists(theme_path), theme_path)
        theme = read_json(theme_path)
        self.assertIn("sc", theme["fileExtensions"],
                      "the .sc extension must be mapped to an icon")
        icon_id = theme["fileExtensions"]["sc"]
        self.assertIn(icon_id, theme["iconDefinitions"])
        icon_path = os.path.normpath(
            os.path.join(os.path.dirname(theme_path),
                         theme["iconDefinitions"][icon_id]["iconPath"]))
        self.assertTrue(os.path.exists(icon_path), icon_path)

    def test_the_icon_theme_covers_both_light_and_dark_themes(self):
        """A charcoal icon on a dark theme is invisible; both variants must ship."""
        themes = self.contributes["iconThemes"]
        theme_path = os.path.join(VSCODE, themes[0]["path"])
        theme = read_json(theme_path)
        self.assertIn("light", theme,
                      "the theme needs a light override or the icon vanishes on "
                      "light themes")
        self.assertIn("sc", theme["light"]["fileExtensions"])
        base = theme["iconDefinitions"][theme["fileExtensions"]["sc"]]["iconPath"]
        light = theme["iconDefinitions"][
            theme["light"]["fileExtensions"]["sc"]]["iconPath"]
        self.assertNotEqual(base, light, "both themes point at the same icon")

    @needs_pillow
    def test_the_base_icon_is_light_and_the_light_override_is_dark(self):
        themes = self.contributes["iconThemes"]
        theme_path = os.path.join(VSCODE, themes[0]["path"])
        theme = read_json(theme_path)

        def mean_luma(relative):
            path = os.path.normpath(os.path.join(os.path.dirname(theme_path),
                                                 relative))
            with Image.open(path) as image:
                rgba = image.convert("RGBA")
                raw = rgba.tobytes()
                total = count = 0
                for i in range(0, len(raw), 4):
                    if raw[i + 3] > 128:          # only the opaque mark
                        total += (raw[i] + raw[i + 1] + raw[i + 2]) / 3
                        count += 1
                return total / max(1, count)

        base = theme["iconDefinitions"][theme["fileExtensions"]["sc"]]["iconPath"]
        light = theme["iconDefinitions"][
            theme["light"]["fileExtensions"]["sc"]]["iconPath"]
        self.assertGreater(mean_luma(base), 180,
                           "the base icon must be light to show on dark themes")
        self.assertLess(mean_luma(light), 100,
                        "the light-theme icon must be dark to show on light themes")

    def test_every_path_in_the_manifest_resolves(self):
        paths = []
        for language in self.contributes.get("languages", []):
            if "configuration" in language:
                paths.append(language["configuration"])
        for grammar in self.contributes.get("grammars", []):
            paths.append(grammar["path"])
        for theme in self.contributes.get("iconThemes", []):
            paths.append(theme["path"])
        self.assertTrue(paths)
        for relative in paths:
            with self.subTest(path=relative):
                self.assertTrue(os.path.exists(os.path.join(VSCODE, relative)),
                                relative)

    def test_the_marketplace_icon_is_a_128px_png(self):
        icon = self.manifest.get("icon")
        self.assertIsNotNone(icon, "the extension has no marketplace icon")
        path = os.path.join(VSCODE, icon)
        self.assertTrue(os.path.exists(path), path)
        if HAVE_PILLOW:
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (128, 128))

    def test_every_json_file_parses(self):
        for dirpath, _dirs, files in os.walk(VSCODE):
            for name in files:
                if name.endswith(".json"):
                    path = os.path.join(dirpath, name)
                    with self.subTest(path=os.path.relpath(path, VSCODE)):
                        read_json(path)


class GrammarCoverageTests(unittest.TestCase):
    """The grammar must know the language, not a stale memory of it."""

    def setUp(self):
        self.path = os.path.join(VSCODE, "syntaxes", "silica.tmLanguage.json")
        with open(self.path, encoding="utf-8") as handle:
            self.text = handle.read()
        self.grammar = json.loads(self.text)

    def test_every_keyword_is_highlighted(self):
        for keyword in sorted(KEYWORDS):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.text)

    def test_every_builtin_type_is_highlighted(self):
        for type_name in sorted(BUILTIN_TYPES):
            with self.subTest(type=type_name):
                self.assertIn(type_name, self.text)

    def test_comments_and_strings_are_covered(self):
        self.assertIn("comment", self.grammar["repository"])
        self.assertIn("string", self.grammar["repository"])

    def test_every_include_resolves(self):
        for pattern in self.grammar["patterns"]:
            include = pattern.get("include")
            if include and include.startswith("#"):
                with self.subTest(include=include):
                    self.assertIn(include[1:], self.grammar["repository"])

    def test_the_grammar_scope_matches_the_manifest(self):
        manifest = read_json(os.path.join(VSCODE, "package.json"))
        self.assertEqual(manifest["contributes"]["grammars"][0]["scopeName"],
                         self.grammar["scopeName"])


class HelloScTests(unittest.TestCase):
    """The brief asks for a `hello.sc` check; the repo already ships one."""

    def test_example_file_exists_and_is_silica(self):
        path = os.path.join(ROOT, "examples", "hello.sc")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".sc"))

    def test_it_still_runs(self):
        from silica.engine import run_source
        import io
        path = os.path.join(ROOT, "examples", "hello.sc")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        out = io.StringIO()
        run_source(source, path, stdin=io.StringIO(""), stdout=out,
                   stderr=io.StringIO())
        self.assertEqual(out.getvalue(), "Hello from Silica\n")

    def test_the_extension_would_claim_it(self):
        manifest = read_json(os.path.join(VSCODE, "package.json"))
        extensions = manifest["contributes"]["languages"][0]["extensions"]
        self.assertTrue(any("hello.sc".endswith(ext) for ext in extensions))


if __name__ == "__main__":
    unittest.main()
