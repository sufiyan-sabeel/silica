# Silica Language Specification — v0.9.3

This document is normative for the v0.9.3 reference implementation. Anything
described here is implemented and covered by tests in `tests/`; anything else is
listed under [Not implemented yet](#not-implemented-yet).

Silica is a small statically typed language. Source files use the `.sc`
extension, compiled programs use `.sbc`, and the toolchain command is `silica`.

---

## 1. Source files

A Silica file is UTF-8 text. It contains, in any order:

* `use` declarations,
* `sfn` function declarations,
* `let` / `const` global declarations.

No other statement may appear at the top level: executable code lives inside a
function, and every program must declare `sfn main()`.

```
sfn square(n: Int) -> Int {
    ret n * n
}

sfn main() {
    sprint(square(12))
}
```

Output:

```
144
```

Comments start with `#` or `//` and run to the end of the line.

## 2. Keywords

These words are reserved and may not be used as identifiers.

| Purpose | Silica | Meaning in v0.1.0 |
|---|---|---|
| Print line | `sprint(x)` | Write `x` to stdout followed by `\n`. Returns `Unit`. |
| Print inline | `dit(x)` | Write `x` to stdout with **no** trailing newline. Returns `Unit`. |
| Input | `input(prompt)` | Write `prompt` (a `String`), read one line from stdin, return it without the line ending. |
| If | `si cond { }` | Branch when `cond` is `oui`. `cond` must be `Bool`. |
| Else | `sino { }` | Alternative branch; must directly follow an `si` block. |
| Logical and | `und` | `Bool und Bool`, short-circuit: right side is not evaluated when the left is `nein`. |
| Logical or | `ou` | `Bool ou Bool`, short-circuit: right side is not evaluated when the left is `oui`. |
| Logical not | `non` | `non Bool -> Bool`. |
| True | `oui` | Boolean literal `true`. |
| False | `nein` | Boolean literal `false`. |
| While | `tant cond { }` | Loop while `cond` is `oui`. |
| For | `per name in expr { }` | Iterate a `List`, `Map` (keys) or `String` (characters). |
| Leave a loop | `break` | Leave the innermost enclosing loop immediately. |
| Next iteration | `continue` | Abandon the rest of the body and start the next iteration. |
| Function | `sfn name(params) -> T { }` | Declare a function. |
| Return | `ret expr` / `ret` | Return a value from a function. |
| Import | `use module` | Import a standard-library module. |
| End of block | `fin` | Optional explicit block terminator, allowed immediately before `}`. |
| Stop | `halt` / `halt(code)` | Terminate the program with exit code 0 or `code`. |
| Binding | `let x = e` / `const x = e` | Mutable / immutable binding. |

### 2.1 Why both `sprint` and `dit` exist

`sprint` always terminates its output with a newline. `dit` never does. They are
not redundant: `dit` is required for prompts, progress output and building a
line from several values, which `sprint` cannot do.

```
dit("value: ")
dit(42)
sprint("")          # finish the line
```

### 2.2 What `fin` means (and does not mean)

`fin` is a **block terminator only**. `{ ... }` and `{ ... fin }` are exactly
equivalent; the parser accepts an optional `fin` as the last element of a block.
It never ends a statement, never returns, never breaks a loop, and never
terminates the program — that is `halt`'s job. Because braces already delimit
blocks, `fin` is optional everywhere and exists for readability.

### 2.3 What `halt` does

`halt` stops the program immediately. `halt` exits with status 0; `halt(n)`
exits with status `n` (an `Int`). Code after a `halt` in the same block is not
executed. The operating system sees `n & 0xFF`.

### 2.4 What `break` and `continue` do

`break` leaves the **innermost** enclosing loop immediately. `continue` abandons
the rest of the current iteration and starts the next one. Both are statements,
neither carries a value, and neither is a function.

```
per n in [1, 2, 3, 4] {
    si n == 2 {
        continue            # skip the rest of this iteration
    }
    si n == 4 {
        break               # leave the loop
    }
    sprint(n)               # prints 1 and 3
}
```

* In a `tant` loop, `continue` re-tests the condition. In a `per` loop it advances
  the iteration. Update the loop variable **before** a `continue` in a `tant`
  loop, or the loop makes no progress and never terminates.
* Both apply to the innermost loop only. Inside nested loops, `break` leaves one
  level; there are no labels (`break outer` does not exist).
* A jump with no enclosing loop is a **compile-time** error:
  `'break' is only allowed inside a loop`, with a hint naming `tant`/`per`. Loop
  depth resets at every function boundary, so a jump cannot reach a caller's loop.
* Neither may appear inside a `call { ... }` builder block, for the same reason
  `ret` may not: a widget tree is closed structurally.
* `break` is not `halt`: `break` ends a loop, `halt` ends the program.

## 3. Values and types

| Type | Meaning |
|---|---|
| `Int` | 64-bit signed integer. |
| `Float` | IEEE-754 double. |
| `Bool` | `oui` / `nein`. |
| `String` | Immutable UTF-8 text. |
| `Unit` | The result of statements and `Unit`-returning functions. |
| `List` | Ordered, mutable sequence of values. |
| `Map` | String-keyed dictionary of values. |
| `Any` | Internal wildcard used by `List`/`Map` element types. |

There is no `null`. A function that returns nothing returns `Unit`.

`List` and `Map` are containers of *unknown* element type in v0.1.0: reading
`xs[0]` yields a value of type `Any`, which is accepted anywhere. That is a
documented limitation — generics arrive in a later milestone.

### 3.1 Numeric rules

* `Int` is 64-bit and **wraps** on overflow (two's complement). `9223372036854775807 + 1` is `-9223372036854775808`.
* `Int / Int` truncates toward zero: `7 / 2 == 3`, `-7 / 2 == -3`.
* `Int % Int` keeps the sign of the dividend: `-7 % 2 == -1`, `7 % -2 == 1`.
* `Float` follows IEEE-754 for `+ - * /` except that **division or modulo by zero is a runtime error** for both `Int` and `Float` (no silent `inf`).
* Mixing `Int` and `Float` in arithmetic promotes the `Int` to `Float`.
* A `Float` never converts to `Int` implicitly; use `int(x)`. An `Int` may be used where a `Float` is expected.

### 3.2 Equality and ordering

* `==` / `!=` compare structurally for `List` and `Map`, by value for scalars.
* Numeric equality crosses types: `1 == 1.0` is `oui`.
* `Bool` never equals a number.
* `< <= > >=` work on numbers and on `String` (lexicographic by code point).
* Ordering two different non-numeric types is a compile error.

### 3.3 Truthiness

There is none. Every condition must be `Bool`, so `si x { }` with an `Int` is a
compile error. Write the comparison you mean: `si x != 0 { }`.

### 3.4 String literals

A string literal may use any of four delimiters. The value is the same for all
four; only the quoting rules differ.

| Form | Multiline | Notes |
|---|---|---|
| `"silica"` | no | the classic form; `"` inside must be escaped as `\"` |
| `'silica'` | no | `"` inside needs no escape; `'` inside must be escaped as `\'` |
| `"""silica"""` | **yes** | runs to the next `"""`; raw newlines are kept |
| `'''silica'''` | **yes** | runs to the next `'''`; raw newlines are kept |

```
let plain = "one line"
let apostrophe = 'it\'s fine'
let quoted = 'she said "hi"'
let paragraph = """first line
second line"""
```

Rules:

* A single-quoted or double-quoted string is **one line**. A raw newline inside
  one is a lex error; write `\n`, or use a triple-quoted string.
* A triple-quoted string keeps every character between the delimiters, including
  newlines. Nothing is trimmed, so `"""a\nb"""` is five characters.
* Escapes work in all four forms: `\n \t \r \0 \\ \" \' \uXXXX`.
* The empty string is `""`, `''`, `""""""` or `''''''`.
* There is no string interpolation and no raw-string prefix: a backslash always
  starts an escape.
* `silica fmt` normalises every literal to a double-quoted, single-line form with
  escapes — the value is unchanged, and a multiline string becomes `\n` escapes.

## 4. Operators and precedence

From lowest to highest binding:

| Level | Operators | Associativity |
|---|---|---|
| 1 | `ou` | left |
| 2 | `und` | left |
| 3 | `==` `!=` | left |
| 4 | `<` `<=` `>` `>=` | left |
| 5 | `+` `-` | left |
| 6 | `*` `/` `%` | left |
| 7 | unary `non`, unary `-` | right |
| 8 | call `f(x)`, index `x[i]`, member `m.n` | left |

`+` is defined for `Int`/`Float` (numeric addition), `String` + `String`
(concatenation) and `List` + `List` (concatenation). `- * / %` are numeric only.

## 5. Statements

```
let name: Type = expr      # mutable
const name: Type = expr    # immutable
name = expr                # assignment to a let-bound variable
si cond { ... } sino { ... }
tant cond { ... }
per item in expr { ... }
break                      # leave the innermost loop
continue                   # start the next iteration of the innermost loop
ret expr
halt(code)
expr                       # expression statement; value is discarded
```

The type annotation on `let`/`const` is optional when the initializer has a
type; it is then inferred from the initializer (literals and call results).

`per` binds its loop variable immutably for each iteration. Iterating a `Map`
yields its keys as `String`; iterating a `String` yields one-character `String`s.

## 6. Functions

```
sfn add(a: Int, b: Int) -> Int {
    ret a + b
}
```

* Parameter type annotations are optional; an unannotated parameter has type `Any`.
* `-> T` gives the return type; without it the function returns `Unit`.
* Functions are declared at the top level only (no closures, no nesting).
* Functions are not first-class values in v0.1.0: they can be called, not passed.
* A function with a non-`Unit` return type must return on **every** path, which
  the checker verifies (`si`/`sino` where both branches return counts).
* `main` takes no parameters. Recursion is supported; the call depth is limited
  (4096 frames by default) and exceeding it is a runtime error.

## 7. Modules

Standard-library modules must be imported before use:

```
use math
use string

sfn main() {
    sprint(math.sqrt(16.0))
    sprint(string.upper("hi"))
}
```

`core` (print, input, conversions, `len`, `range`, `push`, `keys`, `values`,
`has`, `assert`, `type_of`) is always available without a `use`.

Implemented modules: `math`, `string`, `collections`, `json`, `fs`, and the UI
modules (`ui`, `ui.state`, `ui.lib.widgets`, `ui.lib.theme`, `ui.lib.colors`,
`ui.lib.layout`, `ui.lib.scroll`, `ui.lib.animation`). Using a module that exists
in the plan but is not implemented (for example `http`) is a compile error that
says so.

Module paths may be dotted (`use ui.lib.widgets`). Importing a module also brings
its submodules into scope. In a member chain the longest prefix that names an
imported module is the module, and exactly one member may follow it.

`fs` is the only module that reaches outside the engine, and it is guarded by the
capability model described in section 11.

See `docs/STANDARD_LIBRARY.md` for every function, its signature and its errors.

## 8. Output formatting

`sprint` and `dit` render values as follows:

| Value | Output |
|---|---|
| `Int` | decimal digits, e.g. `42` |
| `Float` | shortest round-trip form with a decimal point, e.g. `1.5`, `2.0` |
| `Bool` | `oui` / `nein` |
| `String` | as-is, unquoted |
| `List` | `[1, 2, 3]` — nested strings are quoted |
| `Map` | `{"a": 1}` |
| `Unit` | `unit` |

## 9. Errors

Every diagnostic carries `file:line:column` where available, a category
(`lex error`, `parse error`, `type error`, `bytecode error`, `runtime error`)
and, where useful, a hint.

Runtime errors abort the program with exit status 1 and a message such as:

```
main.sc:7:12: runtime error: list index 5 out of range (length 2)
```

Runtime errors include: division/modulo by zero, out-of-range index, missing map
key, calling a native with a wrong runtime type, `assert` failure, exhausted
input, call-stack overflow.

## 10. Not implemented yet

These are **planned**, not present. Do not rely on them:

* generics, enums, pattern matching, structs/records, tuples
* first-class functions, closures, methods on user types
* `async`/`await`, threads, exceptions (`ret`-based error handling only)
* `path`, `time`, `random`, `regex`, `http`, `net`, `process`, `log`, `crypto`,
  `test`, `ai` modules
* Silica UI (styling language, renderer)
* package manager commands (`silica new/add/remove/install/build`)
* self-hosting: the compiler is not written in Silica yet
* native code generation (LLVM/JIT)

## 11. Capabilities

A program starts with **no capabilities**. It can compute, print and read stdin.
Anything that touches the machine is a named capability:

| Capability | Covers |
|---|---|
| `fs.read` | reading a file's contents, and testing whether a path exists |
| `fs.write` | creating or overwriting a file |
| `fs.list` | listing a directory |

A grant is a capability plus a **root path**. A requested path is resolved
(symlinks and `..` collapsed) and must land inside a granted root for that
capability; otherwise the call fails with a capability error.

Capabilities are granted by the host, never by the program: on the command line
(`--allow-fs-read DIR`) or in a `[capabilities]` table in a TOML file passed with
`--capabilities`. `--deny-fs-*` removes a capability even when a root was
granted, and deny always wins. A run has exactly one capability set; every
function called inherits it, and no operation can widen it.

A denial is a located error:

```
main.sc:4: capability error: capability 'fs.read' (read files) is not granted
  hint: grant it with --allow-fs-read <dir>; Silica grants nothing by default
```

This is a language-level rule, not a library convention: the check is applied by
the VM before a privileged function runs.

## 12. Stability

Bytecode format version is `1.0` and is documented in `docs/BYTECODE.md`. The
language surface is `0.x`: breaking changes are allowed before `1.0.0`, and each
one is recorded in `CHANGELOG.md`.

## Structs

A struct is a named record with typed fields.

```silica
struct Point {
    x: Int
    y: Int
}

sfn main() {
    let p = Point(x: 3, y: 4)
    sprint(p.x)              # 3
    sprint(p)                # Point(x: 3, y: 4)
    p.x = 10                 # only if bound with `let`
}
```

### Construction

Fields may be named or positional, and named fields may be given in any order:

```silica
Point(x: 1, y: 2)
Point(1, 2)
Point(y: 2, x: 1)
```

Every field must be supplied exactly once. A missing field, an unknown field, a
duplicate, or a value of the wrong type is a compile-time error that names the
field and lists the real ones.

### Field access and mutation

`p.x` reads a field; `p.x = value` writes one. Both are checked at compile time
against the declared field type, and both work through a path of any depth:

```silica
struct Box {
    corner: Point
    side: Int
}

let b = Box(corner: Point(x: 2, y: 3), side: 4)
b.corner.x = 10          # writes the nested Point's x
sprint(b.corner.x)       # 10
```

A struct bound with `let` is mutable. One bound with `const` is frozen: the
checker rejects a direct assignment, and the runtime rejects one made through an
alias.

```silica
const origin = Point(0, 0)
let alias = origin
alias.x = 1          # runtime error: cannot modify field of a constant struct
```

### Equality and display

Two structs are equal when they have the same type and the same field values.

```silica
Point(1, 2) == Point(1, 2)     # oui
Point(1, 2) == Pair(x: 1, y: 2)  # type error: different types
```

A struct never equals a `Map` with the same contents — the type is part of the
value. `sprint` renders `Point(x: 1, y: 2)`.

### Types and nesting

A struct name is a type: it may be used for fields, parameters, return values and
`let` annotations. Structs may contain other structs.

```silica
struct Rect {
    origin: Point
    width: Int
    height: Int
}
```

A struct cannot contain itself — that has no finite size. Use a `List` instead.

### Limits

* **No generics yet.** A `List` element is `Any`, so field access on one is
  checked at runtime rather than compile time.
* **No methods.** A struct holds data; functions take it as a parameter.
* **No inheritance.** Composition is the model.
* Structs are reference values: passing one to a function passes the same object,
  so a `let` struct modified inside a function stays modified outside it.

