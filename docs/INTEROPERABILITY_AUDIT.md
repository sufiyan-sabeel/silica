# Interoperability audit

What the Silica implementation actually does today, measured rather than assumed,
as the basis for the interoperability architecture in `docs/INTEROPERABILITY.md`.

- **Repository:** `sufiyan-sabeel/silica`
- **Commit audited:** `cdeabb7a18c2ce748e12c53871f57c52e80748b9` (default branch `main`, after the classes/generics merge)
- **Version:** 0.9.3 · **Requires:** Python `>=3.9`
- **Baseline suite at that commit:** 1081 passed, 7 skipped, 1188 subtests

Every statement below was checked against the source at that commit. Nothing here
is taken from the README or from earlier design notes.

---

## 1. The native registry

`silica/natives.py` holds one global registry, built once at import time.

| Piece | What it is |
|---|---|
| `Native` | A record: `module`, `name`, `params`, `ret`, `fn`, `min_args`, `max_args`, `requires`, `path_arg`, `accepts_block`, plus a `qualified` property |
| `_build()` | The only registration point; returns `mods`, a `{module: {name: Native}}` dict |
| `MODULES` | The registry, assigned from `_build()` at import |
| `CONSTANTS` | Module-level constants (`math.pi`, `math.e`, `math.tau`) |
| `PLANNED_MODULES` | 12 names that exist as documentation only and fail loudly |
| `get_native`, `get_constant`, `module_exists`, `constant_names` | The lookup surface |

Measured size at this commit: **25 modules, 281 natives**.

Modules: `core`, `math`, `string`, `collections`, `fs`, `json`, `colors`,
`speech`, `voice`, `tui`, `tui.lib.layout`, `tui.lib.style`, `tui.lib.widgets`,
`ui`, `ui.state`, `ui.lib.animation`, `ui.lib.colors`, `ui.lib.layout`,
`ui.lib.scroll`, `ui.lib.theme`, `ui.lib.widgets`, `gui`, `gui.lib.layout`,
`gui.lib.theme`, `gui.lib.widgets`.

Planned (not implemented): `ai`, `async`, `crypto`, `http`, `log`, `net`, `path`,
`process`, `random`, `regex`, `test`, `time`.

### All registration points

`_build()` is the single function, but it pulls in four sibling tables, each
declared next to the code it exposes:

```python
from .gui.natives_gui import FUNCTION_TABLES as _GUI        # natives.py:588
from .tui.natives_tui import FUNCTIONS as _TUI              # :595
from .voice.natives_speech import FUNCTIONS as _SPEECH      # :602
from .ui.natives_colors import FUNCTIONS as _COLORS         # :613
from .ui.natives_ui import FUNCTIONS as _UI                 # :619
```

and aliases one namespace:

```python
# `voice` is the preferred namespace; `speech` stays for compatibility.
mods["voice"].update(mods["speech"])                        # :611
```

That alias is a **precedent worth copying**: the same `Native` objects appear
under two module keys, so `voice.speak` and `speech.speak` both resolve. A
side-effect to note — the alias does not rewrite `Native.module`, so a diagnostic
raised through `voice.speak` reports itself as `speech.speak`. It is cosmetic, it
predates this audit, and the interop design should not repeat it (a provider
namespace should carry its own name).

### What the registry is not

- There is **no runtime registration**: `MODULES` is built at import and never
  mutated afterwards. Nothing can add a native after startup.
- There is **no plugin discovery**: nothing scans the filesystem, entry points or
  environment for natives.
- The registry is a plain dict of plain records, with no ownership, no lifetime
  and no versioning.

---

## 2. `CALL_NATIVE`, end to end

### Checker (`silica/checker.py`)

- `check_use` resolves `use mod`: a name in `MODULES` is imported; a name in
  `PLANNED_MODULES` errors "planned but not implemented yet"; anything else is
  "unknown module". UI reserved/adapter names have their own loud errors.
- A call is typed from the `Native` record: `params` give the expected argument
  types, `min_args`/`max_args` the arity. The return type is `native.ret`.

### Compiler (`silica/compiler.py:648`, `:665`)

`CALL_NATIVE` carries **three operands**: the module-name constant index, the
function-name constant index, and the argument count. Module and function are
interned as strings; the compiler does not embed an index into the registry.

### Verifier (`silica/bytecode.py:612`)

Before a chunk may run:

- both constants must be `str`;
- `get_native(module, name)` must resolve;
- `min_args <= argc <= max_args`.

So a chunk that names a native which no longer exists is rejected at load, not at
call time.

### VM dispatch (`silica/vm.py:293`)

