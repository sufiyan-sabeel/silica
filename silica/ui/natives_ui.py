"""Native functions for the `ui` namespace.

The module table at the bottom of this file is what `natives.py` registers, so
the checker and the VM see UI functions exactly like any other native. Builder
blocks work because a widget native pushes a node onto the runtime stack and the
compiler emits `ui.__end_block()` at the closing brace; the checker rejects `ret`
and `halt` inside a builder block, so a scope can never be left open.

Everything that writes to disk (`ui.render`) goes through the capability model:
`fs.write` must be granted for the output path, checked with the same
`CapabilitySet` the filesystem module uses.
"""

import os

from ..capabilities import FS_WRITE
from ..errors import CapabilityError, SilicaRuntimeError
from ..natives import type_name
from . import Node
from . import style as _style
from . import theme as _theme
from . import web as _web

ALLOWED_EVENTS = ("click", "submit", "change", "input", "focus", "blur",
                  "keydown", "mouseenter", "mouseleave")


def _fail(message, hint=None):
    raise SilicaRuntimeError(message, hint=hint)


def _need_string(name, value):
    if not isinstance(value, str):
        _fail("%s expects a String, got %s" % (name, type_name(value)))
    return value


def _need_map(name, value):
    if not isinstance(value, dict):
        _fail("%s expects a Map of properties, got %s" % (name, type_name(value)))
    return value


def _props(args, index, name):
    if len(args) <= index:
        return {}
    return dict(_need_map(name, args[index]))


def _validate(kind, props):
    try:
        _style.validate(kind, props)
    except _style.StyleError as exc:
        _fail("ui.%s: %s" % (kind, exc), hint=exc.hint)


# leaf widgets take no block, so they attach to the current parent without
# opening a scope of their own
LEAF_KINDS = {"text", "image", "spacer", "divider"}


def _widget(ctx, kind, props, text=None):
    runtime = ctx.ui
    if kind != "app" and runtime.app is None:
        _fail("ui.%s() must be inside ui.app(...) { ... }" % kind,
              hint="ui.app is the document root; everything else lives inside it")
    _validate(kind, props)
    node = Node(kind, props)
    node.text = text
    if kind in LEAF_KINDS:
        parent = runtime.current_parent()
        if parent is None:
            runtime.roots.append(node)
        else:
            parent.add(node)
        return None
    runtime.push_node(node)
    if kind == "app":
        runtime.app = node
    return None


# --- document root -----------------------------------------------------------
def _app(ctx, args):
    title = _need_string("ui.app", args[0])
    props = _props(args, 1, "ui.app")
    runtime = ctx.ui
    if runtime.app is not None:
        _fail("only one ui.app() may be open per program")
    node = Node("app", props)
    node.text = title
    runtime.push_node(node)
    runtime.app = node
    return None


def _screen(ctx, args):
    return _widget(ctx, "screen", _props(args, 0, "ui.screen"))


def _layout(kind):
    def native(ctx, args):
        return _widget(ctx, kind, _props(args, 0, "ui.%s" % kind))
    return native


def _text(ctx, args):
    value = args[0]
    props = _props(args, 1, "ui.text")
    return _widget(ctx, "text", props, text=value)


def _button(ctx, args):
    label = _need_string("ui.button", args[0])
    props = _props(args, 1, "ui.button")
    return _widget(ctx, "button", props, text=label)


def _image(ctx, args):
    src = _need_string("ui.image", args[0])
    props = _props(args, 1, "ui.image")
    props.setdefault("src", src)
    if "alt" not in props:
        _fail("ui.image needs an 'alt' property",
              hint="alt text is required for accessibility: "
                   'ui.image(src, {alt: "description"})')
    return _widget(ctx, "image", props)


def _link(ctx, args):
    href = _need_string("ui.link", args[0])
    props = _props(args, 1, "ui.link")
    props.setdefault("href", href)
    return _widget(ctx, "link", props, text=props.pop("__text", None))


def _simple(kind):
    def native(ctx, args):
        return _widget(ctx, kind, _props(args, 0, "ui.%s" % kind))
    return native


def _list(ctx, args):
    items = args[0]
    if not isinstance(items, list):
        _fail("ui.list expects a List, got %s" % type_name(items))
    props = _props(args, 1, "ui.list")
    return _widget(ctx, "list", props)


# --- events ------------------------------------------------------------------
def _on(ctx, args):
    event = _need_string("ui.on", args[0])
    if event not in ALLOWED_EVENTS:
        _fail("ui.on: unsupported event '%s'" % event,
              hint="allowed events: " + ", ".join(ALLOWED_EVENTS))
    runtime = ctx.ui
    node = runtime.current_parent()
    if node is None:
        _fail("ui.on() must be inside a widget block",
              hint="ui.button(\"...\") { ui.on(\"click\") { ... } }")
    runtime.push_actions(node, event)
    return None


