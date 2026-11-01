# Silica Standard Library — v0.4.0

`core` is always in scope. Every other module must be imported with `use`.
Each entry lists its signature, what it returns, and when it raises a runtime
error. `Any` means "any Silica value".

Runtime errors are reported with `file:line:column` and abort the program.

---

## core (no import needed)

### `sprint(value: Any) -> Unit`
Writes `value` to stdout followed by a newline.

```
sprint(42)          # 42
sprint("text")      # text
sprint([1, 2])      # [1, 2]
```

### `dit(value: Any) -> Unit`
Writes `value` to stdout with no trailing newline. Use it for prompts and for
building one line from several pieces.

```
dit("total: ")
dit(41 + 1)
sprint("")          # total: 42
```

### `input(prompt: String) -> String`
Writes `prompt` (no newline added), flushes, then reads one line from stdin and
returns it without the trailing line ending.

```
let name: String = input("name? ")
```

Error: `input reached end of input` when stdin is exhausted.

### `type_of(value: Any) -> String`
Returns `"Int"`, `"Float"`, `"Bool"`, `"String"`, `"Unit"`, `"List"` or `"Map"`.

### `assert(condition: Bool, message: String?) -> Unit`
Raises a runtime error when `condition` is `nein`. The optional message is
appended to the error. This is what `silica test` uses.

```
assert(1 + 1 == 2)
assert(len(xs) > 0, "list must not be empty")
```

### `str(value: Any) -> String`
Converts any value to its `sprint` representation.

### `int(value: String | Float | Int) -> Int`
Parses or truncates toward zero. Error: `cannot convert "x" to Int`, or a Float
that is `nan`/`inf`.

### `float(value: String | Int | Float) -> Float`
Parses or widens. Error: `cannot convert "x" to Float`.

### `len(value: List | Map | String) -> Int`
Number of elements, entries or characters. Error for any other type.

### `range(stop: Int) -> List` · `range(start: Int, stop: Int) -> List` · `range(start: Int, stop: Int, step: Int) -> List`
Builds a list of integers, like Python's `range` but eager.
Error: `range step must not be zero`.

```
range(3)            # [0, 1, 2]
range(2, 5)         # [2, 3, 4]
range(0, 10, 3)     # [0, 3, 6, 9]
```

### `push(list: List, value: Any) -> Unit`
Appends in place. Lists are mutable and shared, so the caller sees the change.

### `keys(map: Map) -> List` / `values(map: Map) -> List`
Keys in insertion order; values in the same order.

### `has(container: List | Map | String, key: Any) -> Bool`
`Map` → key present; `List` → value present (structural equality); `String` →
substring present.

---

## math — `use math`

| Function | Signature | Notes |
|---|---|---|
| `math.abs` | `(Int \| Float) -> Int \| Float` | Same numeric type as the argument. |
| `math.min` | `(Int \| Float, Int \| Float) -> Int \| Float` | Promotes to `Float` if either side is one. |
| `math.max` | `(Int \| Float, Int \| Float) -> Int \| Float` | As above. |
| `math.sqrt` | `(Int \| Float) -> Float` | Error on a negative argument. |
| `math.pow` | `(Int \| Float, Int \| Float) -> Float` | Always `Float`. |
| `math.floor` | `(Int \| Float) -> Int` | Error for `nan`/`inf`. |
| `math.ceil` | `(Int \| Float) -> Int` | Error for `nan`/`inf`. |
| `math.round` | `(Int \| Float) -> Int` | Half away from zero: `2.5 -> 3`, `-2.5 -> -3`. |

Constants: `math.pi`, `math.e`, `math.tau` (all `Float`).

```
use math
sfn main() {
    sprint(math.sqrt(81.0))   # 9.0
    sprint(math.round(2.5))   # 3
    sprint(math.pi)           # 3.141592653589793
}
```

---

## string — `use string`

| Function | Signature | Notes |
|---|---|---|
| `string.split` | `(String, String) -> List` | Error on an empty separator. |
| `string.join` | `(List, String) -> String` | Error unless every element is a `String`. |
| `string.trim` | `(String) -> String` | Strips leading/trailing whitespace. |
| `string.replace` | `(String, String, String) -> String` | Error on an empty search string. |
| `string.contains` | `(String, String) -> Bool` | Substring test. |
| `string.starts_with` | `(String, String) -> Bool` | |
| `string.ends_with` | `(String, String) -> Bool` | |
| `string.upper` | `(String) -> String` | |
| `string.lower` | `(String) -> String` | |

Strings are immutable; every function returns a new string. Indexing a string
(`s[i]`) yields a one-character `String`; out-of-range indices are errors.

---

## collections — `use collections`

| Function | Signature | Notes |
|---|---|---|
| `collections.sort` | `(List) -> List` | New sorted list. Elements must be all `Int`, all `Float` or all `String`; mixed types are an error. |
| `collections.reverse` | `(List) -> List` | New reversed list. |
| `collections.index_of` | `(List, Any) -> Int` | `-1` when absent. |
| `collections.sum` | `(List) -> Int \| Float` | Numeric elements only; `Float` if any element is a `Float`. |

Sorting and reversing do not mutate the input.

---

## fs — `use fs` (requires a capability)

`fs` is the only module that touches the machine, and every function in it
requires an explicit capability grant. **Nothing is granted by default**: a
program run without flags gets a capability error, not a file.

