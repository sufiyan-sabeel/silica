"""The web renderer: a node tree in, HTML + CSS + a small JS runtime out.

This is the only renderer that exists. Any other target is rejected with a clear
error rather than silently substituted, and the compatibility matrix in
`docs/UI.md` says so.

Layout is CSS — the renderer emits flexbox/grid declarations and lets the browser
do the work. Events are not Silica running in the browser: an event body is
lowered to a declarative JSON action list that `silica-ui-runtime.js` interprets.
Anything beyond that action table runs at build time, when the program executes,
or not at all.
"""

import base64
import html
import json
import os

from . import style
from .theme import DEFAULT_THEME, css_variables

TARGETS = ("web",)

RUNTIME_NAME = "silica-ui-runtime.js"
THEME_NAME = "theme.css"
FAVICON_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "silica-32.png")

_favicon_cache = None


def favicon_data_uri():
    """The Silica mark as a data URI, so a rendered page needs no extra file."""
    global _favicon_cache
    if _favicon_cache is None:
        try:
            with open(FAVICON_ASSET, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
        except OSError:  # pragma: no cover - only if the package data is missing
            return None
        _favicon_cache = "data:image/png;base64," + encoded
    return _favicon_cache

_VOID = {"image"}


class RenderError(ValueError):
    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


def render(app, theme=None, options=None):
    """Build the artifact files. Returns {filename: text}, keys relative to `out`."""
    options = options or {}
    target = options.get("target", "web")
    if target not in TARGETS:
        raise RenderError(
            "renderer '%s' is not implemented; available: %s"
            % (target, ", ".join(TARGETS)),
            "only the web renderer exists in UI 0.1")
    theme = theme or DEFAULT_THEME
    out = options.get("out", "index.html")
    directory = os.path.dirname(out) or "."

    builder = _Builder(theme)
    body = builder.walk(app)
    styles = "\n".join(builder.rules)
    actions_json = json.dumps(builder.actions, ensure_ascii=False, sort_keys=True)
    title = options.get("title") or "Silica UI"

    inline_css = bool(options.get("inline_css", False))
    inline_runtime = bool(options.get("inline_runtime", False))
    icon = favicon_data_uri() if options.get("favicon") else None

    files = {}
    files[os.path.basename(out)] = _document(
        title=title,
        body=body,
        styles=styles,
        actions_json=actions_json,
        theme_href=None if inline_css else THEME_NAME,
        inline_css=css_variables(theme) if inline_css else None,
        runtime_src=None if inline_runtime else RUNTIME_NAME,
        inline_runtime=RUNTIME_JS if inline_runtime else None,
        lang=options.get("language", "en"),
        icon=icon,
    )
    if not inline_css:
        files[THEME_NAME] = css_variables(theme)
    if not inline_runtime:
        files[RUNTIME_NAME] = RUNTIME_JS
    return files, directory


def write(files, directory, resolve):
    """Write rendered files, authorising each path through the capability set."""
    written = []
    for name, text in files.items():
        path = os.path.join(directory, name) if directory not in (".", "") else name
        authorised = resolve(path)
        with open(authorised, "w", encoding="utf-8") as handle:
            handle.write(text)
        written.append(authorised)
    return written


# --- tree walk ---------------------------------------------------------------
class _Builder:
    def __init__(self, theme):
        self.theme = theme
        self.rules = []
        self.actions = {}
        self.action_count = 0

    def walk(self, node):
        css_class = self._class_for(node)
        base, media = style.declarations(node.kind, node.props, css_class)
        self.rules.append(style.widget_rule(node.kind, css_class, base, media,
                                            node.props))
        if node.kind == "scroll":
            self.rules.append(style.scroll_rule(css_class, node.props))
        if node.kind == "sticky":
            self.rules.append(style.sticky_rule(css_class, node.props))
        if node.kind == "animate":
            transition, reduced = style.animation_rule(css_class, node.props)
            self.rules.append(transition)
            self.rules.append(reduced)
        if node.kind == "divider":
            self.rules.append(".%s { background: var(--si-color-border, #303741); }"
                              % css_class)

        attributes = self._attributes(node, css_class)
        tag = _TAG.get(node.kind, "div")
        if node.kind in _VOID:
            return "<%s%s>" % (tag, attributes)
        inner = self._children(node)
        if node.kind in ("text", "button"):
            inner = _text(node) + inner
        return "<%s%s>%s</%s>" % (tag, attributes, inner, tag)

    def _class_for(self, node):
        if node.css_id is None:
            node.css_id = "si-c%d" % (len(self.rules) + 1)
        return node.css_id

    def _children(self, node):
        return "".join(self.walk(child) for child in node.children)

    def _attributes(self, node, css_class):
        parts = ['class="%s"' % css_class]
        props = node.props
        if "id" in props:
            parts.append('id="%s"' % html.escape(str(props["id"]), quote=True))
        role = props.get("role") or _ROLE.get(node.kind)
        if role:
            parts.append('role="%s"' % html.escape(str(role), quote=True))
        if "aria_label" in props:
            parts.append('aria-label="%s"'
                         % html.escape(str(props["aria_label"]), quote=True))
        if props.get("hidden") is True:
            parts.append("hidden")
        if node.kind == "image":
            parts.append('src="%s"' % html.escape(str(props.get("src", "")), quote=True))
            parts.append('alt="%s"' % html.escape(str(props.get("alt", "")), quote=True))
        if node.kind == "link" and "href" in props:
            parts.append('href="%s"' % html.escape(str(props["href"]), quote=True))
        if "bind_text" in props:
            parts.append('data-si-bind-text="%s"'
                         % html.escape(str(props["bind_text"]), quote=True))
        if "bind_class" in props:
            mapping = props["bind_class"]
            parts.append('data-si-bind-class="%s"'
                         % html.escape(json.dumps(mapping, ensure_ascii=False), quote=True))
        for event, actions in sorted(node.events.items()):
            self.action_count += 1
            key = "a%d" % self.action_count
            self.actions[key] = {event: actions}
            parts.append('data-si-on-%s="%s"' % (event, key))
        return " " + " ".join(parts)


def _text(node):
    value = getattr(node, "text", None)
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


_TAG = {
    "button": "button",
    "image": "img",
    "link": "a",
    "divider": "hr",
}

_ROLE = {
    "app": "main",
    "screen": "region",
    "row": "group",
    "column": "group",
    "card": "group",
    "button": "button",
    "list": "list",
    "list_item": "listitem",
    "scroll": "region",
    "divider": "separator",
}


def _document(title, body, styles, actions_json, theme_href, inline_css,
              runtime_src, inline_runtime, lang, icon=None):
    head = [
        "<!DOCTYPE html>",
        '<html lang="%s">' % html.escape(lang, quote=True),
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % html.escape(title, quote=False),
        '<meta name="generator" content="Silica UI 0.8.0">',
    ]
    if icon:
        head.append('<link rel="icon" type="image/png" href="%s">' % icon)
    if theme_href:
        head.append('<link rel="stylesheet" href="%s">' % theme_href)
    if inline_css:
        head.append("<style>\n%s</style>" % inline_css)
    head.append("<style>\n%s\n</style>" % styles)
    head.append("</head>")
    tail = ["<body>", body,
            '<script type="application/json" id="silica-ui-actions">%s</script>'
            % actions_json]
    if runtime_src:
        tail.append('<script src="%s"></script>' % runtime_src)
    if inline_runtime:
        tail.append("<script>\n%s\n</script>" % inline_runtime)
    tail.append("</body>")
    tail.append("</html>")
    return "\n".join(head + tail) + "\n"


RUNTIME_JS = """/* silica-ui-runtime.js — generated by Silica UI.
 *
 * Silica does not run in the browser. This file interprets the declarative
 * action list that the compiler emitted for event bodies, and nothing else:
 * it sets state, applies state to bound nodes and toggles CSS classes.
 */
(function () {
  "use strict";
  var script = document.getElementById("silica-ui-actions");
  var actions = script ? JSON.parse(script.textContent || "{}") : {};
  var state = {};

  function emit(name, detail) {
    var event = new CustomEvent("silica:" + name, { detail: detail, bubbles: true });
    document.dispatchEvent(event);
  }

  function apply() {
    var nodes = document.querySelectorAll("[data-si-bind-text]");
    for (var i = 0; i < nodes.length; i++) {
      var key = nodes[i].getAttribute("data-si-bind-text");
      var value = state[key];
      nodes[i].textContent = value === undefined || value === null ? "" : String(value);
    }
    var classed = document.querySelectorAll("[data-si-bind-class]");
    for (var j = 0; j < classed.length; j++) {
      var map = JSON.parse(classed[j].getAttribute("data-si-bind-class") || "{}");
      for (var key2 in map) {
        if (!Object.prototype.hasOwnProperty.call(map, key2)) continue;
        if (state[key2]) {
          classed[j].classList.add(map[key2]);
        } else {
          classed[j].classList.remove(map[key2]);
        }
      }
    }
    document.documentElement.setAttribute("data-si-state",
      JSON.stringify(state));
    emit("state", state);
  }

  function run(list) {
    for (var i = 0; i < list.length; i++) {
      var action = list[i];
      switch (action.op) {
        case "state.set":
          state[action.key] = action.value;
          break;
        case "state.toggle":
          state[action.key] = !state[action.key];
          break;
        case "state.push":
          if (!Array.isArray(state[action.key])) state[action.key] = [];
          state[action.key].push(action.value);
          break;
        case "toggle":
          if (state[action.key]) {
            document.documentElement.classList.add(action.class_name);
          } else {
            document.documentElement.classList.remove(action.class_name);
          }
          break;
        case "navigate":
          window.location.href = action.href;
          return;
        default:
          if (window.console) {
            console.warn("silica-ui-runtime: unknown action", action.op);
          }
      }
    }
    apply();
  }

  function bind(eventName) {
    var attribute = "data-si-on-" + eventName;
    var nodes = document.querySelectorAll("[" + attribute + "]");
    for (var i = 0; i < nodes.length; i++) {
      (function (node) {
        node.addEventListener(eventName, function (evt) {
          var key = node.getAttribute(attribute);
          var entry = actions[key];
          if (!entry || !entry[eventName]) return;
          if (eventName === "submit") evt.preventDefault();
          run(entry[eventName]);
        });
      })(nodes[i]);
    }
  }

  var seen = {};
  for (var key in actions) {
    if (!Object.prototype.hasOwnProperty.call(actions, key)) continue;
    for (var eventName in actions[key]) {
      if (!Object.prototype.hasOwnProperty.call(actions[key], eventName)) continue;
      if (seen[eventName]) continue;
      seen[eventName] = true;
      bind(eventName);
    }
  }
  apply();
  window.silicaUI = { state: state, apply: apply };
})();
"""
