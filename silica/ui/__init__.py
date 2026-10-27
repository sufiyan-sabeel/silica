"""The Silica UI core: the node tree and the runtime that builds it.

A Silica program builds a tree of nodes with builder blocks::

    ui.app("Tasks") {
        ui.card() {
            ui.text("Hello")
        }
    }

Each builder block runs with its widget as the current parent, so children
attach to it. The runtime keeps that stack explicitly (`UIRuntime.stack`), and
the compiler emits a matching `ui.__end_block()` call at the closing brace to
pop it. `ret` and `halt` are rejected by the checker inside a builder block, so
a scope can never be left open.

Nothing is written to disk until `ui.render(...)` is called.
"""


class UIError(Exception):
    """Internal marker; real diagnostics are Silica errors raised by natives."""


class Node:
    """One UI node: a widget kind, its properties, children and events."""

    __slots__ = ("kind", "props", "children", "events", "line", "col", "css_id",
                 "text")

    def __init__(self, kind, props=None, line=0, col=0):
        self.kind = kind
        self.props = dict(props or {})
        self.children = []
        self.events = {}          # event name -> list of action dicts
        self.line = line
        self.col = col
        self.css_id = None
        self.text = None

    def add(self, child):
        self.children.append(child)
        return child

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Node(%s, %d children)" % (self.kind, len(self.children))


class UIRuntime:
    """Per-VM UI state: the open builder scopes, the theme and the roots."""

    __slots__ = ("stack", "roots", "app", "theme", "theme_set", "rendered",
                 "action_seq", "node_seq")

    def __init__(self):
        self.stack = []        # list of scope dicts, innermost last
        self.roots = []        # top-level nodes, in creation order
        self.app = None        # the ui.app node, once one exists
        self.theme = None      # resolved theme dict, or None for the default
        self.theme_set = False
        self.rendered = []     # paths written by ui.render
        self.action_seq = 0
        self.node_seq = 0

    # -- scopes ---------------------------------------------------------------
    def current_parent(self):
        for scope in reversed(self.stack):
            if scope["type"] == "node":
                return scope["node"]
        return None

    def push_node(self, node):
        parent = self.current_parent()
        if parent is not None:
            parent.add(node)
        else:
            self.roots.append(node)
        self.stack.append({"type": "node", "node": node})
        return node

    def push_actions(self, node, event):
        self.stack.append({"type": "actions", "node": node, "event": event,
                           "actions": []})

    def current_actions(self):
        for scope in reversed(self.stack):
            if scope["type"] == "actions":
                return scope["actions"]
        return None

    def pop_scope(self):
        if not self.stack:
            raise UIError("no open builder scope")
        scope = self.stack.pop()
        if scope["type"] == "actions":
            node = scope["node"]
            if scope["actions"]:
                node.events.setdefault(scope["event"], []).extend(scope["actions"])
        return scope

    # -- helpers --------------------------------------------------------------
    def next_node_id(self):
        self.node_seq += 1
        return "si-n%d" % self.node_seq

    def inside_app(self):
        return self.app is not None

    def reset(self):
        self.__init__()
