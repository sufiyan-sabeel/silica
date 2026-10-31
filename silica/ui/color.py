"""Colour: perceptual spaces, gamut mapping, palettes and accessibility.

Why OKLab
---------
sRGB and HSL are not perceptually uniform: a 10% step in HSL lightness is a large
visible jump in dark colours and an invisible one in light ones. OKLab is designed
to be uniform, so equal steps look equal. Every manipulation here happens in
OKLab/OKLCH and converts back at the edges.

What is exact and what is not
-----------------------------
* sRGB <-> linear sRGB is exact (the published transfer function).
* linear sRGB <-> XYZ <-> OKLab uses the published matrices.
* Display P3 shares the sRGB transfer function with a different matrix, so
  sRGB -> P3 is exact; P3 -> sRGB may land outside the sRGB gamut, and that is
  reported rather than clipped.
* Gamut mapping reduces chroma at constant lightness and hue until the colour
  fits. It is a documented choice, not the only possible one.

No HDR. Display P3 conversion is not HDR: there are no PQ/HLG transfer functions
here, no luminance metadata, and no backend that could use them. Claiming
otherwise would be the sort of thing this project keeps trying not to do.
"""

import math
import re

# --- sRGB transfer function -------------------------------------------------

def _srgb_to_linear(value):
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value):
    if value <= 0.0031308:
        return value * 12.92
    return 1.055 * (value ** (1 / 2.4)) - 0.055


# --- matrices (published values) -------------------------------------------

# linear sRGB -> XYZ (D65)
SRGB_TO_XYZ = (
    (0.41239079926595934, 0.357584339383878, 0.1804807884018343),
    (0.21263900587151027, 0.715168678767756, 0.07219231536073371),
    (0.01933081871559182, 0.11919477979462598, 0.9505321522496607),
)
XYZ_TO_SRGB = (
    (3.2409699419045226, -1.537383177570094, -0.4986107602930034),
    (-0.9692436362808796, 1.8759675015077202, 0.04155505740717559),
    (0.05563007969699366, -0.20397695888897652, 1.0569715142428786),
)
# linear Display P3 -> XYZ (D65)
P3_TO_XYZ = (
    (0.4865709486482162, 0.26566769316909306, 0.1982172852343625),
    (0.2289745640697488, 0.6917385218365064, 0.079286914093745),
    (0.0, 0.04511338185890264, 1.043944368900976),
)
XYZ_TO_P3 = (
    (2.493496911941425, -0.9313836179191239, -0.40271078445071684),
    (-0.8294889695615747, 1.7626640603183463, 0.023624685841943577),
    (0.03584583024378447, -0.07617238926804182, 0.9568845240076872),
)

# XYZ -> LMS, LMS -> OKLab (Björn Ottosson)
XYZ_TO_LMS = (
    (0.8189330101, 0.3618667424, -0.1288597137),
    (0.0329845436, 0.9293118715, 0.0361456387),
    (0.0482003018, 0.2643662691, 0.6338517070),
)
LMS_TO_XYZ = (
    (1.2268798733741557, -0.5578149965554813, 0.28139105017721583),
    (-0.04057576262431372, 1.1122868293970594, -0.07171106666151701),
    (-0.07637294974672142, -0.4214933239627914, 1.5869240244272418),
)
LMS_TO_OKLAB = (
    (0.2104542553, 0.7936177850, -0.0040720468),
    (1.9779984951, -2.4285922050, 0.4505937099),
    (0.0259040371, 0.7827717662, -0.8086757660),
)
OKLAB_TO_LMS = (
    (0.9999999984505198, 0.39633779217376786, 0.2158037580607588),
    (1.0000000088817609, -0.10556134232365635, -0.0638541747717059),
    (1.0000000546724108, -0.08948418209496575, -1.2914855378640917),
)

D50 = (0.96422, 1.0, 0.82521)
D65 = (0.95047, 1.0, 1.08883)


def _mul(matrix, vector):
    return tuple(sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3))


def _clamp01(value):
    return 0.0 if value < 0 else 1.0 if value > 1 else value


# --- the Color value --------------------------------------------------------
#
# Silica has no structs, so a colour crosses the boundary as a Map with a fixed
# shape: {"r","g","b" in 0..1, "a" in 0..1, plus derived read-only fields}.
# Everything internal is computed on demand from r/g/b/a, so precision is kept.

class ColorError(ValueError):
    pass