| Function | Signature | Capability | Notes |
|---|---|---|---|
| `fs.read_text` | `(String) -> String` | `fs.read` | Whole file as UTF-8 text. Errors on a missing file, a directory, or bytes that are not UTF-8. |
| `fs.write_text` | `(String, String) -> Unit` | `fs.write` | Creates or overwrites. The parent directory must already exist; Silica does not create directories. |
| `fs.exists` | `(String) -> Bool` | `fs.read` | `nein` for a missing path rather than an error. Requires `fs.read` because existence is itself information. |
| `fs.list_dir` | `(String) -> List` | `fs.list` | Entry names, sorted. Not recursive. Errors on a file or a missing directory. |

Paths are resolved against the working directory, symlinks are resolved before
the check, and a path is only allowed when it lands inside a granted root. So
`--allow-fs-read data` does not permit `data/../secret` and does not permit a
symlink inside `data` that points outside it.

```bash
silica run examples/fs_demo.sc --allow-fs-read examples --allow-fs-list examples
```

Errors are ordinary located runtime errors:

```
examples/fs_demo.sc:5: capability error: capability 'fs.read' (read files) is not granted
  hint: grant it with --allow-fs-read <dir>; Silica grants nothing by default
```

---

## json — `use json`

| Function | Signature | Notes |
|---|---|---|
| `json.parse` | `(String) -> Any` | Returns the value the document describes. Errors report line and column. |
| `json.stringify` | `(Any) -> String` | Compact form: `{"a":1,"b":[1,2]}`. |
| `json.stringify` | `(Any, Int) -> String` | Pretty form with that many spaces per level (0–8; 0 means compact). |

Mapping between JSON and Silica values:

| JSON | Silica |
|---|---|
| `null` | `Unit` |
| `true` / `false` | `Bool` (`oui` / `nein`) |
| whole number in 64-bit range | `Int` |
| any other number | `Float` |
| string | `String` (UTF-8, escapes decoded) |
| array | `List` |
| object | `Map` with `String` keys |

Stated rules rather than guesses:

* `NaN`, `Infinity` and `-Infinity` are rejected — they are not JSON.
* An integer outside signed 64-bit range is an error, not a silent wrap.
* A duplicate object key keeps the **last** value.
* `json.stringify` refuses a `Map` whose keys are not `String`, and refuses
  values with no JSON form (an `Iterator`), and never emits `NaN`.
* `json.parse` reports `invalid JSON at line L column C: <reason>` with a hint
  showing the offending line and a caret.

```silica
use json

sfn main() {
    let doc = json.parse("{\"name\": \"silica\", \"nums\": [1, 2.5]}")
    sprint(json.stringify(doc))       # {"name":"silica","nums":[1,2.5]}
    sprint(json.stringify(doc, 2))    # two-space indented
}
```

---

## gui, gui.lib.widgets, gui.lib.layout, gui.lib.theme — desktop windows

Real windows through tkinter. Opening a window and running an event loop
needs the `gui.run` capability (`--allow-gui`); building the widget tree
needs nothing, so a program can be inspected on a headless machine.
Full guide: `docs/GUI.md`.

| Function | Signature | Notes |
|---|---|---|
| `gui.add` | (Any, Any) -> Unit | attach a widget to a window or container |
| `gui.app` | (String?) -> Any | create the application |
| `gui.button` | (String) -> Any | a button; wire it with gui.on_click |
| `gui.checkbox` | (String) -> Any | a toggle with a label |
| `gui.click` | (Any) -> Unit | activate a button the way a user would |
| `gui.close` | (Any) -> Unit | destroy the window |
| `gui.column` | () -> Any | children stacked |
| `gui.field` | (String?) -> Any | a single-line text entry |
| `gui.heading` | (String) -> Any | a larger bold label |
| `gui.on_click` | (Any, String) -> Unit | run a Silica function, by name, when pressed |
| `gui.row` | () -> Any | children laid out side by side |
| `gui.run` | (Any, Int?) -> Unit | enter the event loop; with a tick count, run that many cycles |
| `gui.set_text` | (Any, String) -> Unit | change a widget's text |
| `gui.set_value` | (Any, String) -> Unit | set a field's contents |
| `gui.show` | (Any) -> Unit | create the real window (needs gui.run) |
| `gui.spacer` | (Int?) -> Any | vertical gap |
| `gui.status` | () -> Map | whether tkinter and a display are available |
| `gui.text` | (String) -> Any | a label |
| `gui.theme` | (Any, Map) -> Unit | override colour tokens |
| `gui.value` | (Any) -> Any | read a widget's text, field contents or checked state |
| `gui.widgets` | (Any) -> List | the kinds of a container's children |
| `gui.window` | (Any, String?, Int?, Int?) -> Any | create a window (title, width, height) |
| `gui.lib.widgets.add` | (Any, Any) -> Unit | attach a widget to a window or container |
| `gui.lib.widgets.app` | (String?) -> Any | create the application |
| `gui.lib.widgets.button` | (String) -> Any | a button; wire it with gui.on_click |
| `gui.lib.widgets.checkbox` | (String) -> Any | a toggle with a label |
| `gui.lib.widgets.click` | (Any) -> Unit | activate a button the way a user would |
| `gui.lib.widgets.close` | (Any) -> Unit | destroy the window |
| `gui.lib.widgets.column` | () -> Any | children stacked |
| `gui.lib.widgets.field` | (String?) -> Any | a single-line text entry |
| `gui.lib.widgets.heading` | (String) -> Any | a larger bold label |
| `gui.lib.widgets.on_click` | (Any, String) -> Unit | run a Silica function, by name, when pressed |
| `gui.lib.widgets.row` | () -> Any | children laid out side by side |
| `gui.lib.widgets.run` | (Any, Int?) -> Unit | enter the event loop; with a tick count, run that many cycles |
| `gui.lib.widgets.set_text` | (Any, String) -> Unit | change a widget's text |
| `gui.lib.widgets.set_value` | (Any, String) -> Unit | set a field's contents |
| `gui.lib.widgets.show` | (Any) -> Unit | create the real window (needs gui.run) |
| `gui.lib.widgets.spacer` | (Int?) -> Any | vertical gap |
| `gui.lib.widgets.status` | () -> Map | whether tkinter and a display are available |
| `gui.lib.widgets.text` | (String) -> Any | a label |
| `gui.lib.widgets.theme` | (Any, Map) -> Unit | override colour tokens |
| `gui.lib.widgets.value` | (Any) -> Any | read a widget's text, field contents or checked state |
| `gui.lib.widgets.widgets` | (Any) -> List | the kinds of a container's children |
| `gui.lib.widgets.window` | (Any, String?, Int?, Int?) -> Any | create a window (title, width, height) |
| `gui.lib.layout.add` | (Any, Any) -> Unit | attach a widget to a window or container |
| `gui.lib.layout.column` | () -> Any | children stacked |
| `gui.lib.layout.row` | () -> Any | children laid out side by side |
| `gui.lib.layout.spacer` | (Int?) -> Any | vertical gap |
| `gui.lib.theme.status` | () -> Map | whether tkinter and a display are available |
| `gui.lib.theme.theme` | (Any, Map) -> Unit | override colour tokens |