def _action(op, key_arg, value_arg=None):
    def native(ctx, args):
        actions = ctx.ui.current_actions()
        if actions is None:
            _fail("%s may only be used inside ui.on(...) { ... }" % op,
                  hint="event bodies are the only place actions belong")
        entry = {"op": op}
        if key_arg is not None:
            entry["key"] = _need_string(op, args[0])
        if value_arg is not None and len(args) > 1:
            entry[value_arg] = args[1]
        actions.append(entry)
        return None
    return native


def _navigate(ctx, args):
    actions = ctx.ui.current_actions()
    if actions is None:
        _fail("ui.navigate may only be used inside ui.on(...) { ... }")
    actions.append({"op": "navigate", "href": _need_string("ui.navigate", args[0])})
    return None


def _toggle_class(ctx, args):
    actions = ctx.ui.current_actions()
    if actions is None:
        _fail("ui.toggle may only be used inside ui.on(...) { ... }")
    actions.append({"op": "toggle",
                    "key": _need_string("ui.toggle", args[0]),
                    "class_name": _need_string("ui.toggle", args[1])})
    return None


def _end_block(ctx, args):
    try:
        ctx.ui.pop_scope()
    except Exception:
        _fail("builder block closed without an open scope",
              hint="this is an internal error; please report it")
    return None


# --- theme -------------------------------------------------------------------
def _theme_native(ctx, args):
    name = _need_string("ui.theme", args[0])
    props = _props(args, 1, "ui.theme")
    try:
        resolved = _theme.resolve_theme(props, ctx.ui.theme)
    except _theme.ColorError as exc:
        _fail("ui.theme: %s" % exc)
    resolved["name"] = name
    problem = _theme.contrast_error(resolved)
    if problem is not None:
        _fail("ui.theme: %s" % problem[0], hint=problem[1])
    ctx.ui.theme = resolved
    ctx.ui.theme_set = True
    return None


def _set_theme(ctx, args):
    mode = _need_string("ui.set_theme", args[0])
    if mode not in ("light", "dark", "system"):
        _fail('ui.set_theme expects "light", "dark" or "system", got %r' % (mode,))
    if ctx.ui.theme is None:
        ctx.ui.theme = _theme.resolve_theme({}, None)
    ctx.ui.theme["mode"] = mode
    return None


