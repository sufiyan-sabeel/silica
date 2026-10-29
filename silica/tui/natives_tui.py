"""Native functions for the `tui` namespaces.

`tui` holds the whole API. `tui.lib.widgets`, `tui.lib.layout` and `tui.lib.style`
re-export parts of it, so the documented imports all resolve to real functions
rather than to aliases that only look real.

A TUI writes to a terminal, which is a privileged act, so the entry points that
touch the screen require the `tui.run` capability.
"""

from ..capabilities import TUI_RUN
from ..errors import SilicaRuntimeError
from ..natives import type_name
from . import App, Node, TUIError, close, poll, render, run

def _registry(ctx):
    """Per-VM object table.

    It must not be a module global: handle numbers restart with each VM, so a
    second run in the same process (the REPL, or two programs in one session)
    would otherwise see the first run's widgets under the same handle.
    """
    vm = ctx.vm
    table = getattr(vm, "tui_objects", None)
    if table is None:
        table = {}
        vm.tui_objects = table
    return table


def _fail(message, hint=None):
    raise SilicaRuntimeError(message, hint=hint)


def _need_string(name, value):
    if not isinstance(value, str):
        _fail("%s expects a String, got %s" % (name, type_name(value)))
    return value


def _need_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("%s expects an Int, got %s" % (name, type_name(value)))
    return value


def _app(ctx, name, value):
    app = _registry(ctx).get(value)
    if app is None:
        _fail("%s: %r is not an application handle" % (name, value),
              hint="create one with tui.app(\"title\")")
    return app


def _node(app, value, ctx=None):
    node = (_registry(ctx) if ctx is not None else {}).get(value)
    if not isinstance(node, Node):
        _fail("%r is not a widget" % (value,),
              hint="widgets come from tui.text, tui.button, tui.panel, ...")
    return node


def _parent(value, ctx):
    """A container: either the application itself or a Node that can hold children."""
    holder = _registry(ctx).get(value)
    if isinstance(holder, (App, Node)):
        return holder
    _fail("%r is not an application or a widget" % (value,))


def _register(ctx, value, obj):
    _registry(ctx)[value] = obj
    return value


def _widget(kind):
    def build(ctx, args):
        text = _need_string("tui.%s" % kind, args[0]) if args else ""
        return _register(ctx, ctx.next_handle(), Node(kind, text))
    return build


def _container(kind):
    def build(ctx, args):
        return _register(ctx, ctx.next_handle(), Node(kind))
    return build


def _t_app(ctx, args):
    title = _need_string("tui.app", args[0]) if args else "Silica"
    return _register(ctx, ctx.next_handle(), App(title))


def _t_panel(ctx, args):
    title = _need_string("tui.panel", args[0]) if args else ""
    return _register(ctx, ctx.next_handle(), Node("panel", title))


def _t_list(ctx, args):
    items = args[0]
    if not isinstance(items, list):
        _fail("tui.list expects a List, got %s" % type_name(items))
    node = Node("list")
    node.items = [str(item) for item in items]
    return _register(ctx, ctx.next_handle(), node)


def _t_table(ctx, args):
    rows = args[0]
    if not isinstance(rows, list):
        _fail("tui.table expects a List of rows, got %s" % type_name(rows))
    node = Node("table")
    node.rows = [list(row) if isinstance(row, list) else [row] for row in rows]
    return _register(ctx, ctx.next_handle(), node)


def _t_spacer(ctx, args):
    node = Node("spacer")
    node.props["height"] = _need_int("tui.spacer", args[0]) if args else 1
    return _register(ctx, ctx.next_handle(), node)


def _t_add(ctx, args):
    parent = _parent(args[0], ctx)
    child = _node(None, args[1], ctx)
    if isinstance(parent, Node) and parent.kind in (
            "text", "heading", "button", "input", "divider", "spacer",
            "list", "table"):
        _fail("%s cannot contain children" % parent.kind,
              hint="add to a column, a row or a panel")
    parent.add(child)
    return None


def _t_render(ctx, args):
    app = _app(ctx, "tui.render", args[0])
    try:
        lines = render(app)
    except TUIError as exc:
        _fail("tui.render: %s" % exc)
    return lines


def _t_poll(ctx, args):
    app = _app(ctx, "tui.poll", args[0])
    try:
        return poll(app)
    except TUIError as exc:
        _fail("tui.poll: %s" % exc)


def _t_run(ctx, args):
    app = _app(ctx, "tui.run", args[0])
    quit_key = _need_string("tui.run", args[1]) if len(args) > 1 else "q"
    try:
        run(app, quit_key)
    except TUIError as exc:
        _fail("tui.run: %s" % exc)
    return None


def _t_close(ctx, args):
    close(_app(ctx, "tui.close", args[0]))
    return None


def _t_pressed(ctx, args):
    """Consume the last activation: one keypress activates exactly once."""
    app = _app(ctx, "tui.pressed", args[0])
    return app.take_pressed()


def _t_press(ctx, args):
    app = _app(ctx, "tui.press", args[0])
    return app.press()


def _t_focus(ctx, args):
    app = _app(ctx, "tui.focus", args[0])
    node = app.focused()
    return node.label() if node is not None else ""


