"""The `colors` namespace: perceptual colour, palettes and accessibility.

Colours cross the boundary as Maps, because Silica has no structs yet:
`{r, g, b, a}` with components in 0..1. Everything else — OKLab, OKLCH, HSL,
gamut, contrast — is computed from those four numbers, so no precision is lost
by round-tripping through a hex string.
"""

from ..errors import SilicaRuntimeError
from ..natives import type_name
from ..ui import color as _color
from ..ui import palette as _palettes  # not `_palette`: that name is a native


def _fail(message, hint=None):
    raise SilicaRuntimeError(message, hint=hint)


def _colour(name, value):
    """Accept a Map or a String and return a Map, with a clear error otherwise."""
    try:
        return _color.parse(value)
    except _color.ColorError as exc:
        _fail("%s: %s" % (name, exc))


def _number(name, value, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("%s expects a number, got %s" % (name, type_name(value)))
    number = float(value)
    if low is not None and number < low:
        _fail("%s must be at least %s, got %s" % (name, low, number))
    if high is not None and number > high:
        _fail("%s must be at most %s, got %s" % (name, high, number))
    return number


def _string(name, value):
    if not isinstance(value, str):
        _fail("%s expects a String, got %s" % (name, type_name(value)))
    return value


def _map(name, value):
    if not isinstance(value, dict):
        _fail("%s expects a Map, got %s" % (name, type_name(value)))
    return value


# --- construction -----------------------------------------------------------

def _parse(ctx, args):
    return _colour("colors.parse", args[0])


def _rgb(ctx, args):
    alpha = args[3] if len(args) > 3 else 1.0
    try:
        return _color.make(_number("colors.rgb", args[0], 0, 1),
                           _number("colors.rgb", args[1], 0, 1),
                           _number("colors.rgb", args[2], 0, 1),
                           _number("colors.rgb", alpha, 0, 1))
    except _color.ColorError as exc:
        _fail("colors.rgb: %s" % exc)


def _oklch(ctx, args):
    lightness = _number("colors.oklch", args[0], 0, 1)
    chroma = _number("colors.oklch", args[1], 0)
    hue = _number("colors.oklch", args[2])
    alpha = _number("colors.oklch", args[3], 0, 1) if len(args) > 3 else 1.0
    # gamut-mapped rather than clipped, so a too-saturated request keeps its
    # lightness and hue instead of silently becoming a different colour
    return _color.to_srgb_gamut(
        _color.raw(*_color.oklch_to_srgb(lightness, chroma, hue), alpha))


def _oklab(ctx, args):
    lightness = _number("colors.oklab", args[0], 0, 1)
    a = _number("colors.oklab", args[1])
    b = _number("colors.oklab", args[2])
    alpha = _number("colors.oklab", args[3], 0, 1) if len(args) > 3 else 1.0
    return _color.to_srgb_gamut(
        _color.raw(*_color.oklab_to_srgb(lightness, a, b), alpha))


def _hsl(ctx, args):
    hue = _number("colors.hsl", args[0])
    saturation = _number("colors.hsl", args[1], 0, 1)
    lightness = _number("colors.hsl", args[2], 0, 1)
    return _color.make(*_color.hsl_to_srgb(hue, saturation, lightness))


# --- conversion -------------------------------------------------------------

def _describe(ctx, args):
    return _color.describe(_colour("colors.describe", args[0]))


def _hex(ctx, args):
    return _color.to_hex(_colour("colors.hex", args[0]))


def _css(ctx, args):
    space = _string("colors.css", args[1]) if len(args) > 1 else "oklch"
    if space not in ("oklch", "oklab", "srgb", "hex"):
        _fail("colors.css: unknown space %r" % space,
              hint="use oklch, oklab, srgb or hex")
    return _color.to_css(_colour("colors.css", args[0]), space)


def _to_p3(ctx, args):
    return _color.srgb_to_p3(_colour("colors.to_p3", args[0]))


def _from_p3(ctx, args):
    raw = _colour("colors.from_p3", args[0])
    r, g, b, a = _color.p3_to_srgb(raw)
    return {"r": r, "g": g, "b": b, "a": a}


# --- gamut ------------------------------------------------------------------

def _in_gamut(ctx, args):
    return _color.in_srgb_gamut(_colour("colors.in_gamut", args[0]))


def _to_gamut(ctx, args):
    return _color.to_srgb_gamut(_colour("colors.to_gamut", args[0]))


# --- manipulation -----------------------------------------------------------

def _lighten(ctx, args):
    return _color.lighten(_colour("colors.lighten", args[0]),
                          _number("colors.lighten", args[1], 0, 1))


def _darken(ctx, args):
    return _color.darken(_colour("colors.darken", args[0]),
                         _number("colors.darken", args[1], 0, 1))


def _with_lightness(ctx, args):
    return _color.with_lightness(_colour("colors.with_lightness", args[0]),
                                 _number("colors.with_lightness", args[1], 0, 1))


def _with_chroma(ctx, args):
    return _color.with_chroma(_colour("colors.with_chroma", args[0]),
                              _number("colors.with_chroma", args[1], 0))


def _with_hue(ctx, args):
    return _color.with_hue(_colour("colors.with_hue", args[0]),
                           _number("colors.with_hue", args[1]))


def _mix(ctx, args):
    weight = _number("colors.mix", args[2], 0, 1) if len(args) > 2 else 0.5
    return _color.mix(_colour("colors.mix", args[0]),
                      _colour("colors.mix", args[1]), weight)


def _gradient(ctx, args):
    steps = int(_number("colors.gradient", args[2], 2, 256)) if len(args) > 2 else 8
    return _color.gradient(_colour("colors.gradient", args[0]),
                           _colour("colors.gradient", args[1]), steps)


def _composite(ctx, args):
    return _color.composite(_colour("colors.composite", args[0]),
                            _colour("colors.composite", args[1]))


# --- accessibility ----------------------------------------------------------

def _contrast(ctx, args):
    return round(_color.contrast_ratio(_colour("colors.contrast", args[0]),
                                       _colour("colors.contrast", args[1])), 4)


def _passes(ctx, args):
    level = _string("colors.passes", args[2]) if len(args) > 2 else "AA"
    large = bool(args[3]) if len(args) > 3 else False
    try:
        return _color.passes(_colour("colors.passes", args[0]),
                             _colour("colors.passes", args[1]), level, large)
    except _color.ColorError as exc:
        _fail("colors.passes: %s" % exc)


def _best_foreground(ctx, args):
    result = _color.best_foreground(_colour("colors.best_foreground", args[0]))
    return {"color": result["color"], "hex": result["hex"],
            "ratio": result["ratio"]}


def _luminance(ctx, args):
    return round(_color.relative_luminance(_colour("colors.luminance", args[0])), 6)


# --- palettes ---------------------------------------------------------------

def _palette(ctx, args):
    steps = None
    if len(args) > 1:
        raw = args[1]
        if not isinstance(raw, list):
            _fail("colors.palette: steps must be a List of numbers")
        steps = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _fail("colors.palette: every step must be a number, got %s"
                      % type_name(value))
            steps.append(int(value))
    try:
        return _palettes.scale(_colour("colors.palette", args[0]), steps)
    except _color.ColorError as exc:
        _fail("colors.palette: %s" % exc)


def _theme(ctx, args):
    dark = bool(args[1]) if len(args) > 1 else True
    return _palettes.semantic(_colour("colors.theme", args[0]), dark=dark)


def _audit(ctx, args):
    theme = _map("colors.audit", args[0])
    try:
        return _palettes.audit(theme)
    except _color.ColorError as exc:
        _fail("colors.audit: %s" % exc)


def _css_theme(ctx, args):
    theme = _map("colors.css_theme", args[0])
    return _palettes.css(theme)


def _css_scale(ctx, args):
    name = _string("colors.css_scale", args[0])
    shades = _map("colors.css_scale", args[1])
    try:
        return _palettes.css_scale(name, shades)
    except _color.ColorError as exc:
        _fail("colors.css_scale: %s" % exc)


FUNCTIONS = (
    ("parse", ["String"], "Map", _parse, 1, 1, None, None),
    ("rgb", ["Float", "Float", "Float", "Float"], "Map", _rgb, 3, 4, None, None),
    ("oklch", ["Float", "Float", "Float", "Float"], "Map", _oklch, 3, 4, None, None),
    ("oklab", ["Float", "Float", "Float", "Float"], "Map", _oklab, 3, 4, None, None),
    ("hsl", ["Float", "Float", "Float"], "Map", _hsl, 3, 3, None, None),
    ("describe", ["Any"], "Map", _describe, 1, 1, None, None),
    ("hex", ["Any"], "String", _hex, 1, 1, None, None),
    ("css", ["Any", "String"], "String", _css, 1, 2, None, None),
    ("to_p3", ["Any"], "Map", _to_p3, 1, 1, None, None),
    ("from_p3", ["Any"], "Map", _from_p3, 1, 1, None, None),
    ("in_gamut", ["Any"], "Bool", _in_gamut, 1, 1, None, None),
    ("to_gamut", ["Any"], "Map", _to_gamut, 1, 1, None, None),
    ("lighten", ["Any", "Float"], "Map", _lighten, 2, 2, None, None),
    ("darken", ["Any", "Float"], "Map", _darken, 2, 2, None, None),
    ("with_lightness", ["Any", "Float"], "Map", _with_lightness, 2, 2, None, None),
    ("with_chroma", ["Any", "Float"], "Map", _with_chroma, 2, 2, None, None),
    ("with_hue", ["Any", "Float"], "Map", _with_hue, 2, 2, None, None),
    ("mix", ["Any", "Any", "Float"], "Map", _mix, 2, 3, None, None),
    ("gradient", ["Any", "Any", "Int"], "List", _gradient, 2, 3, None, None),
    ("composite", ["Any", "Any"], "Map", _composite, 2, 2, None, None),
    ("contrast", ["Any", "Any"], "Float", _contrast, 2, 2, None, None),
    ("passes", ["Any", "Any", "String", "Bool"], "Map", _passes, 2, 4, None, None),
    ("best_foreground", ["Any"], "Map", _best_foreground, 1, 1, None, None),
    ("luminance", ["Any"], "Float", _luminance, 1, 1, None, None),
    ("palette", ["Any", "List"], "Map", _palette, 1, 2, None, None),
    ("theme", ["Any", "Bool"], "Map", _theme, 1, 2, None, None),
    ("audit", ["Map"], "Map", _audit, 1, 1, None, None),
    ("css_theme", ["Map"], "String", _css_theme, 1, 1, None, None),
    ("css_scale", ["String", "Map"], "String", _css_scale, 2, 2, None, None),
)