---

## tui, tui.lib.widgets, tui.lib.layout, tui.lib.style — terminal UI

Real terminal applications on curses. `tui` holds the whole API; the
`tui.lib.*` modules re-export parts of it so the documented imports resolve
to real functions. Drawing to the screen needs the `tui.run` capability
(`--allow-tui`). The full guide is `docs/TUI.md`.

| Function | Signature | Notes |
|---|---|---|
| `tui.add` | (Any, Any) -> Unit | attach a widget to a container |
| `tui.app` | (String) -> Any | create an application |
| `tui.button` | (String) -> Any | focusable button |
| `tui.close` | (Any) -> Unit | restore the terminal |
| `tui.column` | () -> Any | children stacked (the default) |
| `tui.divider` | () -> Any | horizontal rule across the width |
| `tui.field` | (String) -> Any | editable single-line field (`input` is a keyword) |
| `tui.heading` | (String) -> Any | one line, rendered upper-case |
| `tui.list` | (List) -> Any | focusable list |
| `tui.panel` | (String) -> Any | bordered container with a title |
| `tui.poll` | (Any) -> String | block for a key, redraw, return its name |
| `tui.render` | (Any) -> List | draw one frame; returns the lines |
| `tui.row` | () -> Any | children side by side, equal widths |
| `tui.run` | (Any, String?) -> Unit | loop until the quit key (default `q`) |
| `tui.selected` | (Any) -> String | the focused widget's text or value |
| `tui.progress` | (Int, Int?) -> Any | a bar; value and maximum (default 100) |
| `tui.lib.widgets.progress` | (Int, Int?) -> Any | a bar; value and maximum (default 100) |
| `tui.spinner` | (String?) -> Any | a one-line activity indicator with a label |
| `tui.lib.widgets.spinner` | (String?) -> Any | a one-line activity indicator with a label |
| `tui.status` | (String, String?) -> Any | a message with a level: info, success, warning, error |
| `tui.lib.widgets.status` | (String, String?) -> Any | a message with a level: info, success, warning, error |
| `tui.radio` | (List) -> Any | a group of options; left/right change the choice |
| `tui.lib.widgets.radio` | (List) -> Any | a group of options; left/right change the choice |
| `tui.textarea` | (String?) -> Any | multi-line editable text; Enter inserts a newline |
| `tui.lib.widgets.textarea` | (String?) -> Any | multi-line editable text; Enter inserts a newline |
| `tui.set_progress` | (Any, Int) -> Unit | set a progress bar's value |
| `tui.lib.widgets.set_progress` | (Any, Int) -> Unit | set a progress bar's value |
| `tui.select` | (Any, Int) -> String | choose a radio option; returns its label |
| `tui.lib.widgets.select` | (Any, Int) -> String | choose a radio option; returns its label |
| `tui.selected_index` | (Any) -> Int | the chosen index of a radio or list |
| `tui.lib.widgets.selected_index` | (Any) -> Int | the chosen index of a radio or list |
| `tui.checkbox` | (String) -> Any | a toggle with a label; focusable |
| `tui.lib.widgets.checkbox` | (String) -> Any | a toggle with a label; focusable |
| `tui.press` | (Any) -> String | activate the focused widget once; returns its label |
| `tui.pressed` | (Any) -> String | consume the last activation, so one keypress fires once |
| `tui.focus` | (Any) -> String | the label of the focused widget |
| `tui.focus_next` | (Any, Int?) -> String | move focus forward or back; returns the new label |
| `tui.disable` | (Any) -> Unit | make a widget unfocusable and greyed |
| `tui.enable` | (Any) -> Unit | undo tui.disable |
| `tui.colour_mode` | (Any) -> String | "256", "basic" or "none" for this terminal |
| `tui.set_text` | (Any, String) -> Unit | set a widget's text or field value |
| `tui.size` | (Any) -> Map | {width, height} of the terminal |
| `tui.spacer` | (Int?) -> Any | vertical gap, default 1 |
| `tui.table` | (List) -> Any | rows of columns, first row is the header |
| `tui.text` | (String) -> Any | one line of text |
| `tui.theme` | (Any, Map) -> Unit | override colour tokens |
| `tui.tokens` | (Any) -> Map | the effective colour tokens |
| `tui.value` | (Any) -> String | read a widget's text or value |
| `tui.lib.widgets.app` | (String) -> Any | create an application |
| `tui.lib.widgets.button` | (String) -> Any | focusable button |
| `tui.lib.widgets.column` | () -> Any | children stacked (the default) |
| `tui.lib.widgets.divider` | () -> Any | horizontal rule across the width |
| `tui.lib.widgets.field` | (String) -> Any | editable single-line field (`input` is a keyword) |
| `tui.lib.widgets.heading` | (String) -> Any | one line, rendered upper-case |
| `tui.lib.widgets.list` | (List) -> Any | focusable list |
| `tui.lib.widgets.panel` | (String) -> Any | bordered container with a title |
| `tui.lib.widgets.row` | () -> Any | children side by side, equal widths |
| `tui.lib.widgets.spacer` | (Int?) -> Any | vertical gap, default 1 |
| `tui.lib.widgets.table` | (List) -> Any | rows of columns, first row is the header |
| `tui.lib.widgets.text` | (String) -> Any | one line of text |
| `tui.lib.layout.add` | (Any, Any) -> Unit | attach a widget to a container |
| `tui.lib.layout.column` | () -> Any | children stacked (the default) |
| `tui.lib.layout.divider` | () -> Any | horizontal rule across the width |
| `tui.lib.layout.row` | () -> Any | children side by side, equal widths |
| `tui.lib.layout.spacer` | (Int?) -> Any | vertical gap, default 1 |
| `tui.lib.style.size` | (Any) -> Map | {width, height} of the terminal |
| `tui.lib.style.theme` | (Any, Map) -> Unit | override colour tokens |
| `tui.lib.style.tokens` | (Any) -> Map | the effective colour tokens |

