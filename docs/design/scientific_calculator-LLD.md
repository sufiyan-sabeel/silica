# scientific_calculator — low-level design

Status: **design for review — not implemented.**
Target: a self-contained HTML page opened in Chrome on Android.
Capabilities: **`fs.read`, `fs.write`** — scoped to the `build/` directory.

## 0. Read this first: what "Android application" can and cannot mean

Silica has no Android runtime, no APK packaging and no native UI toolkit. **This
will not be an installable Android app.** It is an HTML page that Silica generates,
opened in Chrome on the phone; it looks and behaves like an app, and it can be added
to the home screen, but it is a web page.

There is a second honesty point, and it is the one that shapes the whole design.
The UI runtime says so itself:

> *"Silica does not run in the browser. This file interprets the declarative action
> list that the compiler emitted for event bodies, and nothing else: it sets state,
> applies state to bound nodes and toggles CSS classes."*

The action model offers exactly `state.set`, `state.toggle`, `state.push`, CSS class
toggles and `navigate`. **There is no arithmetic and no way to call a Silica function
from a click.** So a calculator that computes cannot be built from `ui.on("click")`
alone.

The design therefore splits the work honestly:

| Layer | Written in | Runs where |
|---|---|---|
| Layout, widgets, theme, palette | **Silica** | at build time, in the Silica VM |
| Colour maths, contrast checks, CSS | **Silica** (`colors`) | at build time |
| The calculator engine (arithmetic, state, keyboard, history) | **JavaScript**, emitted by Silica as a string and injected into the page | in Chrome, when a key is pressed |

Silica generates the entire page — structure, styling, palette, and the engine
source — but the arithmetic executes in JavaScript. Any claim that "the calculator
logic runs in Silica" would be false, and the page itself will carry a comment
saying so.

## 1. Overview and scope

A scientific calculator for a phone browser: big readable display, an amber-on-black
keypad in the style of the iOS calculator, scientific functions, a history tape, and
full keyboard support so it is usable on a desktop too.

In scope:

- `+ − × ÷`, decimal entry, `±`, `%`, `AC`, backspace
- scientific: `√`, `x²`, `1/x`, `xʸ`, `π`, `e`, and `log`/`ln`
- a history tape of the last 20 evaluated expressions, newest first
- keyboard: digits, `+ - * /`, `Enter`, `Backspace`, `Escape`, `.`, `%`, `^`
- light and dark, both derived from one base colour and contrast-checked
- one output file, no network, no dependencies

Out of scope: memory registers (M+/MR/MC) — deferred, not rejected, because they add
state that the tape already partly covers; trigonometry (needs degree/radian modes
and precision decisions); unit conversion; graphing; installable PWA manifest.

Users: someone who wants a calculator that looks right on a phone and works offline.

## 2. Architecture and component breakdown

Two stages, both driven by one Silica program.

```
stage 1 — Silica, at build time
  palette.sc:  base colour → oklab shades → contrast checks → theme map
  layout.sc:   theme + widgets → ui.app/screen/row/column/card/text/button
  ui.render({"target": "web", "out": "build/calculator.html"})

stage 2 — Silica, still at build time
  engine.js   (a Silica String constant: the calculator)
  glue.js     (a Silica String constant: binds every button to the engine)
  inject:      fs.read_text(calculator.html)
               → insert <script> before </body>
               → fs.write_text(calculator.html)

stage 3 — Chrome, when the user taps
  engine evaluates the expression, updates the display and the tape
```

The buttons are rendered by Silica with stable `id`s (`key-7`, `key-plus`,
`key-ac`…). The glue script finds them by id and attaches handlers. Nothing about
the arithmetic lives in the Silica source except as text.

Why injection rather than a second `ui.render` pass: the renderer has no hook for
arbitrary script, and inventing one would mean changing the runtime. Appending a
`<script>` block to the rendered file is a smaller, testable step that touches no
existing behaviour.

## 3. Module and file structure

| File | Role |
|---|---|
| `examples/scientific_calculator.sc` | the whole application: palette, layout, engine source, injection |
| `build/calculator.html` | the output, self-contained |
| `tests/test_calculator_app.py` | structure, palette contrast, and engine behaviour |
| `docs/design/scientific_calculator-LLD.md` | this document |

Imports: `ui`, `ui.lib.widgets`, `colors`, `string`, `fs`.

Keeping it to one `.sc` file is deliberate: the program is the design, and splitting
the palette out would only help if a second application needed it — at which point it
becomes `silica/lib/palette.sc` in the standard library instead, not an example.

## 4. Data models and data flow

### Theme map (built by Silica)

