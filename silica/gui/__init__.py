"""The Silica GUI: real desktop windows through tkinter.

The widget tree, layout and event wiring are backend-independent; only the last
step touches tkinter. That split matters for testing: the tree can be built and
inspected with no display, and only `show`/`run` need one.

Click handlers
--------------
`gui.on_click(button, "handle_click")` takes the *name* of a Silica function.
Silica has no first-class functions, so a handler is a name the runtime resolves
against the compiled chunk. It is not `eval` and not `exec`: the chunk already
contains the function, and the VM is asked to run it by name.

The handler runs on a short-lived VM that shares the parent's global slots and
its widget registry, so `gui.set_text(...)` inside a handler reaches the same
widgets. Locals do not persist between invocations, which is stated in the docs.

Failure to start
----------------
If tkinter is missing, or there is no display server, `show` raises with the
exact reason instead of dying inside Tk. A headless machine can still build the
whole tree and inspect it; it just cannot put it on screen.
"""

import os

THEME = {
    "background": "#F3F1EC",
    "surface": "#FFFFFF",
    "text": "#1F2328",
    "text_muted": "#5A6570",
    "accent": "#2F6F5E",
    "border": "#D6D1C6",
    "error": "#B4463C",
}

PADDING = 10


class GUIError(RuntimeError):
    pass


def _tkinter():
    try:
        import tkinter
    except ModuleNotFoundError:
        raise GUIError(
            "tkinter is not available, so a window cannot be opened. "
            "On Debian/Ubuntu: sudo apt install python3-tk")
    except ImportError as exc:
        raise GUIError(
            "tkinter is present but cannot load its Tk libraries (%s). "
            "On Debian/Ubuntu: sudo apt install python3-tk libtk8.6" % exc)
    return tkinter


def available():
    """True when a window could actually be opened here."""
    if not os.environ.get("DISPLAY") and os.name != "nt":
        return False
    try:
        _tkinter()
    except GUIError:
        return False
    return True


def describe():
    info = {"tkinter": False, "display": os.environ.get("DISPLAY") or None,
            "reason": None}
    try:
        tk = _tkinter()
        info["tkinter"] = getattr(tk, "TkVersion", True)
    except GUIError as exc:
        info["reason"] = str(exc)
        return info
    if not info["display"] and os.name != "nt":
        info["reason"] = "no DISPLAY: there is no display server to draw on"
    return info


class Node:
    """One widget in the tree. `tk` is filled in when the window is built."""

    __slots__ = ("kind", "text", "props", "children", "parent", "tk",
                 "handler", "value", "checked")

    def __init__(self, kind, text="", props=None):
        self.kind = kind
        self.text = text
        self.props = dict(props or {})
        self.children = []
        self.parent = None
        self.tk = None
        self.handler = None
        self.value = ""
        self.checked = False

    def add(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def walk(self):
        yield self
        for child in self.children:
            for node in child.walk():
                yield node


class Window(Node):
    __slots__ = ("width", "height", "title", "root")

    def __init__(self, title, width, height):
        super().__init__("window", title)
        self.title = title
        self.width = width
        self.height = height
        self.root = None


class App:
    def __init__(self, title="Silica"):
        self.title = title
        self.theme = dict(THEME)
        self.windows = []
        self.root = Node("column")
        self.running = False
        self._vm = None
        self._handlers = {}

    def window(self, title=None, width=640, height=420):
        window = Window(title or self.title, int(width), int(height))
        self.windows.append(window)
        return window

    def handlers(self):
        return self._handlers

    # -- tk construction ------------------------------------------------------
    def build(self, window):
        """Create the tk objects for a window. Needs a display."""
        tk = _tkinter()
        if not os.environ.get("DISPLAY") and os.name != "nt":
            raise GUIError(
                "no DISPLAY: a window needs a display server. "
                "Start one, or use `xvfb-run` for headless tests")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise GUIError("cannot open a window: %s" % exc)
        root.title(window.title)
        root.geometry("%dx%d" % (window.width, window.height))
        root.configure(background=self.theme.get("background", "#F3F1EC"))
        window.root = root
        window.tk = root
        for child in window.children:
            self._build_widget(child, root)
        return root

    def _build_widget(self, node, parent):
        tk = _tkinter()
        theme = self.theme
        if node.kind == "text":
            node.tk = tk.Label(parent, text=node.text,
                               background=theme.get("surface"),
                               foreground=theme.get("text"),
                               anchor="w", padx=PADDING, pady=4)
        elif node.kind == "heading":
            node.tk = tk.Label(parent, text=node.text,
                               background=theme.get("surface"),
                               foreground=theme.get("text"),
                               font=("TkDefaultFont", 14, "bold"),
                               anchor="w", padx=PADDING, pady=8)
        elif node.kind == "button":
            node.tk = tk.Button(parent, text=node.text, padx=PADDING, pady=4,
                                command=lambda n=node: self._click(n))
        elif node.kind == "field":
            node.value = node.props.get("placeholder", "")
            node.tk = tk.Entry(parent)
            node.tk.insert(0, node.value)
        elif node.kind == "checkbox":
            node.tk = tk.Checkbutton(parent, text=node.text,
                                     command=lambda n=node: self._toggle(n))
        elif node.kind == "row":
            node.tk = tk.Frame(parent, background=theme.get("surface"))
            for child in node.children:
                self._build_widget(child, node.tk)
            return
        elif node.kind == "column":
            node.tk = tk.Frame(parent, background=theme.get("surface"))
            for child in node.children:
                self._build_widget(child, node.tk)
            return
        elif node.kind == "spacer":
            node.tk = tk.Frame(parent, height=int(node.props.get("height", 8)),
                               background=theme.get("background"))
            node.tk.pack(fill="x")
            return
        else:
            raise GUIError("unknown widget kind %r" % node.kind)

        pack = {"side": "left", "padx": 4} if (
            node.parent is not None and node.parent.kind == "row") else {
            "fill": "x", "padx": PADDING, "pady": 4}
        node.tk.pack(**pack)

    # -- events ---------------------------------------------------------------
    def _click(self, node):
        if node.handler:
            self.invoke(node.handler)

    def _toggle(self, node):
        node.checked = not node.checked

    def invoke(self, name):
        """Run a Silica function by name, on a VM sharing globals and widgets."""
        vm = self._vm
        if vm is None:
            raise GUIError("no running program to call back into")
        functions = {fn.name: index for index, fn in enumerate(vm.chunk.functions)}
        if name not in functions:
            raise GUIError(
                "no Silica function named %r; handlers must be declared with sfn"
                % name)
        from ..vm import VM
        sub = VM(vm.chunk, stdin=vm.stdin, stdout=vm.stdout, stderr=vm.stderr,
                 filename=vm.filename, capabilities=vm.capabilities)
        # share state with the parent so widget handles and globals resolve
        sub._global_slots = vm._global_slots
        sub.gui_objects = getattr(vm, "gui_objects", {})
        sub.handle_counter = vm.handle_counter
        sub.run(entry=functions[name], verify=False)
        vm.handle_counter = sub.handle_counter

    def run(self, window, ticks=0):
        """Enter the event loop. `ticks` > 0 runs that many update cycles instead."""
        if window.root is None:
            self.build(window)
        window.root.update()
        if ticks:
            for _ in range(int(ticks)):
                window.root.update()
            return None
        self.running = True
        try:
            window.root.mainloop()
        finally:
            self.running = False
        return None

    def close(self, window):
        if window.root is not None:
            try:
                window.root.destroy()
            except Exception:  # pragma: no cover - already gone
                pass
            window.root = None
            window.tk = None
        return None