---

## speech — `use speech` (requires a capability)

Offline speech: a Piper neural voice out, Whisper in. No API key, no network at
runtime, nothing uploaded. The full guide is `docs/VOICE.md`.

| Function | Signature | Capability | Notes |
|---|---|---|---|
| `speech.speak` | `(String, Map?) -> Unit` | `speech.speak` | Synthesise and play through the system player (`paplay`, `aplay`, `play`, `afplay`, `termux-media-player`). Errors if none is available — use `speech.save` then. |
| `speech.save` | `(String, String, Map?) -> Unit` | `speech.speak` | Synthesise and write a 16-bit mono WAV. The path must be inside a granted `speech.speak` root. |
| `speech.transcribe` | `(String, Map?) -> Map` | `speech.listen` | Read an audio file and transcribe it. Returns `{text, language, seconds}`. The path must be inside a granted `speech.listen` root. |
| `speech.voices` | `() -> List` | none | Every known voice with `name`, `language`, `label`, `installed`. |
| `speech.licence` | (String?) -> Map | the licence recorded for a voice: id, url, verified, commercial, attribution |
| `speech.languages` | `() -> Map` | none | `speaking`, `speaking_missing`, `listening` — what can be said, what cannot, and what can be heard. |
| `speech.status` | `() -> Map` | none | `can_speak`, `can_listen`, `voices_installed`, `default_voice`, `voices_dir`. |
| `voice.speak` | `(String, Map?) -> Unit` | `voice.speak` | Synthesise and play through the system player (`paplay`, `aplay`, `play`, `afplay`, `termux-media-player`). Errors if none is available — use `voice.save` then. |
| `voice.save` | `(String, String, Map?) -> Unit` | `voice.speak` | Synthesise and write a 16-bit mono WAV. The path must be inside a granted `voice.speak` root. |
| `voice.transcribe` | `(String, Map?) -> Map` | `voice.listen` | Read an audio file and transcribe it. Returns `{text, language, seconds}`. The path must be inside a granted `voice.listen` root. |
| `voice.voices` | `() -> List` | none | Every known voice with `name`, `language`, `label`, `installed`. |
| `voice.licence` | (String?) -> Map | the licence recorded for a voice: id, url, verified, commercial, attribution |
| `speech.platform` | () -> Map | playback and recording tools found on this machine, and why when none |
| `speech.record` | (Int?, String?) -> String | record N seconds to a WAV file; returns the path written |
| `speech.listen` | (Int?, Map?) -> Map | record and transcribe in one step; needs speech.listen |
| `voice.platform` | () -> Map | playback and recording tools found on this machine, and why when none |
| `voice.record` | (Int?, String?) -> String | record N seconds to a WAV file; returns the path written |
| `voice.listen` | (Int?, Map?) -> Map | record and transcribe in one step; needs speech.listen |
| `speech.models` | () -> List | installed models: size, checksum recorded at download, licence |
| `speech.storage` | () -> Map | disk used by voices: model_bytes, megabytes, files |
| `speech.verify` | (String) -> Map | re-hash a voice and compare with the recorded checksum |
| `speech.set_voice` | (String?) -> String | choose the voice later calls use; empty clears it |
| `speech.current_voice` | () -> String | which voice a call without a name would use |
| `speech.download_model` | (String) -> Map | download a voice; needs speech.models |
| `speech.delete_model` | (String) -> Map | delete a voice, returning the bytes freed; needs speech.models |
| `voice.models` | () -> List | installed models: size, checksum recorded at download, licence |
| `voice.storage` | () -> Map | disk used by voices: model_bytes, megabytes, files |
| `voice.verify` | (String) -> Map | re-hash a voice and compare with the recorded checksum |
| `voice.set_voice` | (String?) -> String | choose the voice later calls use; empty clears it |
| `voice.current_voice` | () -> String | which voice a call without a name would use |
| `voice.download_model` | (String) -> Map | download a voice; needs speech.models |
| `voice.delete_model` | (String) -> Map | delete a voice, returning the bytes freed; needs speech.models |
| `speech.cloning_engines` | () -> Map | engines that can clone, and why the others cannot |
| `speech.profiles` | () -> List | voice profiles on this machine: metadata only |
| `speech.profile` | (String) -> Map | one profile's metadata |
| `speech.verify_profile` | (String) -> Map | has the reference recording changed? |
| `speech.create_profile` | (String, String, Map) -> Map | create a profile from a recording; needs consent, speaker and speech.models |
| `speech.delete_profile` | (String) -> Map | delete a profile and its recording; needs speech.models |
| `voice.cloning_engines` | () -> Map | engines that can clone, and why the others cannot |
| `voice.profiles` | () -> List | voice profiles on this machine: metadata only |
| `voice.profile` | (String) -> Map | one profile's metadata |
| `voice.verify_profile` | (String) -> Map | has the reference recording changed? |
| `voice.create_profile` | (String, String, Map) -> Map | create a profile from a recording; needs consent, speaker and speech.models |
| `voice.delete_profile` | (String) -> Map | delete a profile and its recording; needs speech.models |
| `voice.languages` | `() -> Map` | none | `speaking`, `speaking_missing`, `listening` — what can be said, what cannot, and what can be heard. |
| `voice.status` | `() -> Map` | none | `can_speak`, `can_listen`, `voices_installed`, `default_voice`, `voices_dir`. |