| Key | Source |
|---|---|
| `background` | near-black base, `#0B0B0C` |
| `surface` | `colors.lighten(base, 0.06)` |
| `surface_variant` | `colors.lighten(base, 0.12)` — number keys |
| `text_primary` | `colors.best_foreground(background).hex` |
| `text_secondary` | primary mixed 60% toward the background |
| `accent` | amber `#FF9F0A`, the operator keys |
| `accent_text` | `colors.best_foreground(accent).hex` |
| `error` | a red that passes AA on `surface` |

Colours cross the boundary as maps `{r, g, b, a}` in 0..1, which is what `colors`
expects; hex strings are produced with `colors.hex` for CSS.

### Engine state (JavaScript, in the page)

| Name | Type | Meaning |
|---|---|---|
| `entry` | string | the digits being typed, `""` when a result is showing |
| `expression` | string | the pending expression, e.g. `12+4×` |
| `lastResult` | number | the previous result, for `Ans`-style chaining |
| `history` | array | up to 20 `{expression, result}` records |
| `error` | boolean | display shows `Error` until `AC` |

Data flow on a key press: `key → handler → mutate entry/expression → render()`, where
`render()` writes the display text and rebuilds the tape. The DOM is never rebuilt
wholesale; only the display node and the tape list are updated.

## 5. Function signatures and responsibilities

### Silica

| Function | Signature | Responsibility |
|---|---|---|
| `shade` | `(base: Map, amount: Float) -> Map` | lighten or darken in OKLab so the ramp is perceptually even |
| `ensure_contrast` | `(fg: Map, bg: Map, minimum: Float) -> Map` | return `fg`, or a lightened/darkened variant that reaches the ratio |
| `build_theme` | `(base: Map) -> Map` | the theme map above, every pair contrast-checked |
| `key_button` | `(label: String, id: String, kind: String)` | one keypad button with the right variant |
| `keypad` | `(rows: List) -> Unit` | the grid, from a row/label description |
| `engine_source` | `() -> String` | the calculator JavaScript |
| `glue_source` | `() -> String` | the button-binding JavaScript |
| `inject` | `(path: String, script: String)` | insert before `</body>`, fail loudly if the marker is absent |
| `main` | `() -> Unit` | palette → layout → render → inject |

`ensure_contrast` is the piece that makes the colour library load-bearing rather than
decorative: it is what guarantees the amber on black, and the black on amber, both
reach at least 4.5:1.

### JavaScript engine

| Function | Responsibility |
|---|---|
| `press(key)` | the single entry point every button and key event calls |
| `applyOperator(op)` | fold the pending operation using precedence for `× ÷` over `+ −` |
| `applyFunction(fn)` | immediate unary: `√`, `x²`, `1/x`, `log`, `ln` |
| `evaluate(expression)` | produce a number, or `null` on a domain error |
| `format(value)` | up to 12 significant digits, trailing zeros stripped, `e` notation past ±1e12 |
| `render()` | write the display and the tape |
| `onKeyDown(event)` | map a physical key to `press` |

## 6. UI/UX structure

Portrait, phone-first, single column, sized with `clamp()` so it fills a phone screen
and still looks right on a laptop.

```
┌─────────────────────────────┐
│ 12 + 4 ×                    │  ← expression, small, secondary
│                        56   │  ← display, huge, right-aligned
├─────────────────────────────┤
│ AC   ±   %   ⌫   ÷          │  ← utility row: grey; ÷ amber
│ 7    8   9   √   ×          │
│ 4    5   6   x²   −         │
│ 1    2   3   1/x  +         │
│ 0    .   π   =    =         │
├─────────────────────────────┤
│ history                     │
│ 12×4 = 48                   │
│ 48+8 = 56                   │
└─────────────────────────────┘
```

- Numbers: `surface_variant` on near-black, white text, 1.4:1 separation from the
  background is not enough on its own, so keys also carry a subtle top border.
- Operators: amber background, near-black text — `best_foreground(accent)` decides
  which, rather than assuming white is readable on amber.
- `=` spans two rows, iOS-style.
- The display right-aligns and shrinks its font step when the number is long.
- The tape is the newest-first list, scrollable, each row `expression = result`.
- Tapping a tape row loads that result into the display.
- Dark is default; a light theme is generated from the same base by inverting the
  ramp, not by hand-picking colours.

## 7. Error handling and validation

Silica has no exceptions and the engine is JavaScript, so every failure is an
explicit branch in both layers.

| Condition | Behaviour |
|---|---|
| division by zero | display `Error`, tape records the attempt, `AC` clears |
| `√` of a negative | `Error` |
| `log`/`ln` of a non-positive number | `Error` |
| result not finite (`Infinity`, `NaN`) | `Error` |
| digit typed after `=` | starts a new entry |
| operator typed twice | the second replaces the first |
| backspace on an empty entry | no-op, no crash |
| expression longer than the display | font steps down, then the display scrolls |
| injection marker `</body>` absent | `inject` fails with the path and a hint — never writes a half-modified file |
| `ui.render` target directory missing | the program reports it; Silica does not create directories |