# --- render ------------------------------------------------------------------
def _render(ctx, args):
    options = dict(_need_map("ui.render", args[0]))
    for key in options:
        if key not in ("target", "out", "inline_css", "inline_runtime",
                       "language", "favicon"):
            _fail("ui.render: unknown option '%s'" % key,
                  hint="options: target, out, inline_css, inline_runtime, "
                       "language, favicon")
    if ctx.ui.stack:
        _fail("ui.render() was called with a builder block still open",
              hint="check that every widget that opens '{' has a matching '}'")
    if ctx.ui.app is None:
        _fail("ui.render() needs a ui.app(...) { ... } block")
    target = options.get("target", "web")
    out = options.get("out", "index.html")
    if not options.get("title") and ctx.ui.app.text:
        options["title"] = ctx.ui.app.text
    _need_string("ui.render out", out)
    theme = ctx.ui.theme or _theme.DEFAULT_THEME
    try:
        files, directory = _web.render(ctx.ui.app, theme, options)
    except _web.RenderError as exc:
        _fail("ui.render: %s" % exc, hint=exc.hint)

    capabilities = ctx.capabilities
    written = []
    for name, text in files.items():
        path = os.path.join(directory, name) if directory not in (".", "") else name
        try:
            authorised = capabilities.resolve_path(FS_WRITE, path)
        except CapabilityError as exc:
            raise CapabilityError(
                "ui.render cannot write %s: %s" % (path, exc.message),
                hint=exc.hint)
        parent = os.path.dirname(authorised)
        if parent and not os.path.isdir(parent):
            _fail("ui.render: output directory does not exist: %s" % parent,
                  hint="create it first; Silica does not create directories")
        try:
            with open(authorised, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            _fail("ui.render: cannot write %s: %s" % (path, exc.strerror or exc))
        written.append(authorised)
    ctx.ui.rendered.extend(written)
    for path in written:
        ctx.write("wrote %s\n" % path)
    return None


# --- library helpers ---------------------------------------------------------
def _colors_parse(ctx, args):
    value = _need_string("ui.lib.colors.parse", args[0])
    try:
        rgb = _theme.parse_color(value)
    except _theme.ColorError as exc:
        _fail("ui.lib.colors.parse: %s" % exc)
    return {"r": round(rgb[0], 6), "g": round(rgb[1], 6), "b": round(rgb[2], 6),
            "hex": _theme.to_hex(rgb)}


def _colors_blend(ctx, args):
    first = _need_string("ui.lib.colors.blend", args[0])
    second = _need_string("ui.lib.colors.blend", args[1])
    amount = args[2]
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        _fail("ui.lib.colors.blend expects a number between 0 and 1")
    if amount < 0 or amount > 1:
        _fail("ui.lib.colors.blend amount must be between 0 and 1")
    try:
        return _theme.blend(first, second, float(amount))
    except _theme.ColorError as exc:
        _fail("ui.lib.colors.blend: %s" % exc)


def _colors_contrast(ctx, args):
    first = _need_string("ui.lib.colors.contrast", args[0])
    second = _need_string("ui.lib.colors.contrast", args[1])
    try:
        return round(_theme.contrast_ratio(first, second), 4)
    except _theme.ColorError as exc:
        _fail("ui.lib.colors.contrast: %s" % exc)


def _theme_token(ctx, args):
    name = _need_string("ui.lib.theme.token", args[0])
    theme = ctx.ui.theme or _theme.DEFAULT_THEME
    colors = theme.get("colors", {})
    if name not in colors:
        _fail("ui.lib.theme.token: unknown token '%s'" % name,
              hint="tokens: " + ", ".join(sorted(colors)))
    return colors[name]


def _theme_contrast(ctx, args):
    name = _need_string("ui.lib.theme.contrast", args[0])
    against = _need_string("ui.lib.theme.contrast", args[1])
    theme = ctx.ui.theme or _theme.DEFAULT_THEME
    colors = theme.get("colors", {})
    for token in (name, against):
        if token not in colors:
            _fail("ui.lib.theme.contrast: unknown token '%s'" % token,
                  hint="tokens: " + ", ".join(sorted(colors)))
    return round(_theme.contrast_ratio(colors[name], colors[against]), 4)


def _layout_breakpoint(ctx, args):
    name = _need_string("ui.lib.layout.breakpoint", args[0])
    if name not in _style.BREAKPOINTS:
        _fail("ui.lib.layout.breakpoint: unknown breakpoint '%s'" % name,
              hint="breakpoints: " + ", ".join(sorted(_style.BREAKPOINTS)))
    return _style.BREAKPOINTS[name]


def _layout_breakpoints(ctx, args):
    return dict(_style.BREAKPOINTS)


def _scroll_direction(axis):
    def native(ctx, args):
        props = _props(args, 0, "ui.lib.scroll.%s" % axis)
        props["direction"] = axis
        return props
    return native


def _animation_transition(ctx, args):
    prop = _need_string("ui.lib.animation.transition", args[0])
    duration = _need_string("ui.lib.animation.transition", args[1])
    easing = _need_string("ui.lib.animation.transition", args[2]) \
        if len(args) > 2 else "ease-out"
    return {"property": prop, "duration": duration, "easing": easing}


# --- registration ------------------------------------------------------------
# (module, name, params, ret, fn, min_args, max_args, accepts_block)
FUNCTIONS = (
    # document root and shell
    ("ui", "app", ["String", "Map"], "Unit", _app, 1, 2, True),
    ("ui", "screen", ["Map"], "Unit", _screen, 0, 1, True),
    # the nine core primitives are re-exported by ui for ergonomics
    ("ui", "card", ["Map"], "Unit", _layout("card"), 0, 1, True),
    ("ui", "text", ["Any", "Map"], "Unit", _text, 1, 2, False),
    ("ui", "row", ["Map"], "Unit", _layout("row"), 0, 1, True),
    ("ui", "column", ["Map"], "Unit", _layout("column"), 0, 1, True),
    ("ui", "stack", ["Map"], "Unit", _layout("stack"), 0, 1, True),
    ("ui", "spacer", ["Map"], "Unit", _simple("spacer"), 0, 1, False),
    ("ui", "button", ["String", "Map"], "Unit", _button, 1, 2, True),
    # events, theme, render
    ("ui", "on", ["String"], "Unit", _on, 1, 1, True),
    ("ui", "navigate", ["String"], "Unit", _navigate, 1, 1, False),
    ("ui", "toggle", ["String", "String"], "Unit", _toggle_class, 2, 2, False),
    ("ui", "theme", ["String", "Map"], "Unit", _theme_native, 1, 2, False),
    ("ui", "set_theme", ["String"], "Unit", _set_theme, 1, 1, False),
    ("ui", "render", ["Map"], "Unit", _render, 1, 1, False),
    # internal: emitted by the compiler, refused in source by the checker
    ("ui", "__end_block", [], "Unit", _end_block, 0, 0, False),
    # state actions
    ("ui.state", "set", ["String", "Any"], "Unit",
     _action("state.set", True, "value"), 2, 2, False),
    ("ui.state", "toggle", ["String"], "Unit",
     _action("state.toggle", True), 1, 1, False),
    ("ui.state", "push", ["String", "Any"], "Unit",
     _action("state.push", True, "value"), 2, 2, False),
    # the full widget catalogue (ui re-exports nine of these)
    ("ui.lib.widgets", "app", ["String", "Map"], "Unit", _app, 1, 2, True),
    ("ui.lib.widgets", "screen", ["Map"], "Unit", _screen, 0, 1, True),
    ("ui.lib.widgets", "row", ["Map"], "Unit", _layout("row"), 0, 1, True),
    ("ui.lib.widgets", "column", ["Map"], "Unit", _layout("column"), 0, 1, True),
    ("ui.lib.widgets", "stack", ["Map"], "Unit", _layout("stack"), 0, 1, True),
    ("ui.lib.widgets", "grid", ["Map"], "Unit", _layout("grid"), 0, 1, True),
    ("ui.lib.widgets", "card", ["Map"], "Unit", _layout("card"), 0, 1, True),
    ("ui.lib.widgets", "text", ["Any", "Map"], "Unit", _text, 1, 2, False),
    ("ui.lib.widgets", "button", ["String", "Map"], "Unit", _button, 1, 2, True),
    ("ui.lib.widgets", "image", ["String", "Map"], "Unit", _image, 1, 2, False),
    ("ui.lib.widgets", "link", ["String", "Map"], "Unit", _link, 1, 2, True),
    ("ui.lib.widgets", "spacer", ["Map"], "Unit", _simple("spacer"), 0, 1, False),
    ("ui.lib.widgets", "divider", ["Map"], "Unit", _simple("divider"), 0, 1, False),
    ("ui.lib.widgets", "scroll", ["Map"], "Unit", _layout("scroll"), 0, 1, True),
    ("ui.lib.widgets", "list", ["List", "Map"], "Unit", _list, 1, 2, True),
    ("ui.lib.widgets", "list_item", ["Map"], "Unit", _layout("list_item"), 0, 1, True),
    ("ui.lib.widgets", "sticky", ["Map"], "Unit", _layout("sticky"), 0, 1, True),
    ("ui.lib.widgets", "animate", ["Map"], "Unit", _layout("animate"), 0, 1, True),
    # theme and layout helpers
    ("ui.lib.theme", "token", ["String"], "String", _theme_token, 1, 1, False),
    ("ui.lib.theme", "contrast", ["String", "String"], "Float", _theme_contrast, 2, 2, False),
    ("ui.lib.colors", "parse", ["String"], "Map", _colors_parse, 1, 1, False),
    ("ui.lib.colors", "blend", ["String", "String", "Any"], "String",
     _colors_blend, 3, 3, False),
    ("ui.lib.colors", "contrast", ["String", "String"], "Float",
     _colors_contrast, 2, 2, False),
    ("ui.lib.layout", "breakpoint", ["String"], "Int", _layout_breakpoint, 1, 1, False),
    ("ui.lib.layout", "breakpoints", [], "Map", _layout_breakpoints, 0, 0, False),
    ("ui.lib.scroll", "vertical", ["Map"], "Map", _scroll_direction("vertical"), 0, 1, False),
    ("ui.lib.scroll", "horizontal", ["Map"], "Map",
     _scroll_direction("horizontal"), 0, 1, False),
    ("ui.lib.animation", "transition", ["String", "String", "String"], "Map",
     _animation_transition, 2, 3, False),
)

# modules that exist as names only, and what to say when they are imported
RESERVED_MODULES = {
    "ui.lib.motion3d": "3D transforms and parallax are planned for UI 0.3",
    "ui.lib.navigation": "routing and transitions are not implemented",
    "ui.lib.gestures": "drag and pinch gestures are not implemented",
    "ui.lib.accessibility": "a11y auditing helpers are not implemented",
    "ui.lib.platform": "platform detection is not implemented",
    "ui.lib.terminal": "the terminal renderer is not implemented",
    "ui.lib.graphics": "immediate-mode drawing is not implemented",
    "ui.lib.canvas": "immediate-mode drawing is not implemented",
}

# adapter slots: specified, never installed
ADAPTER_MODULES = {
    "ui.lib.react", "ui.lib.flutter", "ui.lib.compose", "ui.lib.swiftui",
    "ui.lib.css", "ui.lib.qt",
}

# the nine names ui re-exports from ui.lib.widgets
CORE_PRIMITIVES = ("app", "screen", "card", "text", "row", "column", "stack",
                   "spacer", "button")

# actions allowed inside an event body
EVENT_ACTIONS = ("ui.state.set", "ui.state.toggle", "ui.state.push",
                 "ui.navigate", "ui.toggle")
