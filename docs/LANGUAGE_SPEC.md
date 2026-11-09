# Silica Language Specification — v0.10.1

**Status:** normative for the v0.10.1 reference implementation
**Applies to:** `silica-lang` 0.10.1 (`sufiyan-sabeel/silica`)
**Document version:** 2.0 · 2026-11-09
**Owner:** Umaiz Sufiyan (creator and maintainer)

This document states the **rules** of the Silica language. Everything in §1–§12 is
implemented and covered by the test suite; §13 classifies every capability,
including the ones that do not exist yet. If this document and the implementation
ever disagree, the implementation is the defect and this document is the contract
— report it rather than adapting the text to the behaviour.

Silica is a small, statically typed, bytecode-compiled language. Source files use
`.sc`, compiled programs use `.sbc`, and the toolchain command is `silica`.

**Where other documents are authoritative.** This specification defines the
language. It does not restate the following, and must not contradict them:

| Topic | Authoritative document |
|---|---|
| Concrete grammar (EBNF) | `docs/GRAMMAR.md` |
| Bytecode container and verifier | `docs/BYTECODE.md` |
| Every standard-library function and its errors | `docs/STANDARD_LIBRARY.md` |
| Generics | `docs/GENERICS.md` |
| Capability model, threat model | `docs/SECURITY_MODEL.md` |
| Python interop protocol | `docs/INTEROPERABILITY.md` |
| UI, TUI and GUI rendering | `docs/UI.md`, `docs/TUI.md`, `docs/GUI.md` |
| Measured performance and its causes | `docs/PERFORMANCE.md` |
| Milestone tracking | `docs/ROADMAP.md` |
| Future platform and Rust VM architecture | `docs/design/SILICA_PLATFORM_ARCHITECTURE.md` |

---

## 1. Source files

A Silica file is UTF-8 text. It contains, in any order:

* `use` declarations,
* `sfn` function declarations,
* `struct` and `class` declarations,
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

| Purpose | Silica | Meaning |
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
| Function | `sfn name(params) -> T { }` | Declare a function, or a method inside a `class`. |
| Return | `ret expr` / `ret` | Return a value from a function. |
| Import | `use module` | Import a standard-library module. |
| End of block | `fin` | Optional explicit block terminator, allowed immediately before `}`. |
| Stop | `halt` / `halt(code)` | Terminate the program with exit code 0 or `code`. |
| Binding | `let x = e` / `const x = e` | Mutable / immutable binding. |
| Record | `struct Name { }` | Declare a value type with named fields. |
| Object | `class Name { }` | Declare a type with fields and methods. |
| Member visibility | `private` | Field or method not visible outside its type. |
| Static method | `static` | Method that does not take `self`. |

Twenty-six words are reserved in total. `self` is not a keyword: it is the
implicit first parameter of a non-`static` method.

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
neither carries a value, and neither is a function. There are no loop labels.

## 3. Values and types

| Type | Meaning |
|---|---|
| `Int` | 64-bit signed integer. |
| `Float` | IEEE-754 double. |
| `Bool` | `oui` / `nein`. |
| `String` | Immutable Unicode text; indexing and length are by code point. |
| `Unit` | The result of statements and `Unit`-returning functions. |
| `List` | Ordered, mutable sequence of values. |
| `Map` | String-keyed dictionary of values, in insertion order. |
| `Any` | Internal wildcard used for unannotated parameters and untyped element access. |
| struct type | A named record with typed fields and reference semantics, e.g. `Point`. |
| class type | A named object with fields and methods, e.g. `Counter`. |
| generic parameter | A type variable in scope inside a generic declaration, e.g. `T`. |

There is no `null`. A function that returns nothing returns `Unit`. There is no
`Result` type yet; see §10 and §17.

`List` and `Map` are containers of *unknown* element type: reading `xs[0]` yields
a value of type `Any`, which is accepted anywhere. That is a documented
limitation of the containers themselves, not of the type system — user-defined
generic types are fully checked (§14).

### 3.1 Numeric rules

