# Silica UI — v0.6.0

Silica UI is a set of widgets, a theme model and one renderer, written in Silica
and rendered to HTML/CSS by the web backend. This document states exactly what
exists, what does not, and how the grammar was extended to make it work.

Nothing in this document is aspirational. A target is "supported" only when an
acceptance test renders it; a reserved name fails loudly instead of pretending.

**Versioning.** The UI feature set is called "UI 0.1" and ships in **Silica
0.6.0**. The two numbers are different on purpose: Silica's version tracks the
language and toolchain, while UI 0.x tracks the rendering surface. The `.sbc`
bytecode format is still 1.0.

---

## 1. The three grammar changes

Silica 0.2.0 adds three things to the language. All three were previously a
parse error or a type error, so no 0.1.x program can change meaning — that is
the whole compatibility argument, and `tests/test_ui.py` asserts it case by case.

### G1 — dotted module paths in `use`

```ebnf
use-decl    = "use" module-path NEWLINE ;
module-path = IDENT { "." IDENT } ;
```

```silica
use ui
use ui.lib.widgets
use ui.lib.theme
```

In 0.1.0 `use ui.lib.widgets` was `parse error: unexpected '.' after statement`.

Importing a module also brings its **submodules** into scope, so `use ui` is
enough for `ui.state.set` and `ui.lib.widgets.text`. Importing only
`ui.lib.widgets` does not bring `ui` into scope.

### G2 — member-path resolution

No new syntax: the parser already accepted `a.b.c.d`. What changed is resolution.

In a chain `p₁.p₂.….pₙ`, the longest prefix that names an imported module is the
module, and exactly one segment may follow it.

```silica
use ui.lib.widgets

ui.lib.widgets.text("hello")   # module ui.lib.widgets, member text
ui.lib.widgets                 # error: a module path is not a value
ui.lib.nope.text("x")          # error: `ui.lib.widgets` is a module and only one
                               # member may follow it — did you mean to `use ui.lib.nope`?
```

In 0.1.0 anything deeper than one dot was `type error: only standard-library
modules have members`.

### G3 — builder blocks

```ebnf
stmt         = let-stmt | assign-stmt | if-stmt | while-stmt | for-stmt
             | ret-stmt | halt-stmt | builder-stmt | expr-stmt | "fin" ;

builder-stmt = postfix-expr block ;
```

Rules, precisely:

1. **Statement position only.** A builder block is never an expression; it has no
   value and cannot be nested inside one.
2. **The head must be a call.** `ui.card() { … }` yes; `x { … }` and `a + b { … }`
   are parse errors: "a builder block must follow a call".
3. **`{` must be on the same line as the closing `)`.** A newline before `{` is a
   parse error with a hint, so statement termination stays predictable.
4. **No map-literal ambiguity.** At statement position the head expression is
   already complete, so `{` can only start a builder block. Pass properties as an
   argument: `ui.text("hi", {size: "lg"})`.
5. **The callee must accept a block.** `ui.text("hi") { … }` is a type error:
   "`ui.text` does not take a block; pass properties as a map argument".
6. **Scoping.** The block opens a scope with that widget as the current parent and
   closes it at `}`. `ret` and `halt` inside a builder block are compile errors:
   a widget tree is closed structurally, so leaving one early is almost always a
   mistake and the checker can prove it.
7. **Contents are ordinary Silica** — `let`, `si`, `per`, nested builder blocks
   and calls all work inside.
8. **Nesting is unlimited**, subject to the engine's existing nesting limit.

In 0.1.0 `ui.card() { … }` was `parse error: unexpected '{' after statement`.

### What was deliberately not added

| Rejected | Why |
|---|---|
| `duration: 300ms`, `perspective: 900px` property lists | Needs new literal suffixes. Properties are maps, and `duration` is the string `"300ms"`. |
| `ui.theme "Name" { … }` | A call with a block is enough; two spellings for one thing is a bug factory. |
| `ui.scroll { … }` with no parentheses | Rule 2 requires a call. |
| Lambdas and trailing closures | Not needed; event bodies use the action subset (§5). |
| Keyword arguments | Maps cover it. |