def _channel(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ColorError("%s must be a number, got %r" % (name, value))
    if number < 0.0 or number > 1.0:
        raise ColorError("%s must be between 0 and 1, got %r" % (name, value))
    return number


def make(r, g, b, a=1.0):
    """Build a colour from sRGB components in 0..1."""
    return {"r": _channel(r, "r"), "g": _channel(g, "g"),
            "b": _channel(b, "b"), "a": _channel(a, "a")}


def _parts(color):
    if not isinstance(color, dict):
        raise ColorError("expected a colour, got %s" % type(color).__name__)
    try:
        return (float(color["r"]), float(color["g"]), float(color["b"]),
                float(color.get("a", 1.0)))
    except KeyError as exc:
        raise ColorError("colour is missing %s" % exc)


# --- parsing ----------------------------------------------------------------

NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "lime": (0, 255, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "aqua": (0, 255, 255),
    "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "silver": (192, 192, 192),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "navy": (0, 0, 128), "purple": (128, 0, 128),
    "teal": (0, 128, 128), "orange": (255, 165, 0), "transparent": (0, 0, 0),
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{3,8})$")
_FUNC = re.compile(r"^(rgba?|hsla?|oklch|oklab)\(([^)]*)\)$", re.I)


def parse(text):
    """Parse a colour string. Raises ColorError on anything malformed."""
    if isinstance(text, dict):
        return make(text.get("r", 0), text.get("g", 0), text.get("b", 0),
                    text.get("a", 1.0))
    if not isinstance(text, str):
        raise ColorError("expected a String, got %s" % type(text).__name__)
    raw = text.strip()
    if not raw:
        raise ColorError("empty colour string")
    lowered = raw.lower()

    if lowered in NAMED:
        r, g, b = NAMED[lowered]
        return make(r / 255.0, g / 255.0, b / 255.0,
                    0.0 if lowered == "transparent" else 1.0)

    match = _HEX.match(raw)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            parts = [int(d * 2, 16) / 255.0 for d in digits]
        elif len(digits) in (6, 8):
            parts = [int(digits[i:i + 2], 16) / 255.0
                     for i in range(0, len(digits), 2)]
        else:
            raise ColorError("hex colours need 3, 4, 6 or 8 digits: %r" % raw)
        if len(parts) == 3:
            parts.append(1.0)
        return make(*parts)

    match = _FUNC.match(raw)
    if not match:
        raise ColorError(
            "cannot parse colour %r. Use #rrggbb, rgb(), hsl(), oklch(), "
            "oklab() or a CSS colour name" % raw)
    name = match.group(1).lower()
    body = match.group(2).replace("/", " ").replace(",", " ")
    fields = [f for f in body.split() if f]
    try:
        if name in ("rgb", "rgba"):
            if len(fields) not in (3, 4):
                raise ColorError("rgb() takes 3 or 4 values")
            channels = []
            for field in fields[:3]:
                if field.endswith("%"):
                    channels.append(float(field[:-1]) / 100.0)
                else:
                    channels.append(float(field) / 255.0)
            alpha = _alpha(fields[3]) if len(fields) == 4 else 1.0
            return make(*channels, alpha)
        if name in ("hsl", "hsla"):
            if len(fields) not in (3, 4):
                raise ColorError("hsl() takes 3 or 4 values")
            hue = _hue(fields[0])
            sat = float(fields[1].rstrip("%")) / 100.0
            light = float(fields[2].rstrip("%")) / 100.0
            alpha = _alpha(fields[3]) if len(fields) == 4 else 1.0
            r, g, b = hsl_to_srgb(hue, sat, light)
            return make(r, g, b, alpha)
        if name == "oklch":
            if len(fields) not in (3, 4):
                raise ColorError("oklch() takes 3 or 4 values")
            lightness = _ok_lightness(fields[0])
            chroma = float(fields[1])
            hue = _hue(fields[2])
            alpha = _alpha(fields[3]) if len(fields) == 4 else 1.0
            r, g, b = oklch_to_srgb(lightness, chroma, hue)
            return make(r, g, b, alpha)
        if name == "oklab":
            if len(fields) not in (3, 4):
                raise ColorError("oklab() takes 3 or 4 values")
            lightness = _ok_lightness(fields[0])
            a = float(fields[1])
            b_value = float(fields[2])
            alpha = _alpha(fields[3]) if len(fields) == 4 else 1.0
            r, g, b = oklab_to_srgb(lightness, a, b_value)
            return make(r, g, b, alpha)
    except ColorError:
        raise
    except (TypeError, ValueError) as exc:
        raise ColorError("cannot parse %r: %s" % (raw, exc))
    raise ColorError("cannot parse colour %r" % raw)


def _alpha(field):
    if field.endswith("%"):
        return _clamp01(float(field[:-1]) / 100.0)
    return _clamp01(float(field))


def _hue(field):
    text = field.rstrip("deg")
    return float(text) % 360.0


def _ok_lightness(field):
    if field.endswith("%"):
        return _clamp01(float(field[:-1]) / 100.0)
    return _clamp01(float(field))


# --- conversions ------------------------------------------------------------

def srgb_to_linear(color):
    r, g, b, a = _parts(color)
    return {"r": _srgb_to_linear(r), "g": _srgb_to_linear(g),
            "b": _srgb_to_linear(b), "a": a}


def linear_to_srgb(color):
    r, g, b, a = _parts(color)
    return make(_clamp01(_linear_to_srgb(r)), _clamp01(_linear_to_srgb(g)),
                _clamp01(_linear_to_srgb(b)), a)


def srgb_to_oklab(color):
    r, g, b, _a = _parts(color)
    # `_parts` does not validate range, so out-of-gamut values are measurable too
    linear = (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b))
    xyz = _mul(SRGB_TO_XYZ, linear)
    lms = _mul(XYZ_TO_LMS, xyz)
    lms = tuple(math.copysign(abs(v) ** (1 / 3), v) for v in lms)
    lab = _mul(LMS_TO_OKLAB, lms)
    return {"l": lab[0], "a": lab[1], "b": lab[2]}


