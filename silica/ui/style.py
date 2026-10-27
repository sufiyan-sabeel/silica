"""The style model: properties -> CSS declarations, and breakpoints -> queries.

Properties are map literals, not a CSS-like mini-syntax, so there is no second
grammar to keep in sync and a value can be computed at run time::

    ui.card({padding: gap, radius: "12px"})

Unknown keys are errors, not silently ignored, and the message suggests the
nearest known key.

Layout itself is CSS: the renderer emits flexbox/grid declarations and lets the
browser lay out. Claiming pixel parity with a hand-written layout engine would
be false, so the tests assert emitted structure and CSS rules, not pixels.
"""

import difflib

BREAKPOINTS = {"sm": 640, "md": 768, "lg": 1024, "xl": 1280}

# --- property table ----------------------------------------------------------
# css: the declaration this property produces (None for structural properties)
# kind: length | number | colour | enum | string | bool | map | any
# values: allowed names for enum kinds
PROPERTIES = {
    "padding": {"css": "padding", "kind": "length"},
    "margin": {"css": "margin", "kind": "length"},
    "gap": {"css": "gap", "kind": "length"},
    "radius": {"css": "border-radius", "kind": "length"},
    "elevation": {"css": "box-shadow", "kind": "elevation"},
    "background": {"css": "background", "kind": "colour"},
    "color": {"css": "color", "kind": "colour"},
    "border": {"css": "border", "kind": "border"},
    "width": {"css": "width", "kind": "length"},
    "height": {"css": "height", "kind": "length"},
    "min_width": {"css": "min-width", "kind": "length"},
    "max_width": {"css": "max-width", "kind": "length"},
    "align": {"css": "align-items", "kind": "enum",
              "values": {"start": "flex-start", "center": "center", "end": "flex-end",
                         "stretch": "stretch", "baseline": "baseline"}},
    "justify": {"css": "justify-content", "kind": "enum",
                "values": {"start": "flex-start", "center": "center", "end": "flex-end",
                           "between": "space-between", "around": "space-around",
                           "evenly": "space-evenly"}},
    "wrap": {"css": "flex-wrap", "kind": "bool", "values": {True: "wrap",
                                                            False: "nowrap"}},
    "columns": {"css": "grid-template-columns", "kind": "columns"},
    "size": {"css": "font-size", "kind": "size"},
    "weight": {"css": "font-weight", "kind": "string"},
    "line_height": {"css": "line-height", "kind": "string"},
    "letter_spacing": {"css": "letter-spacing", "kind": "length"},
    "direction": {"css": None, "kind": "enum",
                  "values": {"vertical": "vertical", "horizontal": "horizontal"}},
    "snap": {"css": None, "kind": "string"},
    "physics": {"css": None, "kind": "string"},
    "overscroll": {"css": "overscroll-behavior", "kind": "string"},
    "top": {"css": "top", "kind": "length"},
    "sticky": {"css": None, "kind": "bool"},
    "duration": {"css": None, "kind": "time"},
    "easing": {"css": None, "kind": "string"},
    "property": {"css": None, "kind": "string"},
    "keyframes": {"css": None, "kind": "map"},
    # structural properties, emitted as HTML rather than CSS
    "id": {"css": None, "kind": "string"},
    "role": {"css": None, "kind": "string"},
    "aria_label": {"css": None, "kind": "string"},
    "hidden": {"css": None, "kind": "bool"},
    "src": {"css": None, "kind": "string"},
    "alt": {"css": None, "kind": "string"},
    "href": {"css": None, "kind": "string"},
    "bind_text": {"css": None, "kind": "string"},
    "bind_class": {"css": None, "kind": "map"},
}

STRUCTURAL = {name for name, spec in PROPERTIES.items() if spec["css"] is None}

SIZE_SCALE = {"sm": "0.875rem", "md": "1rem", "lg": "1.25rem", "xl": "1.5rem",
              "xxl": "2rem"}

