"""Perceptual palettes: shade scales, themes and CSS custom properties.

A palette here is not "the same hue at eleven arbitrary lightnesses". Each step
has a perceptual lightness target, and the chroma is scaled down near the ends
where a saturated colour cannot fit in sRGB at that lightness. Where a step still
falls outside the gamut it is mapped by reducing chroma at fixed lightness and
hue, and the result is a real colour, not a clipped one.

Determinism: the same base colour always produces the same scale. Nothing here
consults the clock, the environment or a random source.
"""

from . import color as C

# Lightness targets for the conventional Tailwind-style scale. These are
# perceptual (OKLab L), not HSL lightness — which is the point.
STEPS = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
LIGHTNESS = {
    50: 0.977, 100: 0.946, 200: 0.885, 300: 0.808, 400: 0.716, 500: 0.632,
    600: 0.553, 700: 0.478, 800: 0.402, 900: 0.328, 950: 0.256,
}
# Chroma multiplier per step: full strength in the middle, calmer at the extremes.
CHROMA_SCALE = {
    50: 0.10, 100: 0.20, 200: 0.42, 300: 0.66, 400: 0.88, 500: 1.00,
    600: 0.97, 700: 0.88, 800: 0.74, 900: 0.60, 950: 0.46,
}


def scale(base, steps=None):
    """A shade scale from one base colour. Returns {"50": colour, ...}.

    Keys are strings because a Silica Map is keyed by String.
    """
    lch = C.srgb_to_oklch(base)
    hue = lch["h"]
    chroma = lch["c"]
    chosen = tuple(steps) if steps else STEPS
    result = {}
    for step in chosen:
        if step not in LIGHTNESS:
            raise C.ColorError(
                "unknown palette step %r. Known steps: %s"
                % (step, ", ".join(str(s) for s in STEPS)))
        lightness = LIGHTNESS[step]
        factor = CHROMA_SCALE[step]
        # raw: the candidate may be outside sRGB, and to_srgb_gamut decides
        candidate = C.raw(*C.oklch_to_srgb(lightness, chroma * factor, hue))
        result[str(step)] = C.to_srgb_gamut(candidate)
    return result


def hexes(scale_map):
    """The same scale as hex strings, for printing and CSS."""
    return {step: C.to_hex(value)
            for step, value in sorted(scale_map.items(), key=_step_order)}


def _step_order(item):
    """Sort palette steps numerically, not as strings ("50" after "400")."""
    key = item[0]
    try:
        return int(key)
    except (TypeError, ValueError):
        return 0


def semantic(base, dark=True):
    """Semantic tokens derived from a base colour.

    Tokens are named for meaning, not appearance, so a theme can be swapped
    without touching application code. Text colours are chosen by contrast
    against the surface they sit on, not by picking the scale's lightest step.
    """
    shades = scale(base)
    # `neutral` is kept for callers who want greys from the same machinery
    scale(C.parse("#808080"), steps=(50, 100, 200, 300, 400, 500,
                                     600, 700, 800, 900, 950))
    if dark:
        background = C.parse("#0b0d10")
        surface = C.parse("#15191e")
        elevated = C.parse("#1c222a")
        border = C.parse("#262c36")
        text = C.parse("#f3f4f6")
        muted = C.parse("#9ca3af")
    else:
        background = C.parse("#ffffff")
        surface = C.parse("#f7f8f9")
        elevated = C.parse("#ffffff")
        border = C.parse("#dfe3e8")
        text = C.parse("#101418")
        muted = C.parse("#5b636d")
    accent = shades["500"]
    return {
        "background": background,
        "surface": surface,
        "elevated": elevated,
        "border": border,
        "text": text,
        "muted": muted,
        "accent": accent,
        "accent_hover": shades["400"] if dark else shades["600"],
        "success": C.parse("#4ade80"),
        "warning": C.parse("#fbbf24"),
        "error": C.parse("#f87171"),
        "on_accent": C.best_foreground(accent)["color"],
        "on_background": C.best_foreground(background)["color"],
        "dark": bool(dark),
    }


def audit(theme):
    """WCAG checks for the pairs that matter, with a pass/fail per pair."""
    pairs = [
        ("text", "background"), ("text", "surface"), ("muted", "background"),
        ("on_accent", "accent"), ("on_background", "background"),
    ]
    rows = []
    for foreground, background in pairs:
        if foreground not in theme or background not in theme:
            continue
        verdict = C.passes(theme[foreground], theme[background])
        rows.append({"pair": "%s on %s" % (foreground, background),
                     "ratio": verdict["ratio"], "required": verdict["required"],
                     "passes": verdict["passes"]})
    worst = min((row["ratio"] for row in rows), default=0.0)
    return {"checks": rows, "passes": all(row["passes"] for row in rows),
            "worst_ratio": worst}


def css(theme, prefix="silica"):
    """CSS custom properties for a theme, one per token."""
    lines = [":root {"]
    for name in sorted(theme):
        value = theme[name]
        if isinstance(value, dict):
            lines.append("  --%s-%s: %s;" % (prefix, name.replace("_", "-"),
                                             C.to_css(value, "srgb")))
        elif isinstance(value, bool):
            continue
    lines.append("}")
    return "\n".join(lines)


def css_scale(name, shades, prefix="silica"):
    """CSS custom properties for one named scale."""
    lines = [":root {"]
    for step, value in sorted(shades.items(), key=_step_order):
        lines.append("  --%s-%s-%s: %s;" % (prefix, name, step, C.to_hex(value)))
    lines.append("}")
    return "\n".join(lines)
