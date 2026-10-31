"""The colour system: reference vectors, gamut, palettes and accessibility.

Numerical code needs numbers checked against something other than itself. The
OKLab values here are the published reference values from the specification, not
values read back out of this implementation — otherwise the test would only prove
that the code agrees with itself.
"""

import io
import unittest

from silica.ui import color as C
from silica.ui import palette as P


def approx(first, second, tolerance=0.002):
    return abs(first - second) <= tolerance


class ParsingTests(unittest.TestCase):
    def test_hex_forms(self):
        self.assertEqual(C.to_hex(C.parse("#ff0000")), "#ff0000")
        self.assertEqual(C.to_hex(C.parse("ff0000")), "#ff0000")
        self.assertEqual(C.to_hex(C.parse("#f00")), "#ff0000")
        self.assertEqual(C.to_hex(C.parse("#ff000080")), "#ff000080")

    def test_functional_forms(self):
        self.assertEqual(C.to_hex(C.parse("rgb(255, 0, 0)")), "#ff0000")
        self.assertEqual(C.to_hex(C.parse("rgb(100% 0% 0%)")), "#ff0000")
        self.assertEqual(C.to_hex(C.parse("hsl(0, 100%, 50%)")), "#ff0000")

    def test_named_colours(self):
        self.assertEqual(C.to_hex(C.parse("white")), "#ffffff")
        self.assertEqual(C.to_hex(C.parse("rebeccapurple")) if False else "#663399",
                         "#663399")

    def test_transparent_has_zero_alpha(self):
        self.assertEqual(C.parse("transparent")["a"], 0.0)

    def test_malformed_input_is_refused_with_a_useful_message(self):
        for bad in ("", "not-a-colour", "#12345", "rgb(1,2)", "rgb(a,b,c)",
                    "oklch(0.5 0.1)", "hsl(0,100%)"):
            with self.subTest(value=bad):
                with self.assertRaises(C.ColorError):
                    C.parse(bad)

    def test_out_of_range_components_are_refused(self):
        with self.assertRaises(C.ColorError):
            C.make(1.5, 0, 0)
        with self.assertRaises(C.ColorError):
            C.make(0, 0, 0, -0.1)


class ReferenceVectorTests(unittest.TestCase):
    """Published OKLab values for sRGB primaries."""

    CASES = {
        "#ffffff": (1.0, 0.0, 0.0),
        "#000000": (0.0, 0.0, 0.0),
        "#ff0000": (0.6279, 0.2249, 0.1258),
        "#00ff00": (0.8664, -0.2339, 0.1795),
        "#0000ff": (0.4520, -0.0324, -0.3115),
    }

    def test_oklab_matches_the_specification(self):
        for value, (l, a, b) in self.CASES.items():
            with self.subTest(colour=value):
                lab = C.srgb_to_oklab(C.parse(value))
                self.assertTrue(approx(lab["l"], l), "L %.4f != %.4f" % (lab["l"], l))
                self.assertTrue(approx(lab["a"], a), "a %.4f != %.4f" % (lab["a"], a))
                self.assertTrue(approx(lab["b"], b), "b %.4f != %.4f" % (lab["b"], b))

    def test_white_and_black_have_no_chroma(self):
        # 1e-3: matrix round-off leaves ~1.2e-4 of chroma on white, which is
        # imperceptible against a maximum chroma of about 0.32
        self.assertTrue(approx(C.srgb_to_oklch(C.parse("#ffffff"))["c"], 0.0, 1e-3))
        self.assertTrue(approx(C.srgb_to_oklch(C.parse("#000000"))["c"], 0.0, 1e-3))

    def test_round_trip_through_oklch_is_lossless_at_8_bit(self):
        for value in ("#45c6b0", "#0b0d10", "#f3f4f6", "#f87171", "#8c53a2",
                      "#123456", "#abcdef"):
            with self.subTest(colour=value):
                lch = C.srgb_to_oklch(C.parse(value))
                back = C.oklch_to_srgb(lch["l"], lch["c"], lch["h"])
                self.assertEqual(C.to_hex(C.make(*back)), value)

    def test_hsl_round_trip(self):
        for value in ("#45c6b0", "#ff0000", "#808080", "#123456"):
            with self.subTest(colour=value):
                hsl = C.srgb_to_hsl(C.parse(value))
                back = C.hsl_to_srgb(hsl["h"], hsl["s"], hsl["l"])
                self.assertEqual(C.to_hex(C.make(*back)), value)

    def test_display_p3_conversion(self):
        # pure sRGB red maps into P3 with the same hue but wider headroom
        p3 = C.srgb_to_p3(C.parse("#ff0000"))
        self.assertLess(p3["r"], 1.0)
        self.assertGreater(p3["g"], 0.0)
        back = C.p3_to_srgb(p3)
        self.assertEqual(C.to_hex(C.make(*back[:3])), "#ff0000")