ELEVATION = {0: "none",
             1: "0 1px 2px rgba(0,0,0,0.28)",
             2: "0 2px 6px rgba(0,0,0,0.32)",
             3: "0 6px 16px rgba(0,0,0,0.36)",
             4: "0 12px 32px rgba(0,0,0,0.40)"}

# widget -> declarations that define its box model before properties apply
WIDGET_CSS = {
    "app": "display:block;min-height:100vh;",
    "screen": "display:block;padding:env(safe-area-inset-top) "
              "env(safe-area-inset-right) env(safe-area-inset-bottom) "
              "env(safe-area-inset-left);",
    "row": "display:flex;flex-direction:row;",
    "column": "display:flex;flex-direction:column;",
    "stack": "display:grid;grid-template-areas:'stack';",
    "grid": "display:grid;",
    "card": "display:block;",
    "text": "display:block;margin:0;",
    "button": "display:inline-flex;align-items:center;justify-content:center;"
              "cursor:pointer;border:0;font:inherit;",
    "image": "display:block;max-width:100%;",
    "link": "display:inline;cursor:pointer;",
    "spacer": "display:block;flex:1 1 auto;",
    "divider": "display:block;height:1px;border:0;",
    "scroll": "display:block;overflow-y:auto;overflow-x:hidden;"
              "overscroll-behavior:contain;",
    "list": "display:block;",
    "list_item": "display:block;",
    "sticky": "position:sticky;",
    "animate": "display:block;",
}

TEXTUAL = {"text", "button", "link"}


class StyleError(ValueError):
    """Raised for an unknown property or a value the property cannot take."""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


def validate(kind, props):
    """Reject unknown keys and impossible values before anything is emitted."""
    for key, value in props.items():
        if not isinstance(key, str):
            raise StyleError("property names must be Strings, got %s"
                             % type(key).__name__)
        spec = PROPERTIES.get(key)
        if spec is None:
            suggestion = difflib.get_close_matches(key, list(PROPERTIES), 1)
            hint = ("did you mean '%s'?" % suggestion[0] if suggestion
                    else "documented properties: " + ", ".join(sorted(PROPERTIES)))
            raise StyleError("unknown property '%s' for ui.%s" % (key, kind), hint)
        _check_value(kind, key, spec, value)


def _check_value(kind, key, spec, value):
    if isinstance(value, dict):
        # a map value is either a responsive breakpoint map or a nested map
        if key == "bind_class" or key == "keyframes":
            return
        for name in value:
            if name not in BREAKPOINTS:
                suggestion = difflib.get_close_matches(name, list(BREAKPOINTS), 1)
                hint = ("did you mean '%s'?" % suggestion[0] if suggestion
                        else "breakpoints: " + ", ".join(sorted(BREAKPOINTS)))
                raise StyleError(
                    "unknown breakpoint '%s' for property '%s'" % (name, key), hint)
        for sub in value.values():
            _check_value(kind, key, spec, sub)
        return
    type_name = spec["kind"]
    if type_name == "bool":
        if not isinstance(value, bool):
            raise StyleError("property '%s' expects a Bool" % key)
    elif type_name == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StyleError("property '%s' expects a number" % key)
    elif type_name == "length":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise StyleError("property '%s' expects a length like \"12px\" or a number" % key)
    elif type_name == "enum":
        if value not in spec["values"]:
            raise StyleError(
                "property '%s' does not accept %r" % (key, value),
                "allowed: " + ", ".join(sorted(spec["values"])))
    elif type_name == "elevation":
        if isinstance(value, bool) or not isinstance(value, int):
            raise StyleError("property 'elevation' expects an Int 0-4")
        if value not in ELEVATION:
            raise StyleError("property 'elevation' must be 0-4, got %d" % value)
    elif type_name == "size":
        if value not in SIZE_SCALE:
            raise StyleError("property 'size' does not accept %r" % (value,),
                             "allowed: " + ", ".join(sorted(SIZE_SCALE)))
    elif type_name == "time":
        if not isinstance(value, str) or not (value.endswith("ms") or value.endswith("s")):
            raise StyleError(
                "property 'duration' expects a time String like \"300ms\"",
                "Silica has no time literal; write it as a string")
    elif type_name in ("string", "colour", "border", "columns"):
        if not isinstance(value, str):
            raise StyleError("property '%s' expects a String" % key)
        if type_name == "colour" and value.startswith("#"):
            from .theme import ColorError, parse_color
            try:
                parse_color(value)
            except ColorError as exc:
                raise StyleError("property '%s': %s" % (key, exc))


