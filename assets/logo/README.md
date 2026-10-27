# Silica logo assets

The Silica mark and wordmark, cropped from the supplied brand sheet. The design
and colours are the original ones — nothing here is a redrawn or replacement
logo, and nothing is a placeholder.

| File | What it is | Background |
|---|---|---|
| `silica-logo.png` | mark + "Silica" wordmark | original off-white |
| `silica-symbol.png` | the standalone mark | original off-white |
| `silica-symbol-transparent.png` | the mark, background removed | transparent |
| `silica-symbol-monochrome.png` | the single-colour mark | original off-white |
| `icons/silica-{16,24,32,48,64,128,256,512}.png` | square icons, mark centred | transparent |
| `icons/favicon.ico` | 16/32/48/64 multi-size icon | transparent |

## Colours

Sampled from the source, for anyone building a theme around the mark:

| Role | Value |
|---|---|
| Mark / wordmark | `#2B2B2B` (near-black charcoal) |
| Accent (the S inside the mark) | `#C98871` (terracotta) |
| Sheet background | `#EFEFEF` |

The Silica UI default theme uses its own palette; these are the *brand* colours,
not the UI theme tokens.

## How these were produced

Cropped from the attached sheet with the three variants isolated by their
bounding boxes, then the caption text was excluded by taking only the first ink
run in each block. The transparent version removes the flat background with a
threshold (the source has film grain, so a soft alpha ramp left speckles at icon
sizes). Icons are square canvases so the mark is never stretched.

Nothing was redrawn. If you need an SVG, it has to come from whoever owns the
original vector — tracing this bitmap would produce a new design, which the brief
explicitly rules out.

## Using them

- **README / docs**: `assets/logo/silica-logo.png` for the wordmark,
  `assets/logo/silica-symbol.png` for the mark alone.
- **Rendered Silica UI pages**: `ui.render({..., favicon: oui})` embeds a 32px
  copy (shipped inside the package as `silica/ui/assets/silica-32.png`) as a data
  URI, so the page needs no extra file.
- **Editors**: `editors/vscode/` ships the `.sc` file icon; see its README.

## Licence

The logo is part of this project and covered by the repository's MIT licence,
like everything else here.
