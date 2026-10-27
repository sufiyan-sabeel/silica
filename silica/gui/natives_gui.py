"""Native functions for the `gui` namespace.

`ui` was already taken: it is the HTML/UI-DSL namespace shipped in 0.2.0, where
`ui.app` builds a web node tree. Desktop windows therefore live in `gui`, so that
`ui.app` keeps meaning what it meant. The brief allowed adapting the example to
the real runtime, and silently changing the meaning of an existing function would
have been the worse adaptation.

Opening a window and running an event loop needs the `gui.run` capability
(`--allow-gui`). Building the widget tree needs nothing, so a program can be
checked and inspected on a headless machine.
"""

from ..capabilities import GUI_RUN
from ..errors import SilicaRuntimeError
from ..natives import type_name
from . import App, GUIError, Node, Window, describe

_DEFAULT_SIZE = (640, 420)


def _fail(message, hint=None):
    raise SilicaRuntimeError(message, hint=hint)


def _registry(ctx):
    vm = ctx.vm
    table = getattr(vm, "gui_objects", None)
    if table is None:
        table = {}
        vm.gui_objects = table
    return table


def _need_string(name, value):
    if not isinstance(value, str):
        _fail("%s expects a String, got %s" % (name, type_name(value)))
    return value


def _need_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("%s expects an Int, got %s" % (name, type_name(value)))
    return value


def _register(ctx, obj):
    handle = ctx.next_handle()
    _registry(ctx)[handle] = obj
    return handle


def _app(ctx, name, value):
    app = _registry(ctx).get(value)
    if not isinstance(app, App):
        _fail("%s: %r is not an application handle" % (name, value),
              hint='create one with gui.app("title")')
    app._vm = ctx.vm
    return app


def _node(ctx, value, name):
    node = _registry(ctx).get(value)
    if not isinstance(node, Node):
        _fail("%s: %r is not a widget" % (name, value),
              hint="widgets come from gui.text, gui.button, gui.window, ...")
    return node


def _g_app(ctx, args):
    title = _need_string("gui.app", args[0]) if args else "Silica"
    return _register(ctx, App(title))


def _g_window(ctx, args):
    app = _app(ctx, "gui.window", args[0])
    title = _need_string("gui.window", args[1]) if len(args) > 1 else app.title
    width = _need_int("gui.window", args[2]) if len(args) > 2 else _DEFAULT_SIZE[0]
    height = _need_int("gui.window", args[3]) if len(args) > 3 else _DEFAULT_SIZE[1]
    if width <= 0 or height <= 0:
        _fail("gui.window: width and height must be positive")
    window = app.window(title, width, height)
    return _register(ctx, window)


def _widget(kind):
    def build(ctx, args):
        text = _need_string("gui.%s" % kind, args[0]) if args else ""
        return _register(ctx, Node(kind, text))
    return build


def _container(kind):
    def build(ctx, args):
        return _register(ctx, Node(kind))
    return build


def _g_spacer(ctx, args):
    node = Node("spacer")
    node.props["height"] = _need_int("gui.spacer", args[0]) if args else 8
    return _register(ctx, node)


def _g_add(ctx, args):
    parent = _registry(ctx).get(args[0])
    if not isinstance(parent, Node):
        _fail("%r is not a window or a container" % (args[0],),
              hint="add to a window, a row or a column")
    child = _node(ctx, args[1], "gui.add")
    if parent.kind in ("text", "heading", "button", "field", "checkbox", "spacer"):
        _fail("%s cannot contain children" % parent.kind,
              hint="add to a window, a row or a column")
    parent.add(child)
    return None


def _g_on_click(ctx, args):
    node = _node(ctx, args[0], "gui.on_click")
    handler = _need_string("gui.on_click", args[1])
    if node.kind not in ("button", "checkbox"):
        _fail("gui.on_click needs a button or a checkbox, not %s" % node.kind)
    node.handler = handler
    app = getattr(ctx.vm, "gui_app", None)
    if app is not None:
        app.handlers()[id(node)] = handler
    return None


def _g_show(ctx, args):
    window = _node(ctx, args[0], "gui.show")
    if not isinstance(window, Window):
        _fail("gui.show expects a window, got %s" % window.kind)
    app = _app_for(ctx, window)
    try:
        app.build(window)
    except GUIError as exc:
        _fail("gui.show: %s" % exc)
    return None


def _g_run(ctx, args):
    app = _app(ctx, "gui.run", args[0])
    ctx.vm.gui_app = app
    if not app.windows:
        _fail("gui.run: the application has no window",
              hint="create one with gui.window(app, \"title\", 640, 420)")
    ticks = _need_int("gui.run", args[1]) if len(args) > 1 else 0
    window = app.windows[0]
    try:
        app.run(window, ticks=ticks)
    except GUIError as exc:
        _fail("gui.run: %s" % exc)
    return None


def _g_close(ctx, args):
    node = _node(ctx, args[0], "gui.close")
    app = _app_for(ctx, node)
    app.close(node if isinstance(node, Window) else node)
    return None