def raw(r, g, b, a=1.0):
    """A colour that may sit outside the sRGB gamut.

    `make()` rejects components outside 0..1 because a caller asking for a colour
    should get an error, not a surprise. Conversions are different: an OKLCH
    value can legitimately describe a colour sRGB cannot show, and clamping it
    here would destroy the information that makes gamut mapping possible.
    """
    return {"r": float(r), "g": float(g), "b": float(b), "a": float(a)}


def oklab_to_srgb(lightness, a, b, alpha=1.0):
    """OKLab to sRGB components, **unclamped**: the result may be out of gamut.

    Deliberately does not clamp. Silent clipping is how a conversion quietly
    loses colour; callers either check `in_srgb_gamut` or map with
    `to_srgb_gamut`.
    """
    lms = _mul(OKLAB_TO_LMS, (lightness, a, b))
    lms = tuple(v ** 3 for v in lms)
    xyz = _mul(LMS_TO_XYZ, lms)
    linear = _mul(XYZ_TO_SRGB, xyz)
    return (_linear_to_srgb(linear[0]),
            _linear_to_srgb(linear[1]),
            _linear_to_srgb(linear[2]))


def srgb_to_oklch(color):
    lab = srgb_to_oklab(color)
    chroma = math.hypot(lab["a"], lab["b"])
    hue = math.degrees(math.atan2(lab["b"], lab["a"])) % 360.0
    # below a thousandth of a unit the hue is matrix noise, not a colour
    if chroma < 1e-3:
        hue = 0.0
    return {"l": lab["l"], "c": chroma, "h": hue}


def oklch_to_srgb(lightness, chroma, hue):
    radians = math.radians(hue)
    return oklab_to_srgb(lightness, chroma * math.cos(radians),
                         chroma * math.sin(radians))


def hsl_to_srgb(hue, saturation, lightness):
    hue = hue % 360.0 / 360.0
    if saturation <= 0:
        return (lightness, lightness, lightness)

    def hue_to_channel(p, q, t):
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = (lightness * (1 + saturation) if lightness < 0.5
         else lightness + saturation - lightness * saturation)
    p = 2 * lightness - q
    return (hue_to_channel(p, q, hue + 1 / 3), hue_to_channel(p, q, hue),
            hue_to_channel(p, q, hue - 1 / 3))


def srgb_to_hsl(color):
    r, g, b, _a = _parts(color)
    high, low = max(r, g, b), min(r, g, b)
    lightness = (high + low) / 2
    if high == low:
        return {"h": 0.0, "s": 0.0, "l": lightness}
    delta = high - low
    saturation = delta / (2 - high - low) if lightness > 0.5 else delta / (high + low)
    if high == r:
        hue = ((g - b) / delta) % 6
    elif high == g:
        hue = (b - r) / delta + 2
    else:
        hue = (r - g) / delta + 4
    return {"h": (hue * 60) % 360.0, "s": saturation, "l": lightness}