* `Int` is 64-bit and **wraps** on overflow (two's complement). `9223372036854775807 + 1` is `-9223372036854775808`.
* An integer **literal** outside that range is a compile error, not a wrap.
* `Int / Int` truncates toward zero: `7 / 2 == 3`, `-7 / 2 == -3`.
* `Int % Int` keeps the sign of the dividend: `-7 % 2 == -1`, `7 % -2 == 1`.
* `Float` follows IEEE-754 for `+ - * /` except that **division or modulo by zero is a runtime error** for both `Int` and `Float` (no silent `inf`).
* Mixing `Int` and `Float` in arithmetic promotes the `Int` to `Float`.
* A `Float` never converts to `Int` implicitly; use `int(x)`. An `Int` may be used where a `Float` is expected.

### 3.2 Equality and ordering

* `==` / `!=` compare structurally for `List` and `Map`, and structurally for structs of the same type.
* `1 == 1.0` is `oui`: numeric equality crosses types.
* `Bool` never equals a number.
* `< <= > >=` work on numbers and on `String` (lexicographic by code point).
* Ordering two different non-numeric types is a compile error.

### 3.3 Truthiness

There is none. Every condition must be `Bool`, so `si x { }` with an `Int` is a
compile error. Write the comparison you mean: `si x != 0 { }`.

### 3.4 String literals

A string literal may use any of four delimiters. The value is the same for all
four; only the quoting rules differ.

There is **no string interpolation**. `"n is {n}"` is the literal text
`n is {n}`; build a line with `+` and `str(...)`, or with `dit` (§2.1).

### 3.5 Unicode

Strings are sequences of Unicode **code points**, not bytes and not grapheme
clusters:

| Expression | Value |
|---|---|
| `len("héllo")` | `5` |
| `len("😀")` | `1` |
| `len("e" + U+0301)` | `2` — a combining mark is its own code point |
| `"héllo"[1]` | `é` |
| `"abc"[-1]` | runtime error: `string index -1 out of range (length 3)` |

There is no slicing (`s[1:3]` is a parse error) and no normalisation.

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

**No element assignment.** `xs[i] = v` and `m[k] = v` are parse errors; use
`push` and the collection functions. Indexing is read-only.

## 6. Functions

```
sfn add(a: Int, b: Int) -> Int {
    ret a + b
}
```

* Parameter type annotations are optional; an unannotated parameter has type `Any`.
* `-> T` gives the return type; without it the function returns `Unit`.
* Functions are declared at the top level; methods are declared inside a `class` (§15).
* Functions are **not first-class values**: they can be called, not stored, passed or returned. There are no closures.
* A function with a non-`Unit` return type must return on **every** path, which
  the checker verifies (`si`/`sino` where both branches return counts).
* `main` takes no parameters. Recursion is supported; the call depth is limited
  (4096 frames by default) and exceeding it is a runtime error.
* Generic functions exist and are checked (§14).

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

**Implemented modules (29).** Grouped by domain; `docs/STANDARD_LIBRARY.md` lists
every function.

| Domain | Modules |
|---|---|
| Core | `core` |
| Data | `collections`, `json`, `string` |
| Text, time, numbers | `path`, `time`, `random`, `math` |
| Filesystem | `fs` |
| Colour | `colors` |
| Web UI | `ui`, `ui.state`, `ui.lib.widgets`, `ui.lib.theme`, `ui.lib.colors`, `ui.lib.layout`, `ui.lib.scroll`, `ui.lib.animation` |
| Terminal UI | `tui`, `tui.lib.widgets`, `tui.lib.style`, `tui.lib.layout` |
| Desktop GUI | `gui`, `gui.lib.widgets`, `gui.lib.theme`, `gui.lib.layout` |
| Speech | `speech`, `voice` |
| Interop | `python` |

Module paths may be dotted (`use ui.lib.widgets`). Importing a module also brings
its submodules into scope. In a member chain the longest prefix that names an
imported module is the module, and exactly one member may follow it.

Modules reserved in the plan but **not implemented** — `http`, `net`, `regex`,
`process`, `log`, `crypto`, `test`, `ai`, `async` — fail loudly: importing one is
a compile error that names it. There is no third state between implemented and
refused.

`fs` and the UI/speech modules reach outside the engine and are guarded by the
capability model (§11).

## 8. Output formatting

`sprint` and `dit` render values as follows:

| Value | Output |
|---|---|
| `Int` | decimal digits, e.g. `42` |
| `Float` | shortest round-trip form with a decimal point, e.g. `1.5`, `2.0`, `0.30000000000000004` |
| `Bool` | `oui` / `nein` |
| `String` | as-is, unquoted |
| `List` | `[1, 2, 3]` — nested strings are quoted |
| `Map` | `{"a": 1}` |
| struct | `Point(x: 3, y: 4)` |
| class instance | the type name and its fields |
| `Unit` | `unit` |

Float formatting is Python's shortest round-trip representation with a two-digit
minimum exponent (`1e-07`). `-0.0` prints as `-0.0`. `inf` and `nan` are
reachable only through `float(String)`; arithmetic cannot produce them, because
division by zero is an error.

## 9. Errors

Every diagnostic carries `file:line:column` where available, a category
(`lex error`, `parse error`, `type error`, `capability error`, `bytecode error`,
`runtime error`) and, where useful, a hint.

Runtime errors abort the program with exit status 1 and a message such as:

```
main.sc:7:12: runtime error: list index 5 out of range (length 2)
  hint: check the length with 'len' before indexing
```

Runtime errors include: division/modulo by zero, out-of-range index, missing map
key, calling a native with a wrong runtime type, `assert` failure, exhausted
input, call-stack overflow, and a denied capability.

A programming error is never catchable and never recoverable: there are no
exceptions and no `try`. Recoverable I/O is expected to become `Result`-shaped
(§17), which is a design decision recorded but **not implemented**.

## 10. Capabilities

A program starts with **no capabilities**. It can compute, print and read stdin.
Anything that touches the machine is a named capability, and there are nine:

| Capability | Covers |
|---|---|
| `fs.read` | reading a file's contents, and testing whether a path exists |
| `fs.write` | creating or overwriting a file |
| `fs.list` | listing a directory |
| `tui.run` | running a terminal UI |
| `gui.run` | opening a desktop window |
| `speech.speak` | text-to-speech |
| `speech.listen` | microphone capture and recognition |
| `speech.models` | reading or writing downloaded voice models |
| `interop.python` | calling into a Python worker process |

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
the VM before a privileged function runs, at a single dispatch point. See
`docs/SECURITY_MODEL.md` for what the model does **not** guarantee.

## 11. Stability and compatibility

Bytecode format version is `1.0` and is documented in `docs/BYTECODE.md`. The
language surface is `0.x`: breaking changes are allowed before `1.0.0`, and each
one is recorded in `CHANGELOG.md`.

Compatibility rules, in force from 0.10.x:

1. **Existing valid programs stay valid.** A change that makes a working program
   fail to compile, or changes what it prints, is a breaking change and needs a
   `CHANGELOG.md` entry.
2. **Additive by default.** New keywords, new syntax and new required
   annotations are avoided; new capability arrives as new declarations, new
   built-ins or new modules.
3. **No silent semantic change.** Changing the meaning of an operator, a
   conversion or a formatting rule is breaking even when it looks like a fix,
   and is recorded as such.
4. **Bytecode is versioned, not guessed.** `FORMAT_MAJOR` changes only for an
   incompatible layout; a reader that does not understand a file rejects it
   rather than misreading it.
5. **A defect fix may change output** when the old output was wrong — for
   example the constant-pool interning fix that made `0.0 - 0.0` print `0.0`
   rather than `-0.0`. Such a change is documented as a bugfix, with the old and
   new behaviour stated.

## 12. Syntax preservation policy

This section constrains the maintainers, not the programmer.

1. Existing keywords are never renamed or repurposed (`sfn`, `let`, `const`,
   `si`, `sino`, `tant`, `per`, `ret`, `use`, `oui`, `nein`, `und`, `ou`, `non`,
   `sprint`, `dit`, `input`, `halt`, `fin`, `break`, `continue`, `struct`,
   `class`, `private`, `static`, `in`).
2. The grammar is not redesigned. New productions are added only where they are
   unambiguous against the existing ones.
3. Silica does not adopt Python, JavaScript or Rust syntax. Inspirations are
   capability-level: Python for readability and data structures, JavaScript for
   asynchronous and event-driven work, Rust for memory safety and performance.
   The spelling stays Silica's.
4. `docs/GRAMMAR.md` is updated in the same change as any grammar change.
5. A proposal that requires breaking rule 1, 2 or 3 is rejected or deferred, not
   softened into the language.

---

## 13. Feature status

Every capability carries exactly one status. This vocabulary is used across all
Silica documentation, and the statuses below were checked against the
implementation at v0.10.1, not inferred from the roadmap.

| Status | Meaning |
|---|---|
| **IMPLEMENTED** | Verified in the current repository, with tests. |
| **PARTIALLY IMPLEMENTED** | Exists, with a documented limitation. |
| **PLANNED** | Approved direction, designed or scheduled, not present. |
| **PROPOSED** | Design idea requiring evaluation; may never ship. |
| **NOT SUPPORTED** | Deliberately absent; no plan. |

### 13.1 Language core

| Capability | Status | Note |
|---|---|---|
| Static type checking with inference from initialisers | IMPLEMENTED | §5 |
| `let` / `const`, scopes, globals | IMPLEMENTED | §5 |
| `si` / `sino`, `tant`, `per`, `break`, `continue` | IMPLEMENTED | §5 |
| Functions, recursion, `ret` | IMPLEMENTED | §6 |
| 64-bit wrapping `Int`, IEEE-754 `Float`, `Bool`, `String`, `List`, `Map`, `Unit` | IMPLEMENTED | §3 |
| Structs with structural equality and `const` freezing | IMPLEMENTED | §16 |
| Classes: fields, `private`, methods, `static` methods | IMPLEMENTED | §15 |
| Generics on functions and structs | IMPLEMENTED | §14 |
| Generic `List<T>` / `Map<K,V>` element typing | NOT SUPPORTED | containers are `Any`-typed; a documented limitation |
| First-class functions, closures | PLANNED | designed in `docs/design/SILICA_PLATFORM_ARCHITECTURE.md` §13 |
| `async` / `await`, event loop | PLANNED | deferred until after closures |
| Exceptions (`try` / `catch`) | NOT SUPPORTED | the recorded decision is `Result` for recoverable failures, aborts for programming errors |
| `Result` / recoverable error values | PLANNED | decision recorded; no syntax or type yet |
| Enums | NOT SUPPORTED | no plan; `const` `Int`/`String` values are the current idiom |
| Tuples | NOT SUPPORTED | use a struct |
| Pattern matching | NOT SUPPORTED | `si`/`sino` chains are the current idiom |
| Optional / nullable types (`T?`) | NOT SUPPORTED | there is no `null` (§3) |
| Slicing (`s[a:b]`) | NOT SUPPORTED | no plan |
| Element assignment (`xs[i] = v`) | NOT SUPPORTED | use `push` and collection functions |
| Negative indexing | NOT SUPPORTED | index errors instead |
| Labelled `break` / `continue` | NOT SUPPORTED | they target the innermost loop |
| String interpolation | NOT SUPPORTED | `"a {x}"` is literal text (§3.4) |
| Operator overloading | NOT SUPPORTED | `+` is fixed for `Int`/`Float`/`String`/`List` |
| Traits / interfaces / inheritance | NOT SUPPORTED | classes do not inherit |
| Modules written by the user | NOT SUPPORTED | `use` resolves built-ins only |
| Traits, macros, comptime, reflection | NOT SUPPORTED | no plan |

### 13.2 Execution and tooling

| Capability | Status | Note |
|---|---|---|
| Tree-walking-free stack VM over verified bytecode | IMPLEMENTED | `silica/vm.py`, `docs/BYTECODE.md` |
| `.sbc` format 1.0: magic, version, CRC-32, constant pool, line table | IMPLEMENTED | `docs/BYTECODE.md` |
| Bytecode verifier: opcodes, operands, jump targets, arities, stack depth, limits | IMPLEMENTED | rejects before execution |
| 43 opcodes, all implemented | IMPLEMENTED | `NOP` (0x00) executes since PR #8, merged after the 0.10.1 release |
| REPL with persistent globals | IMPLEMENTED | `silica repl` |
| `run`, `check`, `compile`, `fmt`, `test`, `repl`, `capabilities`, `voice`, `ide` | IMPLEMENTED | `silica --help`; there is no `dis` or `verify` command |
| Formatter (AST-based; refuses files containing comments) | PARTIALLY IMPLEMENTED | comments are preserved by refusal, not by the formatter |
| Browser IDE (Script Mode) | IMPLEMENTED | `docs/IDE.md` |
| Debugger with breakpoints and stepping | NOT SUPPORTED | line tables exist; nothing consumes them |
| Native code generation (LLVM/JIT/AOT) | PLANNED | `docs/design/SILICA_PLATFORM_ARCHITECTURE.md` |
| WebAssembly back end | PROPOSED | requires a feasibility prototype before approval |
| Rust VM (second implementation of the same bytecode) | PLANNED | designed, gated on a toolchain; `docs/design/SILICA_R1_*` |
| Self-hosting the compiler in Silica | PLANNED | `docs/BOOTSTRAP.md` |
| Standalone binary without CPython | PLANNED | blocked on a non-Python runtime |

### 13.3 Library and platform

| Capability | Status | Note |
|---|---|---|
| 29 modules, 316 built-in functions | IMPLEMENTED | §7 |
| Filesystem behind capabilities | IMPLEMENTED | `fs.read` / `fs.write` / `fs.list` |
| JSON encode/decode with located errors | IMPLEMENTED | |
| Colour science (OKLab/OKLCH/P3, WCAG audit, CSS output) | IMPLEMENTED | `docs/COLOR.md` |
| Web UI rendering (HTML/CSS + declarative JS action runtime) | IMPLEMENTED | `docs/UI.md` |
| Silica logic executing in the browser | NOT SUPPORTED | event bodies are declarative action lists, not code |
| Terminal UI | IMPLEMENTED | `docs/TUI.md`, capability `tui.run` |
| Desktop GUI (tkinter) | PARTIALLY IMPLEMENTED | one window, 22 functions, handlers by name |
| Speech synthesis and recognition | PARTIALLY IMPLEMENTED | requires models on disk; capabilities `speech.*` |
| Python interop (worker process, JSON frames, opaque handles) | IMPLEMENTED | `docs/INTEROPERABILITY.md` |
| Networking, HTTP, TLS | NOT SUPPORTED | modules reserved and refused |
| Cryptography | NOT SUPPORTED | modules reserved and refused |
| Threads, parallelism, task scheduling | NOT SUPPORTED | the VM is single-threaded |
| Package manager, registry, lockfile | PLANNED | decision recorded: lockfile + pinned commits + checksums, no registry |
| Cross-platform: Linux, macOS, Windows via CPython | IMPLEMENTED | `docs/INSTALL.md` |
| Android / Termux | PARTIALLY IMPLEMENTED | documented install path; no APK, no embedding |
| iOS | NOT SUPPORTED | no plan |
| Operating-system development | NOT SUPPORTED | out of scope; see §20 |

---

## 14. Generics

Generic declarations are checked, not erased at the source level: a type argument
must satisfy the declaration's use of it, and a mismatch is a compile error. See
`docs/GENERICS.md` for the full rules.

```
struct Box<T> {
    v: T
}

sfn id<T>(x: T) -> T {
    ret x
}

sfn main() {
    let b: Box<Int> = Box(v: 1)
    sprint(b.v)
    sprint(id("x"))
}
```

The built-in containers are the exception: `List` and `Map` elements are `Any`
(§3), so element types are not checked until they are annotated or converted.

## 15. Classes

A class has fields, optional `private` fields, methods and `static` methods.
`self` is the implicit first parameter of a non-`static` method; it is not a
keyword and is not written in the parameter list.

```
class Counter {
    v: Int
    private label: String

    sfn add(n: Int) -> Int {
        self.v = self.v + n
        ret self.v
    }

    static sfn zero(label: String) -> Counter {
        ret Counter(0, label)
    }
}

sfn main() {
    let c: Counter = Counter.zero("hits")
    sprint(c.add(2))          # 2
}
```

There is no inheritance, no interfaces and no method overriding. A `private`
member is not visible outside its type, including to a free function.

## 16. Structs

A struct is a record type with named, typed fields and **reference semantics**:
a `let` binding aliases the record, so a write through one alias is visible
through another. A `const` binding and a function parameter are frozen views.
See the appendix for the complete rules.

---

## 17. Error-handling principles

These are the rules the language is being held to, with their current status.

1. **A programming error aborts.** Wrong types, out-of-range index, missing map
   key, division by zero and call-stack overflow are diagnosed and stop the
   program. They are not catchable. *(IMPLEMENTED)*
2. **Every diagnostic is located and actionable.** `file:line:col`, a category,
   and a hint where the fix is mechanical. *(IMPLEMENTED)*
3. **No silent failure.** A refused operation raises; it never returns a
   plausible-looking value. *(IMPLEMENTED)*
4. **Recoverable failure will be a value, not an abort.** File-missing,
   permission-denied, connection-refused, timeout and malformed peer input will
   return a `Result`-shaped value with a stable machine-readable code.
   *(PLANNED — decision recorded, no type or syntax yet)*
5. **No exceptions.** Adding `try`/`catch` was considered and rejected; a
   `Result` value keeps the failure visible at the call site. *(decision)*
6. **A capability denial is a language-level error**, reported like any other,
   never a silent empty result. *(IMPLEMENTED)*

## 18. Memory and resource safety

Silica has no pointers, no manual allocation and no explicit free. Safety comes
from what the language cannot express:

| Property | How it holds today | Status |
|---|---|---|
| No use-after-free | values are never addressable; nothing outlives a reference the language can form | IMPLEMENTED (by construction) |
| No null dereference | there is no `null` | IMPLEMENTED |
| No buffer overflow | there is no unchecked memory access; index errors are diagnosed | IMPLEMENTED |
| No data races | the VM is single-threaded; there are no threads to race | IMPLEMENTED |
| Bounded recursion | explicit frames, 4096 by default, overflow is a diagnosed error | IMPLEMENTED |
| Bounded bytecode | constant, function, local, stack and code-size limits, checked on load | IMPLEMENTED |
| Deterministic release of files and handles | capability-checked calls return values, not handles the program can leak | PARTIALLY IMPLEMENTED |
| Ownership and borrowing guarantees comparable to Rust | would require a compile-time ownership model; **not promised** | NOT SUPPORTED |

The last row matters: Silica's safety is *memory-safety by absence of unsafe
constructs*, not Rust's ownership discipline. This document does not claim
Rust-equivalent guarantees, and a future Rust-hosted VM would inherit the same
language-level model rather than adding borrow checking to the surface language.

## 19. Runtime and execution architecture

| Mode | Status | Semantics |
|---|---|---|
| Interpreter over `.sbc` (the reference VM, written in Python) | IMPLEMENTED | the definition of every rule in this document |
| Bytecode compilation to `.sbc` | IMPLEMENTED | format 1.0, verified on load |
| Native compilation | PLANNED | must reproduce this document exactly; measured, never assumed |
| WebAssembly | PROPOSED | requires a prototype and a comparison before approval |

Rules that any additional execution mode must satisfy:

1. **One semantics.** A second implementation reproduces the reference VM's
   observable behaviour: stdout, stderr including hints, and exit codes, byte for
   byte. A disagreement is a bug in the new implementation.
2. **The reference stays the oracle.** The Python VM is not retired when another
   engine ships; it is how a disputed case is adjudicated.
3. **Same bytecode.** A new engine consumes the `.sbc` the existing compiler
   produces. No recompilation, no format fork.
4. **Deterministic.** Same input, same output, no timing-dependent behaviour.
5. **Measured, not claimed.** Any performance statement is a measurement with the
   workload, the machine and the method stated.

## 20. Concurrency model

**Today the language is single-threaded.** There is no `async`, no `await`, no
threads, no parallelism and no task scheduling; a program that needs to wait,
waits. The `async` module is reserved and refused.

The intended direction, recorded and **not implemented**:

1. `async`/`await` as the user-facing model, on a single-threaded event loop.
2. Function values and closures first — they are the prerequisite, because an
   event handler is a function value.
3. Structured concurrency: a task cannot outlive the scope that started it.
4. No shared mutable state across tasks without an explicit synchronisation
   primitive; message passing over shared memory.
5. Parallelism only where the runtime can actually provide it. No promise of
   threads on a platform that cannot deliver them.

## 21. Standard-library architecture

1. **A module is implemented or refused.** There is no third state: a module
   either works, is documented and tested, or it is in the refused list and
   importing it is a compile error that names it (§7).
2. **Capabilities are declared per function.** A built-in that touches the
   machine declares its capability; 281 of 316 declare none.
3. **`core` is always present**; everything else needs `use`.
4. **Errors are located.** A built-in failure reports `file:line:col` and a hint
   where the fix is mechanical.
5. **No hidden I/O.** A function that reads, writes, opens a window or speaks
   declares a capability; nothing else reaches outside the process.
6. **Growth order** is set by the roadmap: `process`/`log`, then `net`/`http`,
   then `crypto`, then the async model, then `regex`, then `test`.

## 22. Security principles

| Principle | Status |
|---|---|
| Deny by default: a program starts with no capabilities | IMPLEMENTED |
| Capability checks at a single VM dispatch point, before the function runs | IMPLEMENTED |
| Path containment: symlinks and `..` resolved, must land inside a granted root | IMPLEMENTED |
| Deny always wins over grant | IMPLEMENTED |
| A program cannot grant itself a capability | IMPLEMENTED |
| No hidden code execution: nothing is `eval`'d, nothing is unpickled | IMPLEMENTED |
| Interop values are opaque handles, never host objects | IMPLEMENTED |
| Bytecode is verified before execution, with size and depth limits | IMPLEMENTED |
| Package integrity (checksums, pinned commits) | PLANNED |
| Sandboxing against a hostile host | NOT SUPPORTED — **the VM is not an OS sandbox** |

The last row is not a gap to be closed by documentation: capability checks stop a
*program* from asking for a file. They do not contain a malicious engine build and
they are not an operating-system boundary. `docs/SECURITY_MODEL.md` is
authoritative on the limits.

## 23. Developer ecosystem

| Tool | Status | Note |
|---|---|---|
| Compiler diagnostics with locations and hints | IMPLEMENTED | §9 |
| Formatter (`silica fmt`, `--check`) | PARTIALLY IMPLEMENTED | AST-based; refuses files with comments |
| Test runner (`silica test` over `*_test.sc`) | IMPLEMENTED | |
| Browser IDE | IMPLEMENTED | `docs/IDE.md` |
| Capability inspector (`silica capabilities`) | IMPLEMENTED | |
| Documentation generator | NOT SUPPORTED | the docs are hand-written |
| Language Server Protocol | NOT SUPPORTED | no plan yet |
| Editor integration beyond the browser IDE | NOT SUPPORTED | |
| Debugger | NOT SUPPORTED | line tables exist |
| Package manager | PLANNED | `silica new/add/install/build` do not exist |
| Reproducible builds | PARTIALLY IMPLEMENTED | deterministic artefacts tested; no lockfile yet |

## 24. Cross-platform strategy

| Platform | Status | What actually works |
|---|---|---|
| Linux (x86_64, ARM64) | IMPLEMENTED | full toolchain via CPython 3.9+ |
| macOS | IMPLEMENTED | same, via CPython |
| Windows | IMPLEMENTED | same, via CPython |
| Termux (Android, ARM64) | PARTIALLY IMPLEMENTED | install path documented in `docs/INSTALL.md`; no APK and no embedded runtime, so "supported" means "runs under Termux's CPython" |
| Other Android forms | NOT SUPPORTED | would need an embedding strategy |
| iOS | NOT SUPPORTED | no plan |
| WebAssembly | PROPOSED | needs a prototype |
| Standalone binary, no Python installed | NOT SUPPORTED | requires a non-Python runtime |

The single dependency is CPython ≥ 3.9. There is no compiled component, so
"supported platform" means "a platform with a supported CPython", and that is the
honest boundary of the claim.

## 25. Language identity and design philosophy

Silica is a **general-purpose, statically typed, multi-paradigm** language with a
bytecode compiler, a verifying loader and a capability-based security model. It
is not a scripting dialect of Python, not a JavaScript runtime and not a Rust
subset.

The ten design principles, in priority order when they conflict:

1. **Readability over unnecessary complexity.**
2. **Consistency over feature count.**
3. **Safety by default** — no capability unless granted, no `null`, no unchecked
   memory.
4. **Predictable execution** — no truthiness, no implicit conversions that
   surprise, no hidden I/O.
5. **Explicit over implicit** — a capability is named, an error is located, a
   type is written where inference would guess.
6. **Performance without changing behaviour** — an optimisation that alters
   output is a bug, not an optimisation.
7. **Backward compatibility** (§11).
8. **Minimal syntax duplication** — one way to say a thing; `sprint`/`dit` differ
   because their behaviour differs.
9. **Deterministic semantics** — same program, same output, including map order
   and float formatting.
10. **Developer experience** — a diagnostic that says what to do next.

Inspirations, at capability level only:

| From | What Silica takes | What it does not take |
|---|---|---|
| Python | readability, high-level data structures, a usable standard library, good error messages | indentation-significant blocks, dynamic typing, implicit truthiness |
| JavaScript | asynchronous and event-driven programming as a goal, flexible application building | prototype chains, implicit coercion, `null`/`undefined` |
| Rust | memory safety as a default, explicit failure, performance discipline, an ownership-minded runtime | borrow-checker syntax, lifetimes in the surface language, traits |

## 26. Roadmap

`docs/ROADMAP.md` tracks milestones and their real status; this section states
only the order the language requires, because some capabilities are prerequisites
of others.

| Order | Capability | Why this order |
|---|---|---|
| 1 | `Result`-shaped error values | every I/O module needs it; it changes no existing program |
| 2 | First-class functions and closures | prerequisite for events, handlers and the async model |
| 3 | `async`/`await` on a single-threaded loop | built on function values, not before them |
| 4 | Package manager with lockfile and pinned commits | no registry; integrity before ecosystem |
| 5 | Native execution (measured Rust VM, or native codegen) | performance and portability, gated on measurement |
| 6 | WebAssembly | after a prototype proves the compiler can target it |
| 7 | Platform backends (desktop packaging, Android) | last, because each needs the runtime that precedes it |

Nothing in this table may be started before the one above it is settled, and no
item may break §11 or §12.

## 27. Acceptance rules for future changes

A change to the language is accepted only when all of these hold:

1. Existing valid programs still compile and still print what they printed,
   unless the change is a recorded breaking change.
2. `docs/GRAMMAR.md`, this specification and `docs/STANDARD_LIBRARY.md` are
   updated in the same change.
3. A test covers the new behaviour, and a test covers the refusal where the
   change adds an error.
4. The capability model is not widened by accident: a new built-in that reaches
   outside the process declares a capability.
5. No feature is documented as implemented before it is.
6. The `.sbc` format is either unchanged or bumped with the verifier updated in
   the same commit.

---

# Appendix A — Structs

A struct declares a record type with named, typed fields.

```
struct Point {
    x: Int
    y: Int
}
```

## Construction

```
let p: Point = Point(x: 3, y: 4)
```

Fields may be given by name or positionally, and named fields may be written in
any order — all three forms below build the same value:

```silica
Point(x: 1, y: 2)
Point(1, 2)
Point(y: 2, x: 1)
```

Every field must be supplied exactly once. A missing field, an unknown field, a
duplicate, or a value of the wrong type is a compile-time error that names the
field and lists the real ones.

## Field access and mutation

`p.x` reads a field and `p.x = value` writes one, at any depth
(`b.corner.x = 10`). A struct is a **reference to a record**, not a copy, so two
`let` bindings to the same struct alias it:

```silica
let a = Point(x: 1, y: 1)
let b = a
b.x = 5
sprint(a.x)      # 5 — the same record
```

A `const` binding is frozen: the checker rejects a direct assignment, and the
runtime rejects one made through an alias. A **function parameter is also
frozen**, so a function cannot mutate the caller's record through its parameter.

## Equality and display

Two structs of the same type are equal when every field is equal (`==` is
structural). A struct prints as `Point(x: 3, y: 4)`. A struct never equals a
`Map` with the same keys.

## Types and nesting

A field may be any type, including another struct, a `List`, a `Map` or a type
parameter (§14). Structs may be nested to any depth the stack allows.

## Limits

* **Generic structs exist** (§14). The built-in `List`/`Map` remain `Any`-typed,
  so field access on an element read out of one is checked at run time.
* **No methods on structs.** A struct holds data; methods are what a class is for
  (§15).
* **No inheritance.** A class cannot extend another class; composition is the model.
* **No self-containment.** A struct cannot contain itself — `struct R { child: R }`
  is rejected with "cannot contain itself". Use a `List`.
* **Reference semantics.** Two `let` bindings to one struct alias it; a `const`
  binding and a function parameter are frozen views.