def _app_for(ctx, node):
    """Find the application that owns a window."""
    app = getattr(ctx.vm, "gui_app", None)
    if app is not None:
        return app
    for value in _registry(ctx).values():
        if isinstance(value, App):
            value._vm = ctx.vm
            return value
    _fail("no application is open")


def _g_set_text(ctx, args):
    node = _node(ctx, args[0], "gui.set_text")
    value = _need_string("gui.set_text", args[1])
    if node.kind == "field":
        node.value = value
        if node.tk is not None:
            node.tk.delete(0, "end")
            node.tk.insert(0, value)
    else:
        node.text = value
        if node.tk is not None:
            node.tk.configure(text=value)
    return None


def _g_value(ctx, args):
    node = _node(ctx, args[0], "gui.value")
    if node.kind == "field":
        if node.tk is not None:
            return node.tk.get()
        return node.value
    if node.kind == "checkbox":
        if node.tk is not None:
            return bool(node.tk.instate(["selected"]))
        return node.checked
    return node.text


def _g_set_value(ctx, args):
    node = _node(ctx, args[0], "gui.set_value")
    value = _need_string("gui.set_value", args[1])
    if node.kind != "field":
        _fail("gui.set_value expects a field, got %s" % node.kind)
    node.value = value
    if node.tk is not None:
        node.tk.delete(0, "end")
        node.tk.insert(0, value)
    return None


def _g_click(ctx, args):
    """Activate a button the way a user would.

    tkinter's own `invoke()` runs the widget's command, so this goes through
    exactly the same path a real click does — it is not a test-only shortcut.
    """
    node = _node(ctx, args[0], "gui.click")
    if node.kind not in ("button", "checkbox"):
        _fail("gui.click needs a button or a checkbox, not %s" % node.kind)
    if node.tk is None:
        _fail("gui.click: the window has not been shown yet",
              hint="call gui.show(window) first")
    try:
        node.tk.invoke()
    except Exception as exc:
        _fail("gui.click: %s" % exc)
    return None


def _g_widgets(ctx, args):
    node = _node(ctx, args[0], "gui.widgets")
    return [child.kind for child in node.children]


def _g_theme(ctx, args):
    app = _app(ctx, "gui.theme", args[0])
    colours = args[1]
    if not isinstance(colours, dict):
        _fail("gui.theme expects a Map, got %s" % type_name(colours))
    app.theme.update({str(k): str(v) for k, v in colours.items()})
    return None


def _g_status(ctx, args):
    return describe()


# (name, params, ret, fn, min_args, max_args, requires, path_arg)
FUNCTIONS = (
    ("app", ["String"], "Any", _g_app, 0, 1, None, None),
    ("window", ["Any", "String", "Int", "Int"], "Any", _g_window, 1, 4, None, None),
    ("text", ["String"], "Any", _widget("text"), 1, 1, None, None),
    ("heading", ["String"], "Any", _widget("heading"), 1, 1, None, None),
    ("button", ["String"], "Any", _widget("button"), 1, 1, None, None),
    ("field", ["String"], "Any", _widget("field"), 0, 1, None, None),
    ("checkbox", ["String"], "Any", _widget("checkbox"), 1, 1, None, None),
    ("row", [], "Any", _container("row"), 0, 0, None, None),
    ("column", [], "Any", _container("column"), 0, 0, None, None),
    ("spacer", ["Int"], "Any", _g_spacer, 0, 1, None, None),
    ("add", ["Any", "Any"], "Unit", _g_add, 2, 2, None, None),
    ("on_click", ["Any", "String"], "Unit", _g_on_click, 2, 2, None, None),
    ("show", ["Any"], "Unit", _g_show, 1, 1, GUI_RUN, None),
    ("run", ["Any", "Int"], "Unit", _g_run, 1, 2, GUI_RUN, None),
    ("close", ["Any"], "Unit", _g_close, 1, 1, None, None),
    ("set_text", ["Any", "String"], "Unit", _g_set_text, 2, 2, None, None),
    ("value", ["Any"], "Any", _g_value, 1, 1, None, None),
    ("set_value", ["Any", "String"], "Unit", _g_set_value, 2, 2, None, None),
    ("click", ["Any"], "Unit", _g_click, 1, 1, None, None),
    ("widgets", ["Any"], "List", _g_widgets, 1, 1, None, None),
    ("theme", ["Any", "Map"], "Unit", _g_theme, 2, 2, None, None),
    ("status", [], "Map", _g_status, 0, 0, None, None),
)

LAYOUT = (
    ("add", ["Any", "Any"], "Unit", _g_add, 2, 2, None, None),
    ("row", [], "Any", _container("row"), 0, 0, None, None),
    ("column", [], "Any", _container("column"), 0, 0, None, None),
    ("spacer", ["Int"], "Any", _g_spacer, 0, 1, None, None),
)

THEMING = (
    ("theme", ["Any", "Map"], "Unit", _g_theme, 2, 2, None, None),
    ("status", [], "Map", _g_status, 0, 0, None, None),
)

FUNCTION_TABLES = {
    "gui": FUNCTIONS,
    "gui.lib.widgets": FUNCTIONS,
    "gui.lib.layout": LAYOUT,
    "gui.lib.theme": THEMING,
}