def srgb_to_p3(color):
    """sRGB to Display P3. In-gamut sRGB always fits inside P3."""
    r, g, b, a = _parts(color)
    linear = (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b))
    xyz = _mul(SRGB_TO_XYZ, linear)
    p3 = _mul(XYZ_TO_P3, xyz)
    return {"r": _clamp01(_linear_to_srgb(p3[0])),
            "g": _clamp01(_linear_to_srgb(p3[1])),
            "b": _clamp01(_linear_to_srgb(p3[2])), "a": a}


def p3_to_srgb(color):
    """Display P3 to sRGB. The result may be outside the sRGB gamut."""
    r, g, b, a = _parts(color)
    linear = (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b))
    xyz = _mul(P3_TO_XYZ, linear)
    srgb = _mul(XYZ_TO_SRGB, xyz)
    return (_linear_to_srgb(srgb[0]), _linear_to_srgb(srgb[1]),
            _linear_to_srgb(srgb[2]), a)


# --- gamut ------------------------------------------------------------------

GAMUT_TOLERANCE = 2e-3


def in_srgb_gamut(color):
    """True when the colour's sRGB channels all fall inside 0..1.

    `color` may carry out-of-range components — that is the point: this reports
    whether a conversion stayed inside rather than clamping silently.

    The tolerance is 0.002 of a channel — about half of one 8-bit step (1/255 is
    0.0039). It exists because a round trip through two 3x3 matrix chains lands
    pure blue at r=0.0005, g=-0.0011, b=1.0002: float noise, not a gamut
    violation. Colours that are genuinely outside the gamut sit far further out
    (a wide-gamut cyan overshoots by 0.05 and more), so this cannot hide one.
    """
    r, g, b, _a = _parts(color)
    return all(-GAMUT_TOLERANCE <= value <= 1 + GAMUT_TOLERANCE
               for value in (r, g, b))


def in_p3_gamut(color):
    """A Display P3 colour with all channels inside 0..1."""
    r, g, b, _a = _parts(color)
    return all(-GAMUT_TOLERANCE <= value <= 1 + GAMUT_TOLERANCE
               for value in (r, g, b))


def to_srgb_gamut(color, steps=40):
    """Map a colour into the sRGB gamut by reducing chroma at fixed L and h.

    This is the documented algorithm: keep perceptual lightness and hue, give up
    chroma until the colour fits. It is not the only possible mapping, and the
    result is never presented as the original colour.
    """
    r, g, b, alpha = _parts(color)
    if in_srgb_gamut(color):
        return make(_clamp01(r), _clamp01(g), _clamp01(b), _clamp01(alpha))
    lch = srgb_to_oklch(color)
    lightness, hue = lch["l"], lch["h"]
    low, high = 0.0, lch["c"]
    best = oklch_to_srgb(lightness, 0.0, hue)
    for _ in range(steps):
        mid = (low + high) / 2
        candidate = oklch_to_srgb(lightness, mid, hue)
        if in_srgb_gamut(raw(*candidate)):
            best = candidate
            low = mid
        else:
            high = mid
    return make(_clamp01(best[0]), _clamp01(best[1]), _clamp01(best[2]),
                _clamp01(_parts(color)[3]))


# --- manipulation -----------------------------------------------------------

def with_lightness(color, lightness):
    lch = srgb_to_oklch(color)
    return to_srgb_gamut(raw(*oklch_to_srgb(_clamp01(lightness), lch["c"],
                                            lch["h"]),
                             _parts(color)[3]))


def with_chroma(color, chroma):
    lch = srgb_to_oklch(color)
    return to_srgb_gamut(raw(*oklch_to_srgb(lch["l"], max(0.0, chroma),
                                            lch["h"]),
                             _parts(color)[3]))


def with_hue(color, hue):
    lch = srgb_to_oklch(color)
    return to_srgb_gamut(raw(*oklch_to_srgb(lch["l"], lch["c"], hue % 360.0),
                             _parts(color)[3]))


def lighten(color, amount):
    """Raise OKLab lightness by `amount` (0..1), keeping hue and chroma."""
    lch = srgb_to_oklch(color)
    return with_lightness(color, _clamp01(lch["l"] + amount))


def darken(color, amount):
    lch = srgb_to_oklch(color)
    return with_lightness(color, _clamp01(lch["l"] - amount))