---

## 2. Namespaces

One canonical home per name. `ui` re-exports exactly nine core primitives for
ergonomics; everything else lives in `ui.lib.widgets`.

| Module | Status | Contents |
|---|---|---|
| `ui` | implemented | `app`, `screen`, `card`, `text`, `row`, `column`, `stack`, `spacer`, `button`, plus `on`, `theme`, `set_theme`, `navigate`, `toggle`, `render` |
| `ui.state` | implemented | `set`, `toggle`, `push` — the only state actions |
| `ui.lib.widgets` | implemented | the full widget catalogue (§3) |
| `ui.lib.theme` | implemented | `token`, `contrast` |
| `ui.lib.colors` | implemented | `parse`, `blend`, `contrast` |
| `ui.lib.layout` | implemented | `breakpoint`, `breakpoints` |
| `ui.lib.scroll` | implemented | `vertical`, `horizontal` |
| `ui.lib.animation` | implemented | `transition` |
| `ui.lib.motion3d` | reserved | 3D transforms, parallax — planned for UI 0.3 |
| `ui.lib.navigation` | reserved | routing and transitions |
| `ui.lib.gestures` | reserved | drag and pinch |
| `ui.lib.accessibility` | reserved | a11y auditing helpers (semantic roles are emitted anyway) |
| `ui.lib.platform` | reserved | platform detection |
| `ui.lib.terminal` | reserved | the terminal renderer |
| `ui.lib.graphics`, `ui.lib.canvas` | reserved | immediate-mode drawing |
| `ui.lib.react`, `.flutter`, `.compose`, `.swiftui`, `.css`, `.qt` | adapter slots | always error: "no adapter installed" |

Reserved modules raise `ui.lib.motion3d is planned but not implemented (3D
transforms and parallax are planned for UI 0.3)`. Adapter slots raise `no adapter
installed for ui.lib.react; adapters are specified but not implemented`.

`ui.__end_block` is internal: the compiler emits it to close a builder scope, and
the checker refuses it in source.

---

## 3. Widgets

| Builder | Block? | Purpose |
|---|---|---|
| `ui.app(title, props?)` | yes | Document root: title, theme, language |
| `ui.screen(props?)` | yes | Top-level surface with safe-area padding |
| `ui.row(props?)`, `ui.column(props?)`, `ui.stack(props?)` | yes | Flex/grid layout primitives |
| `ui.lib.widgets.grid(props?)` | yes | CSS grid |
| `ui.card(props?)` | yes | Elevated surface |
| `ui.text(value, props?)` | no | Text node; value may be any value |
| `ui.button(label, props?)` | yes | Interactive control; takes `ui.on` children |
| `ui.lib.widgets.image(src, props?)` | no | Image; **`alt` is required** |
| `ui.lib.widgets.link(href, props?)` | yes | Anchor with child content |
| `ui.spacer(props?)` | no | Flexible gap |
| `ui.lib.widgets.divider(props?)` | no | Separator |
| `ui.lib.widgets.scroll(props?)` | yes | Scroll container |
| `ui.lib.widgets.list(items, props?)` | yes | Repeats the block per item, binding `item` |
| `ui.lib.widgets.list_item(props?)` | yes | One row inside a list |
| `ui.lib.widgets.sticky(props?)` | yes | Sticky-positioned section |
| `ui.lib.widgets.animate(props?)` | yes | Transition wrapper |
| `ui.on(event)` | yes | Event action list |

### The `item` binding

`ui.lib.widgets.list(items) { … }` binds `item` to the current element for the
duration of its block — an immutable binding of type `Any`, exactly like a `per`
loop variable. It shadows any outer `item`, and assigning to it is a compile
error.

```silica
ui.lib.widgets.list(tasks) {
    ui.lib.widgets.list_item() {
        ui.text(item)
    }
}
```

---

## 4. Properties and responsive values

Properties are map literals. Unknown keys are errors that suggest the nearest
known key (`unknown property 'padinng' for ui.card` / `did you mean 'padding'?`).

Documented vocabulary:

```
padding margin gap radius elevation background color border width height
min_width max_width align justify wrap columns size weight line_height
letter_spacing id role aria_label hidden duration easing property direction
snap physics overscroll top sticky src alt href bind_text bind_class
```

Values: lengths are Strings (`"20px"`) or numbers (treated as pixels); `size` is
`sm|md|lg|xl|xxl`; `align`/`justify` are names (`center`, `between`, …);
`elevation` is `0–4`; `duration` is a time String (`"300ms"`) because Silica has
no time literal.

Colour properties accept a semantic token (`"surface"`) or a literal
(`"#65BFA8"`). Tokens become CSS custom properties, so theme switching needs no
re-render.

A property whose value is a map keyed by breakpoint becomes a media query:

```silica
ui.screen({padding: {sm: "12px", md: "24px"}}) { … }
```

Breakpoints, defined in `ui.lib.layout`: `sm` 640px, `md` 768px, `lg` 1024px,
`xl` 1280px. An unknown breakpoint name is an error.

---

## 5. Events — the honest execution model

The browser cannot run Silica: the VM is Python-hosted and there is no JS or WASM
backend. Rather than fake it, an event body is a restricted action subset that
compiles to a declarative JSON program, which `silica-ui-runtime.js` interprets.

Allowed inside `ui.on(...) { … }` — nothing else:

| Action | Effect |
|---|---|
| `ui.state.set(key, value)` | set a state key |
| `ui.state.toggle(key)` | flip a boolean state key |
| `ui.state.push(key, value)` | append to a list state key |
| `ui.navigate(href)` | set `location.href` |
| `ui.toggle(key, class_name)` | toggle a CSS class while state is true |

Any other statement is a type error: "event bodies run in the browser; only …
are allowed in UI 0.1".

State binds back into the page declaratively:

```silica
ui.text("", {id: "status", bind_text: "status"})
ui.card({bind_class: {dark: "theme-dark"}}) { … }
```

Emitted output:

```html
<button data-si-on-click="a1">Toggle theme</button>
<script type="application/json" id="silica-ui-actions">
{"a1": {"click": [{"op": "state.toggle", "key": "dark"},
                  {"op": "state.set", "key": "status", "value": "theme changed"}]}}
</script>
<script src="silica-ui-runtime.js"></script>
```

`silica-ui-runtime.js` is dependency-free, a few kilobytes, and does nothing but
bind listeners, apply state to bound nodes and toggle classes. Anything beyond
the action table — computation, loops, network calls — runs at build time, when
the program executes, or not at all. Real client-side Silica needs a WASM build
of the VM and is not scheduled.

---

## 6. Rendering

```silica
ui.render({target: "web", out: "build/index.html"})
```

Writes three files next to `out`:

| File | Contents |
|---|---|
| the `out` path | the HTML document, including the per-node CSS rules |
| `theme.css` | `:root` custom properties, plus the reduced-motion override |
| `silica-ui-runtime.js` | the action interpreter |

Options: `target`, `out`, `inline_css`, `inline_runtime`, `language`, `favicon`.

`favicon: oui` adds `<link rel="icon">` pointing at a 32px Silica mark embedded as
a data URI, so the page keeps its icon without an extra file to copy around. It is
off by default: a rendered page is otherwise byte-identical to what 0.2.0
produced.

Rendering is explicit. A program that builds a tree and exits writes nothing.
A renderer that does not exist is rejected, never silently substituted.

**Writing needs a capability.** `ui.render` is the only UI function that touches
disk, and it requires `fs.write` for the output path — the same capability the
`fs` module uses. Without it:

```
main.sc:6: capability error: ui.render cannot write build/index.html:
capability 'fs.write' (write files) is not granted
```

The output directory must already exist; Silica does not create directories.

### Layout

The web renderer delegates box layout to CSS flexbox/grid. CSS is the layout
engine; claiming pixel parity with a hand-written layout engine would be false.
Silica computes the style model — token resolution, breakpoint media queries,
spacing scale, rem-based units — and the tests assert emitted structure and CSS
rules, not pixels.

### Scrolling and animation