```python
elif op == 0x1A:  # CALL_NATIVE
    mod_idx, fn_idx, argc = operands
    module = constants[mod_idx]
    fname  = constants[fn_idx]
    native = natives.get(module, {}).get(fname)
    args   = stack[-argc:] if argc else []
    try:
        if native.requires is not None:
            args = self.capabilities.authorize_call(native, args)
        result = native.fn(ctx, args)
    except SilicaError as err:
        # line, column and filename are attached here
        raise
    stack.append(result)
```

Two properties matter for interoperability:

1. **The resolution is by name, at dispatch time.** The verifier proves the name
   was valid when the chunk was verified; the VM resolves again when it runs.
2. **`authorize_call` is the single authorization point for the whole language.**
   Every privileged operation in Silica passes through these six lines. The
   native itself never re-checks and never re-resolves the path it is handed.

---

## 3. Capabilities

`silica/capabilities.py`. Declared on the native, granted outside the program,
enforced at the one dispatch point above.

| Concept | Implementation |
|---|---|
| Kinds | A closed tuple of 8: `fs.read`, `fs.write`, `fs.list`, `speech.speak`, `speech.listen`, `speech.models`, `tui.run`, `gui.run` |
| Declaration | `Native.requires` names the kind; `Native.path_arg` names the argument holding a path |
| Grant | `CapabilitySet.grant(kind, root)` — scoped to a directory for the `fs` kinds, unscoped for `tui.run`, `gui.run`, `speech.models` |
| Deny | `CapabilitySet.deny(kind)`; and by default nothing is granted |
| Enforce | `CapabilitySet.require(kind)` raises `CapabilityError` |
| Path resolution | `resolve_path(kind, path)` returns the authorised absolute path, refusing anything outside a granted root |
| Config | CLI flags (`--allow-fs-read DIR`, `--allow-fs-write`, `--allow-fs-list`, `--allow-speech-speak`, `--allow-speech-listen`, `--allow-tui`, …) or a `[capabilities]` table in a TOML file |

`authorize_call(native, args)` is the gate: it requires the kind, resolves the
path argument, and returns the argument list with that path replaced by the
resolved one. **29 of the 281 natives are privileged** (`fs.*`, `gui.*`,
`speech.*`).

Deny-by-default is real, not aspirational: with no grants, an `fs.read_text`
call raises before any I/O happens, and `tests/test_capabilities.py` (373 lines)
covers grant, deny, scoping, path escape and the config parser.

---

## 4. Language surface relevant to interoperability

Verified by running programs, not by reading the spec.

| Feature | State |
|---|---|
| `struct` | Records with typed fields; construction positional or named; `MAKE_STRUCT` with a descriptor constant; structural equality; frozen when bound with `const` |
| `class` | Fields + methods, `private`, `static`; identity equality; instances are the same runtime value type with `is_struct=False` |
| Methods | Compiled as `Type.method` functions; `CALL_METHOD` (0x2A) dispatches on the runtime type name; `self` in slot 0 |
| Generics | `<T>` on `sfn`/`struct`/`class`; constraints `Numeric`, `Orderable`, `Equatable`; `List<T>`, `Map<K,V>`; inference at construction and calls; **erased at run time** (`type_of(Box(1))` is `Box`) |
| Inheritance | **None.** No subtyping, no interfaces, no traits |
| Exceptions | None. Errors are `SilicaError` subclasses raised by the checker, verifier, VM or a native |
| First-class functions | None ("Silica v0.8.0 has no first-class functions") |
| Pointers | No pointer type, no raw addresses in the language |

For interoperability the relevant consequence is: **there is no existing way for a
Silica program to name a foreign object, and no place to put one.** Values are
Python objects (`int`, `float`, `str`, `bool`, `list`, `dict`, `StructValue`,
`Iterator`, `None`), and `type_of` maps them to Silica type names.

---

## 5. Module import and name resolution

- `use mod` imports one module. Importing a parent brings its submodules into
  scope (`use ui` makes `ui.lib.widgets` resolvable); importing a leaf does not
  bring its parent.
- A member is resolved by name at check time and again at run time; unknown
  members produce located errors listing what is available.
- Module-level constants are separate from natives (`CONSTANTS`).
- Reserved and planned names fail loudly rather than resolving to something
  empty — the "reserved names fail loudly instead of pretending" rule in
  `check_use`.

---

## 6. Bytecode compatibility constraints

| Constraint | Value at this commit |
|---|---|
| Magic + version | `FORMAT_MAJOR = 1`, `FORMAT_MINOR = 0` |
| Integrity | CRC-32 over the payload |
| Structure | constant pool, globals, functions (code, line table), entry index |
| Verifier | Runs on load; checks operands, constant types, native existence and arity, jump targets, stack discipline, `CALL_METHOD` names and arity |
| Recent additions | `MAKE_STRUCT` 0x26, `GET_FIELD` 0x27, `SET_FIELD` 0x28, `FREEZE` 0x29, `CALL_METHOD` 0x2A |

