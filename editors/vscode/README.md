# Silica for VS Code

Gives `.sc` files the Silica file icon in the explorer, the open-editors list and
editor tabs, plus syntax highlighting for the language.

## Why this exists

The Silica repository is a language toolchain: a CLI, a compiler and a VM. It has
no editor, no file explorer and no file-icon system of its own — there is nothing
in it for a file icon to attach to. VS Code is the one surface that *does* have
explorer icons, tabs and open-file lists, and it is where `.sc` files are actually
opened, so the file-icon work lives here.

This is a new sub-project, not an integration into an existing Silica editor.
Nothing in the main repository changed behaviour to accommodate it.

## What it contributes

| Contribution | Effect |
|---|---|
| `languages` | registers the `silica` language for the `.sc` extension |
| `grammars` | TextMate grammar, scope `source.silica`, for syntax highlighting |
| `iconThemes` | `Silica File Icons`, which maps `.sc` to the Silica mark |

The grammar covers the whole keyword vocabulary the lexer defines; a test in the
main repository fails if a keyword or built-in type is added to `silica/tokens.py`
and the grammar is not updated with it.

The mark is near-black, which is invisible on a dark editor background, so the
theme ships two monochrome silhouettes of the same shape: a light one used by
default (dark themes) and a dark one wired into the theme's `light` section
(light themes). Both are generated from the supplied mark — the geometry is
unchanged, only the fill colour differs, which is what makes a file icon legible
at 16px on either background.

The file icon theme is contributed through `contributes.iconThemes` — the point
VS Code documents for file icon themes. `fileIconThemes` does not exist, and using
it fails silently: the manifest loads and the theme is simply never offered. There
is a test for that too.

## Install

**From this folder** (development):

```bash
cd editors/vscode
npm install -g @vscode/vsce        # once
vsce package                        # produces silica-language-0.2.0.vsix
code --install-extension silica-language-0.2.0.vsix
```

**From a checkout, without packaging**: open VS Code, press `F5` in this folder to
launch an Extension Development Host, then open any `.sc` file.

## Turn the file icon on

VS Code does not apply a file icon theme automatically:

1. `Ctrl+Shift+P` (or `Cmd+Shift+P`) → **Preferences: File Icon Theme**
2. Choose **Silica File Icons**

`.sc` files now show the Silica mark. The setting is per-workspace if you set it
from a workspace.

## The one caveat, stated plainly

A file icon theme is **all or nothing**. Enabling "Silica File Icons" replaces
whatever icon theme you were using, and files this theme does not map fall back to
VS Code's built-in icons rather than to your previous theme's icons. That is how
the VS Code contribution point works; there is no way to contribute icons for a
single extension without owning the theme.

If you want Silica's icon *inside* your existing theme, copy the entry instead:

```jsonc
// your-theme.json
"iconDefinitions": { "_silica": { "iconPath": "./icons/silica-symbol.png" } },
"fileExtensions": { "sc": "_silica" }
```

## What is not here

- No language server, completion, hover or diagnostics. `silica check` exists in
  the main repository; wiring it to an LSP is separate work and is not claimed.
- No icon for the `silica.toml` manifest — the brief covers `.sc` only.
- No build, debug or task integration.

## Verified

`tests/test_assets.py` in the repository root checks that the manifest is valid
JSON, that `.sc` is registered, that every path it names resolves, that the icon
theme maps `sc` to an icon file that exists, and that the grammar covers every
keyword and type in the lexer.

What that cannot check is how the icon *looks* in the explorer — that needs an
editor. Run it and look.