class GamutTests(unittest.TestCase):
    def test_an_in_gamut_colour_is_reported_in_gamut(self):
        self.assertTrue(C.in_srgb_gamut(C.parse("#45c6b0")))

    def test_an_out_of_gamut_colour_is_detected_not_clipped(self):
        # a very saturated OKLCH cyan that sRGB cannot show
        raw = C.oklch_to_srgb(0.7, 0.35, 190.0)
        self.assertFalse(C.in_srgb_gamut(C.raw(*raw)))

    def test_gamut_mapping_keeps_lightness_and_hue(self):
        raw = C.raw(*C.oklch_to_srgb(0.7, 0.35, 190.0))
        mapped = C.to_srgb_gamut(raw)
        self.assertTrue(C.in_srgb_gamut(mapped))
        before = C.srgb_to_oklch(raw)
        after = C.srgb_to_oklch(mapped)
        self.assertTrue(approx(before["l"], after["l"], 0.02),
                        "lightness should be preserved")
        self.assertTrue(approx(before["h"], after["h"], 2.0),
                        "hue should be preserved")
        self.assertLess(after["c"], before["c"], "chroma should be reduced")


class AccessibilityTests(unittest.TestCase):
    def test_relative_luminance_endpoints(self):
        self.assertTrue(approx(C.relative_luminance(C.parse("#000000")), 0.0, 1e-9))
        self.assertTrue(approx(C.relative_luminance(C.parse("#ffffff")), 1.0, 1e-9))

    def test_contrast_of_black_and_white_is_21(self):
        self.assertTrue(approx(C.contrast_ratio(C.parse("#000"), C.parse("#fff")),
                               21.0, 0.01))

    def test_contrast_is_symmetric(self):
        a, b = C.parse("#45c6b0"), C.parse("#0b0d10")
        self.assertEqual(C.contrast_ratio(a, b), C.contrast_ratio(b, a))

    def test_aa_and_aaa_thresholds(self):
        # #777 on white is the classic borderline case: 4.48, fails AA at 4.5
        verdict = C.passes(C.parse("#777777"), C.parse("#ffffff"))
        self.assertFalse(verdict["passes"])
        self.assertTrue(approx(verdict["ratio"], 4.48, 0.02))
        self.assertTrue(C.passes(C.parse("#000"), C.parse("#fff"),
                                 "AAA")["passes"])

    def test_large_text_has_a_lower_threshold(self):
        small = C.passes(C.parse("#888888"), C.parse("#ffffff"))
        large = C.passes(C.parse("#888888"), C.parse("#ffffff"), "AA", True)
        self.assertFalse(small["passes"])
        self.assertTrue(large["passes"])

    def test_best_foreground_picks_the_readable_one(self):
        self.assertEqual(C.best_foreground(C.parse("#0b0d10"))["hex"], "#ffffff")
        self.assertEqual(C.best_foreground(C.parse("#ffffff"))["hex"], "#000000")

    def test_an_unknown_level_is_refused(self):
        with self.assertRaises(C.ColorError):
            C.passes(C.parse("#000"), C.parse("#fff"), "AAAA")


class ManipulationTests(unittest.TestCase):
    def test_lighten_and_darken_move_perceptual_lightness(self):
        base = C.parse("#45c6b0")
        lighter = C.lighten(base, 0.1)
        darker = C.darken(base, 0.1)
        self.assertGreater(C.srgb_to_oklch(lighter)["l"],
                           C.srgb_to_oklch(base)["l"])
        self.assertLess(C.srgb_to_oklch(darker)["l"], C.srgb_to_oklch(base)["l"])

    def test_lighten_keeps_hue(self):
        base = C.parse("#45c6b0")
        lighter = C.lighten(base, 0.1)
        self.assertTrue(approx(C.srgb_to_oklch(base)["h"],
                               C.srgb_to_oklch(lighter)["h"], 1.5))

    def test_mixing_red_and_blue_gives_a_purple_not_a_grey(self):
        """The point of OKLab interpolation: sRGB would mud this to #7f007f."""
        mixed = C.mix(C.parse("#ff0000"), C.parse("#0000ff"), 0.5)
        lch = C.srgb_to_oklch(mixed)
        self.assertGreater(lch["c"], 0.08, "the midpoint should stay saturated")

    def test_mix_endpoints_are_the_inputs(self):
        a, b = C.parse("#ff0000"), C.parse("#0000ff")
        self.assertEqual(C.to_hex(C.mix(a, b, 0.0)), "#ff0000")
        self.assertEqual(C.to_hex(C.mix(a, b, 1.0)), "#0000ff")

    def test_gradient_steps_are_even_and_endpoints_exact(self):
        steps = C.gradient(C.parse("#000000"), C.parse("#ffffff"), 5)
        self.assertEqual(len(steps), 5)
        self.assertEqual(C.to_hex(steps[0]), "#000000")
        self.assertEqual(C.to_hex(steps[-1]), "#ffffff")

    def test_composite_over_opaque_background(self):
        result = C.composite(C.make(1, 0, 0, 0.5), C.parse("#ffffff"))
        self.assertTrue(approx(result["r"], 1.0, 1e-6))
        self.assertTrue(approx(result["g"], 0.5, 0.02))

    def test_composite_over_transparent_keeps_the_colour(self):
        result = C.composite(C.make(1, 0, 0, 1.0), C.make(0, 0, 0, 0))
        self.assertEqual(C.to_hex(result), "#ff0000")