The format is **1.0 and unchanged by the generics work** (type arguments are
erased, so nothing new is stored). `tests/test_bytecode.py` and the round-trip
tests in `test_classes.py`/`test_generics.py` pin this down.

**Constraint for interoperability:** `CALL_NATIVE` operands are
`(module const, name const, argc)` and the verifier resolves them against the
global native registry. A provider call therefore cannot reuse `CALL_NATIVE`
without either (a) registering provider operations in that same global registry —
which the brief forbids ("a provider registry separate from the existing
standard-library native registry") — or (b) changing the format. Neither is
acceptable in a non-breaking foundation, so **Phase 3 adds no opcode and no
Silica-visible surface at all.**

---

## 7. Existing process and native-library functionality

There is more here than the brief assumes, and it is the closest thing to a
precedent for the worker protocol.

| Mechanism | Where | Notes |
|---|---|---|
| In-process ONNX inference | `silica/voice/piper.py`, `whisper.py` | Needs `onnxruntime`; no subprocess |
| **`ctypes.CDLL` of `libespeak-ng`** | `silica/voice/espeak.py:119` | Loads a shared library and calls `espeak_Initialize`, `espeak_SetVoiceByName`, `espeak_TextToPhonemes`. Search order: an `espeakng_loader` package path, then `ctypes.util.find_library`, then glob patterns including `/data/data/com.termux/files/usr/lib/libespeak-ng.so*`, then a CLI binary |
| Subprocess | `silica/voice/espeak.py:166`, `silica/voice/__init__.py:390` | `subprocess.run(..., timeout=300)` for the espeak CLI and the system audio player |

All of it sits **inside capability-gated speech natives** (`speech.speak`,
`speech.listen`, `speech.models`), so it is unreachable without a grant.

Two observations that shape the design:

- **A native library is already loaded by path**, with a fallback chain and no
  allowlist of libraries — the gate is the capability, not the library identity.
  The C ABI section of the architecture has to be stricter than this precedent,
  not modelled on it.
- **The only timeouts in the codebase are the subprocess ones** (300 s, hardcoded
  per call site). There is no general deadline, message-size bound or resource
  accounting anywhere.

---

## 8. Platform and test limitations

- **Python 3.9+** (`requires-python = ">=3.9"`). Code must stay 3.9-compatible:
  no `match`, no `X | Y` annotations at runtime, no `tomllib`.
- **Termux/ARM64** is a first-class target in intent — the espeak search paths and
  `PREFIX` handling exist for it — but there is no CI job that proves it. Nothing
  in this audit was executed on Termux.
- **7 tests are skipped** in this environment: the GUI/TUI rendering suites need a
  terminal or display.
- The audio and ONNX engines cannot run here (no models, no audio device), so
  their tests are skipped or use fakes.

---

## 9. Findings that constrain the design

| # | Finding | Consequence |
|---|---|---|
| F1 | `MODULES` is built at import and never mutated | A provider registry must be a **separate** structure, not an addition to `MODULES` |
| F2 | `CALL_NATIVE` resolves names against the global registry and the verifier enforces it | Provider calls cannot be expressed as `CALL_NATIVE` without a format change; the foundation exposes **no** Silica syntax |
| F3 | `authorize_call` in the VM is the only authorization point | Any future provider invocation must pass through the same call, not a parallel check |
| F4 | Capability kinds are a closed 8-tuple | A provider capability is a **new kind** and needs a table entry; until then a provider declares what it needs and the registry refuses unknown kinds |
| F5 | Values are plain Python objects; there is no foreign handle type | The foundation must define one, and define its lifecycle, before any ecosystem is wired up |
| F6 | Errors are `SilicaError` subclasses with line/column/filename attached by the VM | Interop errors need a structured form that can be attached to a call site the same way |
| F7 | `voice`/`speech` shows namespace aliasing works but leaks the canonical name into diagnostics | Provider namespaces carry their own name; no aliasing in the foundation |
| F8 | A shared library is already loaded by path in `espeak.py`, gated only by capability | The C ABI plan must require an explicit allowlist and versioned symbols — stricter than the existing precedent |
| F9 | Format 1.0 with a load-time verifier; no requirement has yet forced a change | Keep 1.0; the foundation is Python-side only |
| F10 | No general deadline or size bound exists; only per-call subprocess timeouts | Timeout and message-size limits belong in the provider context, enforced by the caller |

## 10. What this audit did not do

- It did not run anything on Termux, Android, Windows or macOS.
- It did not exercise the audio, ONNX or GUI paths (no models, no device, no
  display here).
- It did not measure performance; `docs/PERFORMANCE.md` and `docs/AUDIT.md`
  already cover that ground.
- It did not attempt to load a foreign library, start a worker, or define any
  Silica-visible interop syntax.