Options for `speak`/`save`: `{voice: "hi_IN-pratham-medium", length_scale: 1.1,
noise_scale: 0.6}`. `length_scale` > 1 speaks more slowly. For `transcribe`:
`{model: "base", language: "hi"}`.

```silica
use speech

sfn main() {
    sprint(speech.status())
    speech.save("Silica can talk.", "out/hello.wav", {voice: "en_US-lessac-medium"})
    sprint(speech.transcribe("out/hello.wav"))
}
```

Engines are optional: if `onnxruntime`, an espeak-ng library or `faster-whisper`
is missing, the call fails with the exact install command rather than producing
silence or noise. Downloading a voice is a CLI action
(`silica voice install <name>`), never something a program does implicitly.

---

## ui, ui.state, ui.lib.* — the UI DSL

The UI modules are documented in full in `docs/UI.md`: the grammar, the
property vocabulary, the event model and the renderer. This is the function
list, generated from the same registry the checker uses.

Widgets are builders: they take a `{ ... }` block, except `text`, `image`,
`spacer` and `divider`. `ui` re-exports nine core primitives; the canonical
home of every widget is `ui.lib.widgets`.

### `ui`

| Function | Signature | Notes |
|---|---|---|
| `ui.__end_block` | `() -> Unit` | Internal. Emitted by the compiler to close a builder scope; the checker refuses it in source. |
| `ui.app` | `(title: String, props?: Map) -> Unit` | Document root. Everything else lives inside it. |
| `ui.button` | `(label: String, props?: Map) -> Unit` | Interactive control; takes `ui.on` children. |
| `ui.card` | `(props?: Map) -> Unit` | Elevated surface. |
| `ui.column` | `(props?: Map) -> Unit` | Flex column. |
| `ui.navigate` | `(href: String) -> Unit` | Event action: set location.href. |
| `ui.on` | `(event: String) -> Unit` | Event action list. Allowed events: click, submit, change, input, focus, blur, keydown, mouseenter, mouseleave. |
| `ui.render` | `(options: Map) -> Unit` | Write the artifact. Requires `fs.write` for the output path. Options: target, out, inline_css, inline_runtime, language. |
| `ui.row` | `(props?: Map) -> Unit` | Flex row. |
| `ui.screen` | `(props?: Map) -> Unit` | Top-level surface with safe-area padding. |
| `ui.set_theme` | `(mode: String) -> Unit` | Switch mode: "light", "dark" or "system". |
| `ui.spacer` | `(props?: Map) -> Unit` | Flexible gap; takes no block. |
| `ui.stack` | `(props?: Map) -> Unit` | Single-cell grid. |
| `ui.text` | `(value: Any, props?: Map) -> Unit` | Text node; takes no block. |
| `ui.theme` | `(name: String, props?: Map) -> Unit` | Define the theme. Colours are checked for WCAG AA contrast. |
| `ui.toggle` | `(key: String, class_name: String) -> Unit` | Event action: toggle a CSS class while state is true. |

### `ui.state`

| Function | Signature | Notes |
|---|---|---|
| `ui.state.push` | `(key: String, value: Any) -> Unit` | Event action: append to a list state key. |
| `ui.state.set` | `(key: String, value: Any) -> Unit` | Event action: set a state key. |
| `ui.state.toggle` | `(key: String) -> Unit` | Event action: flip a boolean state key. |

### `ui.lib.widgets`