def declarations(kind, props, css_class):
    """Split a node's properties into base declarations and media queries.

    Returns (base_list, [(min_width_px, [declarations])]).
    """
    base = []
    media = {}
    for key, value in props.items():
        spec = PROPERTIES[key]
        if spec["css"] is None:
            continue
        if isinstance(value, dict) and key not in ("bind_class", "keyframes"):
            for name, sub in value.items():
                width = BREAKPOINTS[name]
                media.setdefault(width, []).extend(_declaration(key, spec, sub))
            continue
        base.extend(_declaration(key, spec, value))
    return base, sorted(media.items())


def _declaration(key, spec, value):
    css = spec["css"]
    kind = spec["kind"]
    if kind == "bool":
        return ["%s: %s;" % (css, spec["values"][value])]
    if kind == "enum":
        return ["%s: %s;" % (css, spec["values"][value])]
    if kind == "size":
        return ["%s: %s;" % (css, SIZE_SCALE[value])]
    if kind == "elevation":
        return ["%s: %s;" % (css, ELEVATION[value])]
    if kind == "colour":
        if value.startswith("#"):
            return ["%s: %s;" % (css, value)]
        return ["%s: var(--si-color-%s, %s);" % (css, value.replace("_", "-"), value)]
    if kind == "border":
        return ["%s: %s;" % (css, value)]
    if kind == "length":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return ["%s: %dpx;" % (css, value)]
        return ["%s: %s;" % (css, value)]
    if kind == "columns":
        return ["%s: %s;" % (css, value)]
    return ["%s: %s;" % (css, value)]


def widget_rule(kind, css_class, base, media, props=None):
    """The full CSS rule(s) for one node."""
    chunks = []
    defaults = widget_defaults(kind, props or {})
    body = [defaults] + base
    chunks.append(".%s { %s }" % (css_class, " ".join(body)))
    for width, decls in media:
        chunks.append("@media (min-width: %dpx) { .%s { %s } }"
                      % (width, css_class, " ".join(decls)))
    return "\n".join(chunks)


def widget_defaults(kind, props):
    """The box model a widget starts from, before its properties apply."""
    defaults = WIDGET_CSS.get(kind, "display:block;")
    if kind == "screen" and "padding" in props:
        # the property wins; do not emit the safe-area padding as well
        return "display:block;"
    return defaults


def scroll_rule(css_class, props):
    direction = props.get("direction", "vertical")
    snap = props.get("snap", "none")
    decls = []
    if direction == "horizontal":
        decls.append("overflow-x:auto; overflow-y:hidden;")
    else:
        decls.append("overflow-y:auto; overflow-x:hidden;")
    if snap != "none":
        axis = "x" if direction == "horizontal" else "y"
        decls.append("scroll-snap-type: %s %s;" % (axis, snap))
    return ".%s { %s }" % (css_class, " ".join(decls))


def sticky_rule(css_class, props):
    top = props.get("top", "0")
    if isinstance(top, (int, float)) and not isinstance(top, bool):
        top = "%dpx" % top
    return ".%s { position: sticky; top: %s; }" % (css_class, top)


def animation_rule(css_class, props):
    duration = props.get("duration", "300ms")
    easing = props.get("easing", "ease-out")
    prop = props.get("property", "all")
    return (".%s { transition: %s %s %s; }" % (css_class, prop, duration, easing),
            "@media (prefers-reduced-motion: reduce) { .%s { transition: none; "
            "animation: none; } }" % css_class)
