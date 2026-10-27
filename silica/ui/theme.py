"""Themes, colour tokens and WCAG contrast.

A theme is a map of semantic colour tokens to literal colours, plus a mode and a
motion policy. Tokens are emitted as CSS custom properties, so switching theme at
runtime is a class change rather than a re-render.

Contrast is checked, not assumed: every text token is measured against
`background` and `surface`, and a pair below WCAG AA (4.5:1 for body text) is an
error rather than something the renderer quietly ships.
"""

import difflib

DEFAULT_THEME = {
    "name": "Silica Default",
    "mode": "system",
    "colors": {
        "background": "#0B0D10",
        "surface": "#15191E",
        "surface_variant": "#20252C",
        "text_primary": "#F2F4F6",
        "text_secondary": "#A6AFB9",
        "accent": "#65BFA8",
        "border": "#303741",
        "error": "#D96B6B",
    },
    "motion": {"enabled": True, "respect_reduced_motion": True},
}

# tokens whose value must be readable on top of the surface tokens
TEXT_TOKENS = ("text_primary", "text_secondary")
SURFACE_TOKENS = ("background", "surface")

AA_BODY = 4.5
AA_LARGE = 3.0


class ColorError(ValueError):
    pass


def parse_color(value):
    """`#RRGGBB` or `#RGB` -> (r, g, b) floats in 0..1."""
    if not isinstance(value, str) or not value.startswith("#"):
        raise ColorError("colour must be a hex literal like \"#65BFA8\"")
    body = value[1:]
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    if len(body) != 6:
        raise ColorError("colour must be #RGB or #RRGGBB, got %r" % value)
    try:
        return tuple(int(body[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        raise ColorError("colour has non-hex digits: %r" % value)


def to_hex(rgb):
    return "#" + "".join("%02X" % int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb)


def relative_luminance(rgb):
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first, second):
    """WCAG 2.1 contrast ratio between two colours (either hex or rgb tuples)."""
    a = parse_color(first) if isinstance(first, str) else first
    b = parse_color(second) if isinstance(second, str) else second
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def blend(first, second, amount):
    """Linear blend; amount 0.0 -> first, 1.0 -> second."""
    a = parse_color(first) if isinstance(first, str) else first
    b = parse_color(second) if isinstance(second, str) else second
    return to_hex(tuple(a[i] + (b[i] - a[i]) * amount for i in range(3)))


def resolve_theme(props, runtime_theme=None):
    """Validate and normalise a `ui.theme(name, props)` argument."""
    base = _copy_theme(runtime_theme or DEFAULT_THEME)
    if props is None:
        return base
    if not isinstance(props, dict):
        raise ColorError("ui.theme expects a Map of properties")
    for key in props:
        if key not in ("mode", "colors", "motion"):
            suggestion = difflib.get_close_matches(key, ["mode", "colors", "motion"], 1)
            hint = " (did you mean '%s'?)" % suggestion[0] if suggestion else ""
            raise ColorError("unknown theme property '%s'%s" % (key, hint))
    mode = props.get("mode")
    if mode is not None:
        if mode not in ("light", "dark", "system"):
            raise ColorError(
                "theme mode must be \"light\", \"dark\" or \"system\", got %r" % (mode,))
        base["mode"] = mode
    colors = props.get("colors")
    if colors is not None:
        if not isinstance(colors, dict):
            raise ColorError("theme colors must be a Map")
        for name, value in colors.items():
            if not isinstance(name, str):
                raise ColorError("theme colour names must be Strings")
            if not isinstance(value, str):
                raise ColorError(
                    "theme colour '%s' must be a hex String, got %s"
                    % (name, type(value).__name__))
            parse_color(value)
            base["colors"][name] = value.upper() if value.startswith("#") else value
    motion = props.get("motion")
    if motion is not None:
        if not isinstance(motion, dict):
            raise ColorError("theme motion must be a Map")
        for key in motion:
            if key not in ("enabled", "respect_reduced_motion"):
                raise ColorError(
                    "unknown motion property '%s'" % key,
                    )
            if not isinstance(motion[key], bool):
                raise ColorError("theme motion.%s must be a Bool" % key)
            base["motion"][key] = motion[key]
    return base


def _copy_theme(theme):
    return {
        "name": theme.get("name", "Silica Default"),
        "mode": theme.get("mode", "system"),
        "colors": dict(theme.get("colors", {})),
        "motion": dict(theme.get("motion", {})),
    }


def contrast_problems(theme):
    """Every text token that fails AA against a surface token.

    Returns a list of (text_token, surface_token, ratio).
    """
    problems = []
    colors = theme.get("colors", {})
    for text_token in TEXT_TOKENS:
        if text_token not in colors:
            continue
        for surface_token in SURFACE_TOKENS:
            if surface_token not in colors:
                continue
            ratio = contrast_ratio(colors[text_token], colors[surface_token])
            if ratio < AA_BODY:
                problems.append((text_token, surface_token, ratio))
    return problems


def contrast_error(theme):
    """The first AA failure, formatted as a diagnostic, or None."""
    problems = contrast_problems(theme)
    if not problems:
        return None
    text_token, surface_token, ratio = problems[0]
    return ("%s on %s is %.1f:1, below AA %.1f:1"
            % (text_token, surface_token, ratio, AA_BODY),
            "lighten %s or darken %s" % (text_token, surface_token))


def css_variables(theme):
    """The `:root` custom properties for a theme."""
    colors = theme.get("colors", {})
    lines = [":root {"]
    for name in sorted(colors):
        lines.append("  --si-color-%s: %s;" % (name.replace("_", "-"), colors[name]))
    lines.append("  --si-mode: %s;" % theme.get("mode", "system"))
    motion = theme.get("motion", {})
    lines.append("  --si-motion: %s;" % ("on" if motion.get("enabled", True) else "off"))
    lines.append("}")
    if motion.get("respect_reduced_motion", True):
        lines.append("")
        lines.append("@media (prefers-reduced-motion: reduce) {")
        lines.append("  :root { --si-motion: off; }")
        lines.append("}")
    return "\n".join(lines) + "\n"