| Function | Signature | Notes |
|---|---|---|
| `ui.lib.widgets.animate` | `(props?: Map) -> Unit` | Transition wrapper; always emits a reduced-motion override. |
| `ui.lib.widgets.app` | `` | Document root. |
| `ui.lib.widgets.button` | `` | Interactive control; takes `ui.on` children. |
| `ui.lib.widgets.card` | `(props?: Map) -> Unit` | Elevated surface. |
| `ui.lib.widgets.column` | `(props?: Map) -> Unit` | Flex column. |
| `ui.lib.widgets.divider` | `(props?: Map) -> Unit` | Separator; takes no block. |
| `ui.lib.widgets.grid` | `(props?: Map) -> Unit` | CSS grid; set `columns`. |
| `ui.lib.widgets.image` | `(src: String, props?: Map) -> Unit` | Image. `alt` is required. |
| `ui.lib.widgets.link` | `(href: String, props?: Map) -> Unit` | Anchor with child content. |
| `ui.lib.widgets.list` | `(items: List, props?: Map) -> Unit` | Repeats the block once per item, binding `item`. |
| `ui.lib.widgets.list_item` | `(props?: Map) -> Unit` | One row inside a list. |
| `ui.lib.widgets.row` | `(props?: Map) -> Unit` | Flex row. |
| `ui.lib.widgets.screen` | `` | Top-level surface with safe-area padding. |
| `ui.lib.widgets.scroll` | `(props?: Map) -> Unit` | Scroll container: direction, snap, physics, overscroll. |
| `ui.lib.widgets.spacer` | `(props?: Map) -> Unit` | Flexible gap; takes no block. |
| `ui.lib.widgets.stack` | `(props?: Map) -> Unit` | Single-cell grid. |
| `ui.lib.widgets.sticky` | `(props?: Map) -> Unit` | Sticky-positioned section. |
| `ui.lib.widgets.text` | `` | Text node; takes no block. |

### `ui.lib.theme`

| Function | Signature | Notes |
|---|---|---|
| `ui.lib.theme.contrast` | `(token: String, against: String) -> Float` | WCAG contrast ratio between two theme tokens. |
| `ui.lib.theme.token` | `(name: String) -> String` | Look up a theme colour token. |

### `ui.lib.colors`

| Function | Signature | Notes |
|---|---|---|
| `ui.lib.colors.blend` | `(a: String, b: String, amount: Any) -> String` | Linear blend; amount 0.0 to 1.0. |
| `ui.lib.colors.contrast` | `(a: String, b: String) -> Float` | WCAG contrast ratio between two colours. |
| `ui.lib.colors.parse` | `(hex: String) -> Map` | Split a hex colour into r, g, b and hex. |

### `ui.lib.layout`

| Function | Signature | Notes |
|---|---|---|
| `ui.lib.layout.breakpoint` | `(name: String) -> Int` | Breakpoint width in pixels: sm 640, md 768, lg 1024, xl 1280. |
| `ui.lib.layout.breakpoints` | `() -> Map` | Every breakpoint and its width. |

### `ui.lib.scroll`

| Function | Signature | Notes |
|---|---|---|
| `ui.lib.scroll.horizontal` | `(props?: Map) -> Map` | Props map for a horizontal scroll container. |
| `ui.lib.scroll.vertical` | `(props?: Map) -> Map` | Props map for a vertical scroll container. |

### `ui.lib.animation`

| Function | Signature | Notes |
|---|---|---|
| `ui.lib.animation.transition` | `(property: String, duration: String, easing: String?) -> Map` | Props map for `animate`. |

Reserved UI modules (`ui.lib.motion3d`, `ui.lib.navigation`,
`ui.lib.gestures`, `ui.lib.accessibility`, `ui.lib.platform`,
`ui.lib.terminal`, `ui.lib.graphics`, `ui.lib.canvas`) and the adapter slots
(`ui.lib.react`, `.flutter`, `.compose`, `.swiftui`, `.css`, `.qt`) fail with a
clear error instead of pretending to work.

---

## python — interoperability with a Python worker

`use python` — call into CPython from Silica. The Python code runs in a **separate
worker process**, never inside the VM: the VM sends framed JSON messages over a
pipe and receives converted values back. Nothing is unpickled, so a hostile
payload cannot execute code in the host.

**Capability: `interop.python`** (`--allow-interop-python`). Without it every
function below except `python.info` is refused before the worker starts.

| Function | Signature | Returns |
|---|---|---|
| `python.start()` | `() -> Unit` | starts the worker if it is not running |
| `python.stop()` | `() -> Unit` | stops the worker and releases its handles |
| `python.import(module)` | `(String) -> Any` | a handle for the imported module |
| `python.attr(target, name)` | `(Any, String) -> Any` | a converted attribute (e.g. `math.pi`) |
| `python.call(target, function, args)` | `(Any, String, List) -> Any` | the converted result |
| `python.release(handle)` | `(Any) -> Unit` | frees a foreign object |
| `python.info()` | `() -> Map` | `{running, python, handles, capability}` — starts nothing |

`python.call` accepts 2 or 3 arguments; the third is the argument list and
defaults to `[]`. `python.start()` is optional: the first call that needs the
worker starts it.

```silica
use python

sfn main() {
    let m: Any = python.import("math")
    sprint(python.call(m, "sqrt", [2]))    # 1.4142135623730951
    sprint(python.attr(m, "pi"))           # 3.141592653589793
    python.release(m)
    python.stop()
}
```

### Conversion rules

In, and out, without guessing: `Unit`/`null`, `Bool`, `Int` (64-bit, out of range
is an error), `Float`, `String`, `List`, `Map` (String keys only) and binary data
(base64 over the wire). A Python object with no such shape comes back as an
**opaque handle** the program can only pass back to Python — never an address,
never a Python object.

### Errors

