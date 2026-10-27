# Silica Standard Library — v0.1.0

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

## Planned modules (not implemented)

`fs`, `path`, `json`, `time`, `random`, `regex`, `http`, `net`, `process`, `log`,
`crypto`, `test`, `async`, `ai`.

Using any of them is a compile error that names the implemented modules. They are
deliberately not stubbed: a module either works or does not exist.

## Security model

Silica v0.1.0 exposes no operating-system capability: no file access, no network,
no process execution, no environment access. Programs can read stdin and write
stdout/stderr only. When `fs`, `net` and `process` arrive, they will be explicit
imports with a documented capability boundary rather than ambient authority.