def _t_focus_next(ctx, args):
    app = _app(ctx, "tui.focus_next", args[0])
    step = _need_int("tui.focus_next", args[1]) if len(args) > 1 else 1
    app.focus_next(step)
    node = app.focused()
    return node.label() if node is not None else ""


def _t_disable(ctx, args):
    node = _node(None, args[0], ctx)
    node.props["disabled"] = True
    return None


def _t_enable(ctx, args):
    node = _node(None, args[0], ctx)
    node.props.pop("disabled", None)
    return None


def _t_colour_mode(ctx, args):
    app = _app(ctx, "tui.colour_mode", args[0])
    return app._colour_mode


def _t_selected(ctx, args):
    app = _app(ctx, "tui.selected", args[0])
    node = app.focused()
    if node is None:
        return ""
    if node.kind == "input":
        return node.value
    if node.kind == "list":
        return node.items[0] if node.items else ""
    return node.text


def _t_set_text(ctx, args):
    node = _node(None, args[0], ctx)
    value = _need_string("tui.set_text", args[1])
    if node.kind == "input":
        node.value = value
    else:
        node.text = value
    return None


def _t_value(ctx, args):
    node = _node(None, args[0], ctx)
    if node.kind == "input":
        return node.value
    return node.text


def _t_theme(ctx, args):
    app = _app(ctx, "tui.theme", args[0])
    colours = args[1]
    if not isinstance(colours, dict):
        _fail("tui.theme expects a Map of tokens, got %s" % type_name(colours))
    app.theme.update({str(k): str(v) for k, v in colours.items()})
    return None


def _t_tokens(ctx, args):
    app = _app(ctx, "tui.tokens", args[0])
    return dict(app.theme)


def _t_size(ctx, args):
    app = _app(ctx, "tui.size", args[0])
    width, height = app.size
    return {"width": width, "height": height}


# (name, params, ret, fn, min_args, max_args, requires, path_arg)
WIDGETS = (
    ("app", ["String"], "Any", _t_app, 0, 1, None, None),
    ("panel", ["String"], "Any", _t_panel, 0, 1, None, None),
    ("text", ["String"], "Any", _widget("text"), 1, 1, None, None),
    ("heading", ["String"], "Any", _widget("heading"), 1, 1, None, None),
    ("button", ["String"], "Any", _widget("button"), 1, 1, None, None),
    # `input` is a reserved Silica keyword, so the editable field is `field`
    ("field", ["String"], "Any", _widget("input"), 0, 1, None, None),
    ("checkbox", ["String"], "Any", _widget("checkbox"), 1, 1, None, None),
    ("divider", [], "Any", _container("divider"), 0, 0, None, None),
    ("list", ["List"], "Any", _t_list, 1, 1, None, None),
    ("table", ["List"], "Any", _t_table, 1, 1, None, None),
    ("spacer", ["Int"], "Any", _t_spacer, 0, 1, None, None),
    ("row", [], "Any", _container("row"), 0, 0, None, None),
    ("column", [], "Any", _container("column"), 0, 0, None, None),
)

LAYOUT = (
    ("add", ["Any", "Any"], "Unit", _t_add, 2, 2, None, None),
    ("row", [], "Any", _container("row"), 0, 0, None, None),
    ("column", [], "Any", _container("column"), 0, 0, None, None),
    ("spacer", ["Int"], "Any", _t_spacer, 0, 1, None, None),
    ("divider", [], "Any", _container("divider"), 0, 0, None, None),
)

STYLE = (
    ("theme", ["Any", "Map"], "Unit", _t_theme, 2, 2, None, None),
    ("tokens", ["Any"], "Map", _t_tokens, 1, 1, None, None),
)

RUNTIME = (
    ("add", ["Any", "Any"], "Unit", _t_add, 2, 2, None, None),
    ("render", ["Any"], "List", _t_render, 1, 1, TUI_RUN, None),
    ("poll", ["Any"], "String", _t_poll, 1, 1, TUI_RUN, None),
    ("run", ["Any", "String"], "Unit", _t_run, 1, 2, TUI_RUN, None),
    ("close", ["Any"], "Unit", _t_close, 1, 1, None, None),
    ("press", ["Any"], "String", _t_press, 1, 1, None, None),
    ("pressed", ["Any"], "String", _t_pressed, 1, 1, None, None),
    ("focus", ["Any"], "String", _t_focus, 1, 1, None, None),
    ("focus_next", ["Any", "Int"], "String", _t_focus_next, 1, 2, None, None),
    ("disable", ["Any"], "Unit", _t_disable, 1, 1, None, None),
    ("enable", ["Any"], "Unit", _t_enable, 1, 1, None, None),
    ("colour_mode", ["Any"], "String", _t_colour_mode, 1, 1, None, None),
    ("selected", ["Any"], "String", _t_selected, 1, 1, None, None),
    ("set_text", ["Any", "String"], "Unit", _t_set_text, 2, 2, None, None),
    ("value", ["Any"], "String", _t_value, 1, 1, None, None),
    ("size", ["Any"], "Map", _t_size, 1, 1, None, None),
)

# module name -> function table
FUNCTIONS = {
    "tui": WIDGETS + RUNTIME + STYLE,
    "tui.lib.widgets": WIDGETS,
    "tui.lib.layout": LAYOUT,
    "tui.lib.style": STYLE + (("size", ["Any"], "Map", _t_size, 1, 1, None, None),),
}