Failures are reported with a stable code and no traceback, so host paths do not
leak: `operation.failed` (missing module, unknown function, rejected argument),
`operation.timeout` (the worker is stopped, not reused), `worker.lost` (the worker
crashed), `handle.released` / `handle.owner` (a handle that is gone or belongs to
another provider or session).

### Limits

A frame is capped at 8 MiB, a call has a deadline (10 s by default), and each
session is capped at 1024 live handles. A timed-out or crashed worker is
terminated and must be restarted.

### Platform notes

The worker is a child process of the interpreter, so it works wherever Silica
runs, including Termux — but it has been tested on Linux x86_64 only. It is **not**
a sandbox: the worker can do anything the Python process can do. See
`docs/SECURITY_MODEL.md`.

## path — path text, without touching the disk

`use path` — split, join and normalise paths as **strings**. Nothing in this module
opens, stats or lists anything, so it needs **no capability**: a program can reason
about paths without being allowed to touch them. The functions that do touch the
disk are `fs.*`, behind `fs.read` / `fs.write` / `fs.list`.

| Function | Signature | Returns |
|---|---|---|
| `path.join(parts)` | `(List) -> String` | the parts joined with `path.sep` |
| `path.base(p)` | `(String) -> String` | last component (`""` for a trailing separator) |
| `path.dir(p)` | `(String) -> String` | everything before the last component |
| `path.ext(p)` | `(String) -> String` | extension including the dot, or `""` |
| `path.stem(p)` | `(String) -> String` | file name without its extension |
| `path.split(p)` | `(String) -> List` | `[head, tail]` |
| `path.normalise(p)` | `(String) -> String` | collapses `//`, `.` and `..` **lexically** |
| `path.absolute(p)` | `(String) -> String` | absolute form against the current directory, lexically |
| `path.is_absolute(p)` | `(String) -> Bool` | whether it starts at the root |
| `path.is_within(p, root)` | `(String, String) -> Bool` | whether `p` is `root` or below it, lexically |
| `path.with_suffix(p, s)` | `(String, String) -> String` | `p` with its extension replaced by `s` |

Constant: `path.sep` — the host's separator, so a program need not guess.

```silica
use path

sfn main() {
    let p: String = path.join(["data", "notes", "a.txt"])
    sprint(p)                        # data/notes/a.txt
    sprint(path.base(p))             # a.txt
    sprint(path.ext(p))              # .txt
    sprint(path.normalise("data/./x/../y.txt"))   # data/y.txt
    sprint(path.is_within(p, "data"))             # oui
    sprint(path.is_within("/etc/passwd", "data")) # nein
}
```

**What `is_within` is not.** It compares normalised *text*. It does not resolve
symlinks and does not know whether a path exists, so it cannot be a sandbox on its
own — `a/b/..` may be a symlink to somewhere else. The real boundary is the
capability check in `fs.*`, which resolves canonical paths before it opens
anything. `is_within` is for deciding what to ask for, not for granting access.

A NUL byte in any argument is refused: it cannot appear in a real path and it is
the classic way to truncate a path inside a C library.

## time — two clocks, and a fixed date format

`use time` — read the clock, wait, and format dates. No capability: reading a
clock touches no file, no network and no other process.

| Function | Signature | Returns |
|---|---|---|
| `time.now()` | `() -> Int` | wall-clock seconds since the Unix epoch, UTC |
| `time.now_ms()` | `() -> Int` | the same in milliseconds |
| `time.monotonic()` | `() -> Float` | a monotonic clock, arbitrary origin — use for elapsed time |
| `time.sleep(s)` | `(Float) -> Unit` | waits `s` seconds (0 ≤ s ≤ 86400) |
| `time.iso(epoch)` | `(Int) -> String` | `2026-11-01T10:00:00Z` |
| `time.parse_iso(s)` | `(String) -> Int` | epoch seconds from ISO-8601 |
| `time.year(epoch)` | `(Int) -> Int` | UTC year |
| `time.month(epoch)` | `(Int) -> Int` | UTC month, 1–12 |
| `time.day(epoch)` | `(Int) -> Int` | UTC day of month |

```silica
use time

sfn main() {
    let start: Float = time.monotonic()
    sprint(time.iso(time.now()))          # 2026-11-01T10:00:00Z
    sprint(time.parse_iso("1970-01-01T00:00:10Z"))   # 10
    sprint(time.monotonic() >= start)     # oui
}
```

`now` can jump backwards (NTP, a manual change), so it is for timestamps.
`monotonic` cannot, so it is for measuring. There is no `strftime`: one fixed,
unambiguous output is more useful than a partial format language.

## random — ordinary randomness, and separately, secure randomness

`use random` — the distinction is in the names, because it matters.

**Ordinary pseudorandom** (a Mersenne Twister: fast, reproducible, **never for
secrets**):

| Function | Signature | Returns |
|---|---|---|
| `random.float()` | `() -> Float` | in `[0.0, 1.0)` |
| `random.int(low, high)` | `(Int, Int) -> Int` | `low` included, `high` excluded |
| `random.choice(items)` | `(List) -> Any` | one element of a non-empty list |
| `random.shuffle(items)` | `(List) -> List` | a new list; the argument is unchanged |
| `random.seed(n)` | `(Int) -> Unit` | makes the sequence reproducible |