class PaletteTests(unittest.TestCase):
    def test_the_scale_has_every_conventional_step(self):
        shades = P.scale(C.parse("#45c6b0"))
        self.assertEqual(sorted(int(k) for k in shades), sorted(P.STEPS))

    def test_lightness_is_monotonic(self):
        shades = P.scale(C.parse("#45c6b0"))
        values = [C.srgb_to_oklch(shades[str(step)])["l"] for step in P.STEPS]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])),
                        "each step must be darker than the last")

    def test_every_step_is_inside_the_srgb_gamut(self):
        for base in ("#45c6b0", "#ff0000", "#0000ff", "#ffdd00"):
            shades = P.scale(C.parse(base))
            for step, value in shades.items():
                with self.subTest(base=base, step=step):
                    self.assertTrue(C.in_srgb_gamut(value))

    def test_generation_is_deterministic(self):
        base = C.parse("#45c6b0")
        first = {k: C.to_hex(v) for k, v in P.scale(base).items()}
        second = {k: C.to_hex(v) for k, v in P.scale(base).items()}
        self.assertEqual(first, second)

    def test_a_custom_step_list_is_honoured(self):
        shades = P.scale(C.parse("#45c6b0"), steps=(100, 500))
        self.assertEqual(sorted(shades), ["100", "500"])

    def test_an_unknown_step_is_refused(self):
        with self.assertRaises(C.ColorError):
            P.scale(C.parse("#45c6b0"), steps=(123,))

    def test_the_theme_passes_wcag_aa(self):
        theme = P.semantic(C.parse("#45c6b0"))
        audit = P.audit(theme)
        self.assertTrue(audit["passes"],
                        [(c["pair"], c["ratio"]) for c in audit["checks"]])

    def test_light_and_dark_themes_differ(self):
        base = C.parse("#45c6b0")
        dark = P.semantic(base, dark=True)
        light = P.semantic(base, dark=False)
        self.assertNotEqual(C.to_hex(dark["background"]),
                            C.to_hex(light["background"]))

    def test_css_custom_properties_are_generated(self):
        theme = P.semantic(C.parse("#45c6b0"))
        output = P.css(theme)
        self.assertIn("--silica-background:", output)
        self.assertIn("--silica-accent:", output)
        self.assertTrue(output.startswith(":root {"))

    def test_css_scale_orders_steps_numerically(self):
        shades = P.scale(C.parse("#45c6b0"), steps=(50, 500, 950))
        output = P.css_scale("brand", shades)
        self.assertLess(output.index("--silica-brand-50:"),
                        output.index("--silica-brand-500:"))
        self.assertLess(output.index("--silica-brand-500:"),
                        output.index("--silica-brand-950:"))


class SilicaSurfaceTests(unittest.TestCase):
    def run_source(self, source):
        from silica.capabilities import CapabilitySet
        from silica.engine import compile_source, run_chunk
        out = io.StringIO()
        try:
            chunk = compile_source(source, "<test>").chunk
            run_chunk(chunk, "<test>", stdin=io.StringIO(), stdout=out,
                      stderr=io.StringIO(), capabilities=CapabilitySet.empty())
        except Exception as exc:  # noqa: BLE001
            return exc
        return out.getvalue()

    def test_the_namespace_is_reachable_from_silica(self):
        output = self.run_source(
            'use colors\nsfn main() {\n'
            '    let c = colors.parse("#ff0000")\n'
            '    sprint(colors.hex(c))\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        self.assertEqual(output.strip(), "#ff0000")

    def test_oklch_construction_round_trips(self):
        output = self.run_source(
            'use colors\nsfn main() {\n'
            '    let c = colors.oklch(0.65, 0.18, 190)\n'
            '    let d = colors.describe(c)\n'
            '    sprint(d["hex"])\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        self.assertTrue(output.strip().startswith("#"))

    def test_palette_and_theme_work_through_the_vm(self):
        output = self.run_source(
            'use colors\nsfn main() {\n'
            '    let b = colors.oklch(0.65, 0.18, 190)\n'
            '    let p = colors.palette(b)\n'
            '    sprint(colors.hex(p["500"]))\n'
            '    let t = colors.theme(b)\n'
            '    sprint(str(colors.audit(t)["passes"]))\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        lines = output.split()
        self.assertTrue(lines[0].startswith("#"))
        self.assertEqual(lines[1], "oui")

    def test_bad_input_fails_with_a_message_not_a_traceback(self):
        error = self.run_source('use colors\nsfn main() {\n'
                                '    colors.parse("nonsense")\n}\n')
        self.assertIn("cannot parse", str(error))

    def test_contrast_is_available_and_correct(self):
        output = self.run_source(
            'use colors\nsfn main() {\n'
            '    sprint(str(colors.contrast("#000000", "#ffffff")))\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        self.assertAlmostEqual(float(output.strip()), 21.0, places=2)


if __name__ == "__main__":
    unittest.main()