`ui.lib.widgets.scroll({direction: "vertical", snap: "none"})` maps to
`overflow`, `scroll-snap-type` and `overscroll-behavior: contain`.
`ui.lib.widgets.sticky({top: "0"})` maps to `position: sticky`.
Virtualized lists are not implemented: `ui.lib.widgets.list` expands with a loop,
and the docs say so.

Animation is CSS only. Every animation also emits
`@media (prefers-reduced-motion: reduce) { transition: none; animation: none; }`,
and `theme.motion.enabled: nein` suppresses animation entirely. Pause/resume,
spring physics, gesture-driven motion and shared-element transitions are not
implemented — they need a JS animation engine, not a CSS declaration.

---

## 7. Themes

```silica
ui.theme("Silica Graphite", {
    mode: "system",
    colors: {
        background: "#0B0D10",
        surface: "#15191E",
        text_primary: "#F2F4F6",
        accent: "#65BFA8"
    },
    motion: {enabled: oui, respect_reduced_motion: oui}
})
```

`mode` is `light`, `dark` or `system`. Every colour token becomes
`--si-color-<token>`, so a theme change is a class change, not a re-render.
`ui.set_theme(mode)` switches mode at run time.

**Contrast is measured, not assumed.** Every text token is checked against
`background` and `surface`; a pair below WCAG AA (4.5:1) is an error:

```
runtime error: ui.theme: text_primary on background is 1.2:1, below AA 4.5:1
  hint: lighten text_primary or darken background
```

`ui.lib.colors.contrast(a, b)` returns the ratio for any two colours.

---

## 8. Diagnostics

| Code | Situation | Message |
|---|---|---|
| E1 | use of a reserved module | `ui.lib.motion3d is planned but not implemented (…)` |
| E2 | use of an adapter slot | `no adapter installed for ui.lib.react; adapters are specified but not implemented` |
| E3 | builder head is not a call | `a builder block must follow a call, e.g. \`ui.card() { ... }\`` |
| E4 | `{` on a new line after a call | `the block of a builder must open on the same line as the call` |
| E5 | block given to a non-block native | `\`ui.text\` does not take a block; pass properties as a map argument` |
| E6 | unknown property key | `unknown property 'padinng' for ui.card` + `did you mean 'padding'?` |
| E7 | non-action statement in an event body | `event bodies run in the browser; only ui.state.set, … are allowed in UI 0.1` |
| E8 | contrast below AA in a theme | `text_primary on background is 1.2:1, below AA 4.5:1` |
| E9 | unsupported target | `renderer 'android' is not implemented; available: web` |
| E10 | widget outside any `ui.app` | `ui.card() must be inside ui.app(...) { ... }` |
| E11 | `ret`/`halt` inside a builder block | `'ret' inside a builder block is not allowed; close the block first` |

---

## 9. Compatibility matrix

| Capability | Status |
|---|---|
| Silica UI core (tree, props, builder blocks) | implemented |
| Web renderer (HTML + CSS + runtime) | implemented |
| Theme/colour tokens, contrast validation, light/dark/system | implemented |
| Responsive layout (breakpoints, safe areas) | implemented |
| Buttons + declarative events | implemented |
| Scrolling (containers, sticky, lists) | implemented |
| Basic animation (CSS transitions, reduced motion) | implemented |
| Virtualized lists | not implemented |
| 3D / motion3d / parallax / shared elements | not implemented |
| Terminal renderer | not implemented |
| Android / iOS / desktop / OS-UI | not implemented |
| External adapters (React/Flutter/Compose/SwiftUI/Qt) | specified, not implemented |
| Client-side Silica execution (WASM) | not implemented, not scheduled |
| Pixel-identical rendering across engines | not claimed |

---

## 10. Testing

`tests/test_ui.py` covers the grammar (including the additivity proof), the
namespace rules, theme contrast, the property-to-CSS mapping, rendered markup and
events, and the honesty guarantees (reserved names never import, `web` is the
only target). The three `examples/ui_*.sc` programs are run and their artifacts
asserted in `tests/test_examples.py`.

What is *not* tested: pixels. There is no browser in the test environment, so
the markup and CSS are asserted structurally. If you want a visual check, open
`build/ui_tasks.html` from the repository root after running the example.