def mix(first, second, weight=0.5):
    """Interpolate in OKLab, which avoids the muddy midpoints sRGB produces."""
    weight = _clamp01(float(weight))
    a_lab = srgb_to_oklab(first)
    b_lab = srgb_to_oklab(second)
    lightness = a_lab["l"] * (1 - weight) + b_lab["l"] * weight
    a_value = a_lab["a"] * (1 - weight) + b_lab["a"] * weight
    b_value = a_lab["b"] * (1 - weight) + b_lab["b"] * weight
    alpha = (_parts(first)[3] * (1 - weight) + _parts(second)[3] * weight)
    return to_srgb_gamut(raw(*oklab_to_srgb(lightness, a_value, b_value), alpha))


def gradient(first, second, steps=8):
    """Even perceptual steps between two colours."""
    steps = int(steps)
    if steps < 2:
        raise ColorError("a gradient needs at least 2 steps")
    return [mix(first, second, index / (steps - 1)) for index in range(steps)]


def composite(top, bottom):
    """Alpha-composite `top` over `bottom` (source-over)."""
    tr, tg, tb, ta = _parts(top)
    br, bg, bb, ba = _parts(bottom)
    out_a = ta + ba * (1 - ta)
    if out_a <= 0:
        return make(0, 0, 0, 0)

    def blend(top_c, bottom_c):
        return (top_c * ta + bottom_c * ba * (1 - ta)) / out_a

    return make(blend(tr, br), blend(tg, bg), blend(tb, bb), _clamp01(out_a))


# --- accessibility ----------------------------------------------------------

def relative_luminance(color):
    """WCAG 2.x relative luminance of the sRGB colour."""
    r, g, b, _a = _parts(color)

    def channel(value):
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(first, second):
    """WCAG contrast ratio, 1.0 to 21.0. Order does not matter."""
    a = relative_luminance(first)
    b = relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def passes(first, second, level="AA", large=False):
    """WCAG AA or AAA verdict for text at normal or large size."""
    ratio = contrast_ratio(first, second)
    if level.upper() == "AAA":
        needed = 4.5 if large else 7.0
    elif level.upper() == "AA":
        needed = 3.0 if large else 4.5
    else:
        raise ColorError("level must be 'AA' or 'AAA', got %r" % level)
    return {"ratio": round(ratio, 4), "required": needed,
            "passes": ratio >= needed, "level": level.upper(), "large": bool(large)}


def best_foreground(background, candidates=("#000000", "#ffffff")):
    """Whichever candidate contrasts most with `background`."""
    best = None
    for candidate in candidates:
        parsed = parse(candidate)
        ratio = contrast_ratio(parsed, background)
        if best is None or ratio > best[0]:
            best = (ratio, parsed, candidate)
    return {"color": best[1], "hex": to_hex(best[1]),
            "ratio": round(best[0], 4)}


# --- output -----------------------------------------------------------------

def to_hex(color, alpha=False):
    r, g, b, a = _parts(color)
    body = "%02x%02x%02x" % tuple(int(round(_clamp01(v) * 255)) for v in (r, g, b))
    if alpha or a < 1.0:
        body += "%02x" % int(round(_clamp01(a) * 255))
    return "#" + body


def to_css(color, space="oklch"):
    """A CSS colour string in the requested space."""
    if space == "hex":
        return to_hex(color)
    if space == "srgb":
        r, g, b, a = _parts(color)
        return ("rgba(%d, %d, %d, %s)" % (round(r * 255), round(g * 255),
                                          round(b * 255), round(a, 3)))
    lch = srgb_to_oklch(color)
    alpha = _parts(color)[3]
    if space == "oklab":
        lab = srgb_to_oklab(color)
        return "oklab(%.4f %.4f %.4f / %s)" % (lab["l"], lab["a"], lab["b"],
                                               round(alpha, 3))
    return "oklch(%.4f %.4f %.2f / %s)" % (lch["l"], lch["c"], lch["h"],
                                           round(alpha, 3))


def describe(color):
    """Everything worth knowing about one colour, as a Map."""
    lch = srgb_to_oklch(color)
    lab = srgb_to_oklab(color)
    hsl = srgb_to_hsl(color)
    return {
        "hex": to_hex(color),
        "rgb": [round(v, 4) for v in _parts(color)[:3]],
        "alpha": round(_parts(color)[3], 4),
        "oklab": [round(lab["l"], 4), round(lab["a"], 4), round(lab["b"], 4)],
        "oklch": [round(lch["l"], 4), round(lch["c"], 4), round(lch["h"], 2)],
        "hsl": [round(hsl["h"], 2), round(hsl["s"], 4), round(hsl["l"], 4)],
        "luminance": round(relative_luminance(color), 4),
        "in_srgb": in_srgb_gamut(color),
        "css": to_css(color),
    }