The `inject` failure is the important one: a silently un-injected page would look
correct and do nothing when tapped, which is worse than a build error.

## 8. Security and capability requirements

Requires `fs.read` and `fs.write`, scoped to `build/`:

```bash
silica run --allow-fs-read build --allow-fs-write build examples/scientific_calculator.sc
```

`ui.render` writes its output through the renderer; the injection step reads that
file back and writes it again, which is why the `fs` capability is needed and why the
grant is narrowed to `build/` rather than `.`.

The generated page has **no network access**: no `fetch`, no external stylesheet, no
remote font, no analytics. Everything is inline, so it works offline and cannot leak
anything. The engine uses no `eval` and no `new Function` — the expression parser is
a small hand-written evaluator over a token array, because `eval` on user-typed input
in a page you might add to a home screen is exactly the wrong habit to build into an
example.

No input from the page reaches Silica, and no Silica value is built from page content.

## 9. Dependencies and external integrations

| Dependency | Kind | Notes |
|---|---|---|
| `ui` | Silica stdlib | `theme`, `app`, `screen`, `row`, `column`, `card`, `text`, `button`, `on`, `render` |
| `ui.lib.widgets` | Silica stdlib | `scroll` for the tape |
| `colors` | Silica stdlib | `hex`, `lighten`, `darken`, `mix`, `oklab`, `contrast`, `passes`, `best_foreground`, `css_theme` |
| `fs` | Silica stdlib | `read_text`, `write_text`, `exists` |
| `string` | Silica stdlib | `contains`, `replace` for the injection |
| Chrome (Android) | browser | the only runtime requirement on the phone |

No third-party packages. No CDN. No build step beyond running the `.sc` file.

## 10. Testing strategy and acceptance criteria

Three layers, all runnable without a browser.

**1. Structure** — run the program, then parse `build/calculator.html` with Python's
`html.parser`:

- the file exists and is self-contained: no `http://` or `https://` references
- every keypad id is present exactly once
- the engine and glue scripts are present exactly once (no double injection on a
  second run)
- the display and tape nodes carry the ids the glue script binds

**2. Palette** — assert with `silica.ui.color`, not by eye:

- `contrast(text_primary, background) >= 4.5`
- `contrast(accent_text, accent) >= 4.5`
- every theme pair passes AA
- light and dark are both generated and both pass

**3. Engine** — extract the injected script and run it under **Node** (preinstalled
in CI and in this sandbox), feeding key sequences and asserting the display:

| Input | Expected display |
|---|---|
| `1 2 + 4 × 3 =` | `24` — precedence: `×` binds before `+` |
| `9 √` | `3` |
| `5 ÷ 0 =` | `Error` |
| `2 ^ 10 =` | `1024` |
| `50 %` | `0.5` |
| `AC` after an error | `0` |
| `1 2 ⌫` | `1` |
| `π` then `× 2 =` | `6.283185307` |
| twelve digits then more | the display shrinks, the value is unchanged |
| `0 . 1 + 0 . 2 =` | `0.3`, not `0.30000000000000004` |

That last one matters: formatting is what separates a calculator from a
floating-point demo.

Acceptance criteria: the three layers pass; the page opens offline in a phone-sized
viewport with no console errors; every button produces the same result as its
keyboard equivalent.

## 11. Implementation phases

1. **Palette** — `shade`, `ensure_contrast`, `build_theme`, with the contrast tests
   written first so the colours are proven before any layout exists.
2. **Layout** — the display, the five-row keypad, the tape container; render and
   check the structure tests.
3. **Engine** — the JavaScript evaluator and formatter, developed against the Node
   harness so arithmetic is proven before it is wired to buttons.
4. **Injection** — `inject`, with the idempotence test (run twice, one script block)
   and the missing-marker failure.
5. **Glue and keyboard** — bind every id, map physical keys, verify a button and its
   key produce identical results.
6. **History tape** — record, render newest-first, tap to reuse.
7. **Light theme** — generate from the same base, re-run the contrast suite.
8. **Docs** — `docs/APPLICATIONS.md` entry, design status updated to implemented,
   deviations recorded here.

Each phase ends with its tests passing; the design is updated if a phase reveals a
genuine change, and the deviation is recorded below.

## Deviations

None yet — implementation has not started.

## Limitations

- **Not an Android app.** An HTML file opened in Chrome. No APK, no Play Store, no
  native widgets.
- **The arithmetic is JavaScript**, not Silica. Silica generates the page and the
  engine source; it does not execute the calculation.
- No trigonometry, no memory registers, no unit conversion.
- Single file output: there is no bundler, so the page grows with the engine — fine
  at roughly 30 KB, not a framework.
- Requires a browser. If Chrome is unavailable, nothing works; the TUI calculator
  (`examples/tui_calculator.sc`) is the terminal alternative.