**Cryptographically secure** (the operating system's CSPRNG, never seeded):

| Function | Signature | Returns |
|---|---|---|
| `random.secure_bytes(n)` | `(Int) -> String` | `n` random bytes as 2n hex characters |
| `random.secure_int(low, high)` | `(Int, Int) -> Int` | `low` included, `high` excluded |
| `random.secure_token(n)` | `(Int) -> String` | URL-safe text from `n` random bytes |

```silica
use random

sfn main() {
    random.seed(7)
    let a: Int = random.int(1, 7)
    random.seed(7)
    let b: Int = random.int(1, 7)
    sprint(a == b)                        # oui — reproducible when seeded

    sprint(len(random.secure_bytes(8)))   # 16 — hex text, two chars per byte
    let token: String = random.secure_token(16)
    sprint(len(token) > 16)               # oui
}
```

`random.float`, `int`, `choice` and `shuffle` are **not** cryptographically
secure and are documented as such; for a password, a token or a key, use the
`secure_*` functions. Silica has no byte type, so random bytes are returned as hex
text and tokens as URL-safe text — stated rather than silently re-encoded.

## Planned modules (not implemented)

`regex`, `http`, `net`, `process`, `log`, `crypto`, `test`, `async`, `ai`.

Using any of them is a compile error that names the implemented modules. They are
deliberately not stubbed: a module either works or does not exist.

## Security model

A Silica program starts with **no capabilities**. It can compute, print and read
stdin; it cannot open a file. Privileged operations are named capabilities
(`fs.read`, `fs.write`, `fs.list`) and each grant is scoped to a root path.

* **Granting** happens outside the program, on the command line
  (`--allow-fs-read DIR`) or in a TOML file (`--capabilities FILE`). A program
  cannot grant itself anything: the set is built before the VM starts.
* **Denying** (`--deny-fs-read`) removes a capability even when a root was
  granted, so a caller can narrow a config file without editing it. Deny wins.
* **Inheriting**: one set per run. Every function called inherits it; `derive()`
  can only narrow, never widen, so a callee cannot exceed its caller.
* **Enforcement** lives at the VM's `CALL_NATIVE` dispatch, not inside the
  filesystem functions: each privileged native declares the capability it needs,
  the VM authorises the call, and the native receives the path that was actually
  authorised. There is no second resolution step to disagree with the check.

There is no network, environment or arbitrary host-execution capability.
Starting a foreign runtime is its own capability (`interop.python`), and it grants
no filesystem, network or native-library access by itself. `silica capabilities`
prints the effective set.

## colours

`use colors` — perceptual colour, palettes and accessibility. Colours are Maps of
`{r, g, b, a}` in 0..1; everything else is computed from those four numbers.
Manipulation happens in OKLab/OKLCH, which is perceptually uniform, so equal
steps look equal.

| `colors.parse` | (String) -> Map | parse #hex, rgb(), hsl(), oklch(), oklab() or a CSS name |
| `colors.rgb` | (Float, Float, Float, Float?) -> Map | sRGB colour from 0..1 components |
| `colors.oklch` | (Float, Float, Float, Float?) -> Map | perceptual colour; gamut-mapped, not clipped |
| `colors.oklab` | (Float, Float, Float, Float?) -> Map | OKLab colour; gamut-mapped, not clipped |
| `colors.hsl` | (Float, Float, Float) -> Map | hue in degrees, saturation and lightness in 0..1 |
| `colors.describe` | (Any) -> Map | hex, rgb, oklab, oklch, hsl, luminance and gamut status |
| `colors.hex` | (Any) -> String | the colour as #rrggbb (or #rrggbbaa when translucent) |
| `colors.css` | (Any, String?) -> String | CSS string in oklch (default), oklab, srgb or hex |
| `colors.to_p3` | (Any) -> Map | Display P3 components; not HDR |
| `colors.from_p3` | (Any) -> Map | Display P3 to sRGB; may land outside the sRGB gamut |
| `colors.in_gamut` | (Any) -> Bool | whether the colour fits in sRGB |
| `colors.to_gamut` | (Any) -> Map | map into sRGB by reducing chroma at fixed lightness and hue |
| `colors.lighten` | (Any, Float) -> Map | raise perceptual lightness by 0..1 |
| `colors.darken` | (Any, Float) -> Map | lower perceptual lightness by 0..1 |
| `colors.with_lightness` | (Any, Float) -> Map | set OKLab lightness outright |
| `colors.with_chroma` | (Any, Float) -> Map | set OKLCH chroma |
| `colors.with_hue` | (Any, Float) -> Map | set OKLCH hue in degrees |
| `colors.mix` | (Any, Any, Float?) -> Map | interpolate in OKLab; weight defaults to 0.5 |
| `colors.gradient` | (Any, Any, Int?) -> List | even perceptual steps between two colours |
| `colors.composite` | (Any, Any) -> Map | alpha-composite the first over the second |
| `colors.contrast` | (Any, Any) -> Float | WCAG contrast ratio, 1.0 to 21.0 |
| `colors.passes` | (Any, Any, String?, Bool?) -> Map | WCAG AA/AAA verdict for normal or large text |
| `colors.best_foreground` | (Any) -> Map | the most readable of black or white on a background |
| `colors.luminance` | (Any) -> Float | WCAG relative luminance |
| `colors.palette` | (Any, List?) -> Map | shade scale keyed "50".."950" |
| `colors.theme` | (Any, Bool?) -> Map | semantic tokens; second argument true for dark |
| `colors.audit` | (Map) -> Map | WCAG checks for a theme's text/background pairs |
| `colors.css_theme` | (Map) -> String | CSS custom properties for a theme |
| `colors.css_scale` | (String, Map) -> String | CSS custom properties for a named scale |

See `docs/COLOR.md` for the reference values, the gamut mapping algorithm and
what is deliberately not supported (HDR).
