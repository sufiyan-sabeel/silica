# Colour

`use colors` — perceptual colour, palettes and accessibility, in the standard
library with no dependencies.

```silica
use colors

sfn main() {
    let brand = colors.oklch(0.65, 0.18, 190)
    sprint(colors.hex(brand))              # #00a59e

    let shades = colors.palette(brand)
    sprint(colors.hex(shades["500"]))

    let theme = colors.theme(brand)
    let report = colors.audit(theme)
    sprint(str(report["passes"]))          # oui
}
```

```bash
silica run examples/colors_demo.sc
```

---

## Why OKLab

sRGB and HSL are not perceptually uniform. A 10% step in HSL lightness is a large
visible jump in dark colours and an invisible one in light ones, which is why
hand-tuned palettes end up with a muddy middle. OKLab is designed so that equal
numeric steps look equally different.

Every manipulation here — lighten, darken, mix, gradient, palette generation —
happens in OKLab or OKLCH and converts back at the edges.

The visible difference: mixing red and blue.

| Method | Result |
|---|---|
| sRGB midpoint | `#7f007f` — dull, muddy |
| **OKLab midpoint** | **`#8c53a2`** — a clean purple |

---

## Colour values

A colour is a Map of four numbers in 0..1:

```silica
{"r": 0.27, "g": 0.78, "b": 0.69, "a": 1.0}
```

Nothing is stored as a hex string internally, so no precision is lost by
round-tripping through text.

### Parsing

`colors.parse` accepts `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`, `rgb()`,
`rgba()`, `hsl()`, `hsla()`, `oklch()`, `oklab()`, and CSS colour names.

```silica
colors.parse("#45c6b0")
colors.parse("rgb(69 198 176)")
colors.parse("hsl(170, 48%, 52%)")
colors.parse("oklch(0.72 0.11 178)")
```

Malformed input raises with a message naming what was expected — it does not
return black or silently drop the value.

### Construction

| Function | Notes |
|---|---|
| `colors.rgb(r, g, b, a?)` | sRGB, 0..1 each |
| `colors.oklch(l, c, h, a?)` | perceptual; **gamut-mapped, not clipped** |
| `colors.oklab(l, a, b, a?)` | as above |
| `colors.hsl(h, s, l)` | hue in degrees, rest 0..1 |

---

## Gamut

sRGB is a small box inside what human eyes can see. A request like
`oklch(0.65, 0.18, 190)` describes a colour sRGB cannot display.

There are two wrong answers and one right one:

* **Clip each channel** — silently turns a vivid teal into a different colour.
* **Pretend it worked** — the same lie with more code.
* **Map it** — keep lightness and hue, give up chroma until it fits. ✅

`colors.oklch` maps. So a request for chroma 0.18 at that lightness comes back at
chroma 0.112, and `colors.describe` will tell you so. The colour you get is the
closest one in the same hue and lightness, not a clipped approximation.

```silica
let asked = colors.oklch(0.65, 0.18, 190)
let detail = colors.describe(asked)
sprint(str(detail["oklch"][1]))    # 0.1123 — the chroma sRGB could actually show
```

Use `colors.in_gamut(c)` to test, and `colors.to_gamut(c)` to map a colour you
constructed another way.

### Display P3

`colors.to_p3` and `colors.from_p3` convert through XYZ. sRGB always fits inside
P3, so that direction is lossless; P3 to sRGB may land outside the sRGB gamut and
is reported rather than clipped.

**This is not HDR.** There are no PQ or HLG transfer functions, no luminance
metadata, and no backend that could use them. Saying otherwise would be false.

---

## Palettes

`colors.palette(base)` produces the conventional scale — `50` to `950` — from one
colour.

Each step has a perceptual lightness target, and chroma is scaled down at the
extremes where a saturated colour cannot fit at that lightness. Generation is
deterministic: the same base always produces the same scale.

```silica
let shades = colors.palette(brand)
per step in ["50", "500", "950"] {
    sprint(step + "  " + colors.hex(shades[step]))
}
```

Keys are strings, because a Silica Map is keyed by String.

A custom set of steps is allowed: `colors.palette(brand, [100, 500, 900])`.

**Not claimed:** that equal lightness spacing guarantees equal perceptual
quality. It gives an even *lightness* ramp, which is a real improvement, and no
more than that.

---

## Themes and semantic tokens

```silica
let theme = colors.theme(brand)          # dark by default
let light = colors.theme(brand, nein)    # light
```

Tokens: `background`, `surface`, `elevated`, `border`, `text`, `muted`, `accent`,
`accent_hover`, `success`, `warning`, `error`, `on_accent`, `on_background`.

`on_accent` is chosen by contrast against `accent`, not by taking the lightest
step of the scale — which is the usual way this goes wrong.

### Auditing a theme

```silica
let report = colors.audit(theme)
per check in report["checks"] {
    sprint(check["pair"] + "  " + str(check["ratio"]))
}
sprint(str(report["passes"]))
```

Each check reports the ratio, the threshold and a verdict. The pairs checked are
text on background, text on surface, muted on background, on_accent on accent, and
on_background on background.

### CSS

```silica
sprint(colors.css_theme(theme))            # --silica-background: ...;
sprint(colors.css_scale("brand", shades))  # --silica-brand-500: #009e98;
```

---

## Accessibility

| Function | Purpose |
|---|---|
| `colors.contrast(a, b)` | WCAG ratio, 1.0 to 21.0 |
| `colors.passes(a, b, level?, large?)` | AA (4.5) or AAA (7.0); 3.0 for large text |
| `colors.best_foreground(bg)` | the more readable of black or white |
| `colors.luminance(c)` | WCAG relative luminance |

Known values the tests check: black on white is exactly 21.0, and `#777777` on
white is 4.48 — which **fails** AA, as it should. That pair is the classic
borderline case, and it is in the suite precisely because it is easy to get wrong.

**APCA is not implemented.** It has its own licence terms and versioned
constants, and I have not verified them. Calling an approximation "APCA" would be
worse than not having it.

---

## Reference values

The OKLab conversions are checked against published values from the
specification, not against numbers read back out of this implementation:

| Colour | L | a | b |
|---|---|---|---|
| `#ffffff` | 1.0000 | 0.0000 | 0.0000 |
| `#ff0000` | 0.6279 | 0.2249 | 0.1258 |
| `#00ff00` | 0.8664 | −0.2339 | 0.1795 |
| `#0000ff` | 0.4520 | −0.0324 | −0.3115 |

The suite also checks that a round trip sRGB → OKLCH → sRGB is exact at 8-bit for
a spread of colours, which catches matrix and transfer-function mistakes that a
single vector would miss.

---

## Limits

* **No HDR.** See above.
* **Gamut mapping is one documented algorithm**, not the only correct one. It
  preserves lightness and hue and reduces chroma.
* **Chroma below 0.001 is treated as zero** — that is matrix round-off, not a
  colour.
* **The gamut tolerance is 0.002 of a channel**, about half an 8-bit step,
  because a round trip through two matrix chains lands pure blue at 1.0002.
  Genuine gamut violations are far larger and are not hidden by it.
* **No ICC profiles, no colour management.** This is sRGB and P3 maths.
* **Not wired into the TUI or GUI yet** — `colors` produces values; the TUI has
  its own hex theme tokens and the GUI its own. Connecting them is the next step,
  not something this release claims.
