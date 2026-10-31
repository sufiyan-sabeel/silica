# Phase 2 — Classes and Structs: Design Specification

Design for the second phase of the expansion brief. This is the contract the
parser, AST, checker, compiler, verifier, VM and formatter must all agree on, and
it is written **before** the implementation because those six stages have to
change together.

Status: **specification only.** Nothing in this document is implemented yet.
Version stays 0.9.1; no release is implied.

---

## 1. Scope

**In Phase 2:** struct declarations, class declarations, typed fields,
construction, field read/write, instance methods with an implicit `self`,
`private` visibility, `static` methods, structural equality for structs,
identity equality for classes, and a readable printed form.

**Deliberately out of Phase 2** (and stated in the docs as such):

| Deferred | Why |
|---|---|
| Inheritance | The brief asks for "a clearly specified inheritance or composition model". Phase 2 chooses **composition**: a field of another type. Inheritance is a later decision, not an accident. |
| Interfaces / traits | No dispatch mechanism to hang them on until inheritance or dynamic typing exists. |
| Constructors with custom logic | Construction is positional field initialisation. A `init` method with validation arrives with Phase 2b once defaults exist. |
| Field defaults | Every field is initialised by construction, so there is no "uninitialised field" state to reason about. |
| Generics on types | Phase 3. A `Box` that holds `Any` is honest; a fake `Box<T>` is not. |
| Operator overloading, `toString` hooks | `str()` and `sprint()` use one documented representation. |
| Destructors, finalisers | No lifetime model in the VM. |

## 2. Grammar

Two new declaration forms and three new keywords: `struct`, `class`, `private`.
(`static` is a modifier, also new — four keywords total.)

```ebnf
program      = { NEWLINE | use-decl | func-decl | global-decl
               | struct-decl | class-decl } EOF ;

struct-decl  = "struct" IDENT "{" { NEWLINE | field-decl } "}" ;
class-decl   = "class" IDENT "{" { NEWLINE | field-decl | method-decl } "}" ;

field-decl   = [ "private" ] IDENT ":" type NEWLINE ;
method-decl  = [ "private" ] [ "static" ] func-decl ;
```

* A **field** is `name: Type`. There are no field defaults and no `let`/`const`
  keyword — a field declaration is not a binding.
* A **method** is an ordinary `sfn` declaration inside a class body, optionally
  preceded by `private` and/or `static`.
* Structs hold fields only; a `sfn` inside a struct is a parse error with a hint
  ("use a class if you need behaviour").
* Declarations appear at the top level, like `sfn` and `use`. No nested types.

### Expressions: nothing new

Field access and method calls already parse — `p.x` is a member expression and
`c.inc()` is a call whose callee is a member. Phase 2 gives those forms meaning;
it does not add syntax.

### Worked examples

```silica
struct Point {
    x: Int
    y: Int
}

class Counter {
    value: Int
    private label: String

    sfn add(amount: Int) -> Int {
        self.value = self.value + amount
        ret self.value
    }

    sfn describe() -> String {
        ret self.label + " = " + str(self.value)
    }

    static sfn zero(label: String) -> Counter {
        ret Counter(0, label)
    }
}

sfn main() {
    let p: Point = Point(3, 4)
    sprint(p.x + p.y)                 # 7
    p.x = 10                          # struct fields are mutable too
    sprint(p)                         # Point { x: 10, y: 4 }

    let c: Counter = Counter(0, "hits")
    sprint(c.add(2))                  # 2
    sprint(c.describe())              # hits = 2
    sprint(Counter.zero("fresh"))     # Counter { value: 0, label: fresh }
}
```

## 3. Semantics

**Construction.** `Name(args…)` builds an instance. Arguments are positional and
must match the declared field count and types exactly, in declaration order. There
is no `new` keyword: a type name used as a call is construction, which keeps the
call syntax uniform. `Point(1)` is a compile error naming the missing field.

**Fields.** Read with `obj.field`, written with `obj.field = value` (an
assignment statement, already in the grammar). A `private` field is readable and
writable only inside a method of its own class. Writing a value of the wrong type
is a compile error.

**Methods.** `sfn` inside a class body. The receiver is bound to `self` inside the
body; `self` is an ordinary identifier, not a keyword, and cannot be reassigned.
A method may read and write `self`'s fields, including private ones, and call
other methods on `self`. Methods dispatch on the receiver's class at run time.

**Statics.** `static sfn` has no `self`, is called as `Type.name(args…)`, and
cannot touch instance fields (compile error).

**Equality.** Structs compare **structurally**: `Point(1, 2) == Point(1, 2)` is
`oui`. Classes compare by **identity**: two `Counter(0, "a")` values are not
equal unless they are the same instance. This is a deliberate distinction, not an
inconsistency: a struct is a value, a class is an object with state that methods
mutate.

**Printing.** `sprint` / `str` render `Type { field: value, … }` with fields in
declaration order, values rendered as `sprint` renders them. Nested instances
nest. There is no cycle detection: a self-referencing structure would recurse
until the depth limit, and that is documented rather than silently truncated.

**Mutability.** Both struct and class instances are mutable, and assignment copies
nothing — `let q: Point = p` binds the same instance. Value semantics (copy on
assign) is **not** claimed in Phase 2.

## 4. Bytecode and VM

Four new opcodes. Field and method names are string constants, so the verifier can
check them without a symbol table and a native can never be confused for a field.

| Opcode | Operands | Stack effect | Meaning |
|---|---|---|---|
| `NEW` | type-name const, argc | `argc → 1` | Pop `argc` values, build an instance of the named type, push it. |
| `GET_FIELD` | field-name const | `1 → 1` | Pop instance, push field value. |
| `SET_FIELD` | field-name const | `2 → 0` | Pop value and instance, store. |
| `CALL_METHOD` | method-name const, argc | `argc + 1 → 1` | Pop `argc` args and the receiver, dispatch by name, push result. |

**Instance representation.** A new VM value kind holding the type name and a
field map. `type_name()` returns the declared type name, so `type_of(p)` is
`"Point"`. Instances are opaque to every existing opcode: arithmetic, comparison
and indexing on an instance are runtime errors that name the type.

**Verifier rules.** For each new opcode: the constant index is in range and holds
a **String**; `argc` is non-negative and within a limit; the stack effect is
consistent at every join. `NEW` additionally checks that `argc` equals the
declared field count, which the compiler embeds in the constant pool alongside the
name (a `NEW` with the wrong arity is rejected before execution). `CALL_METHOD`
cannot be arity-checked statically — dispatch is dynamic — so the checker enforces
arity and types at compile time and the VM raises a located error on a mismatch.

**Format version.** New opcodes mean a **minor bump to 1.1**. The reader accepts
any `1.x`, so **1.0 files keep loading and running** — that must be proven by a
test that ships a 1.0 byte string. Files produced by 1.1 will not load in a 0.9.1
engine, which is expected and is stated in `docs/BYTECODE.md`.

**Type metadata.** `TYPE_TAGS` stays at its eight entries: a user type in a
function signature serialises as `Any` in the bytecode's informational metadata.
The static checker remains the authority on types; the VM does not need the tag.

## 5. Type checker

* A per-program **type registry** of declared structs and classes, with their
  fields (name, type, visibility) and methods (name, params, return type,
  visibility, static flag). Declarations are collected before bodies are checked,
  so declaration order does not matter.
* Type names become valid annotations: `let p: Point = Point(1, 2)`.
  `BUILTIN_TYPES` stays the built-in set; user types are added per program.
* Member resolution on an instance type: field, then method, then a diagnostic.
* Diagnostics (all with locations, and a suggestion where a near match exists):

| Code | Situation | Message |
|---|---|---|
| E20 | unknown type | `unknown type 'Piont' (did you mean 'Point'?)` |
| E21 | construction arity | `Point expects 2 arguments (x: Int, y: Int), got 1` |
| E22 | construction type | `argument 2 of Point must be Int, found String` |
| E23 | unknown member | `Point has no member 'z' (did you mean 'x'?)` |
| E24 | private access | `'label' is private to Counter` |
| E25 | static misuse | `Counter.add is an instance method; call it on an instance` |
| E26 | `self` outside a method | `'self' is only available inside a method` |
| E27 | method in a struct | `struct Point cannot declare methods; use a class` |
| E28 | duplicate field/method | `'x' is declared twice in Point` |
| E29 | static touching a field | `a static method cannot use 'self'` |

## 6. Backward compatibility

**The one breaking change: four new keywords.** `struct`, `class`, `private` and
`static` become reserved, so any existing program using them as identifiers stops
parsing. This is unavoidable for a keyword-based language and is the reason it
needs an explicit decision.

Mitigation and documentation: the checker already reports reserved words with a
hint, the release notes name the four words, and `docs/LANGUAGE_SPEC.md` records
them in the keyword table. A repository-wide check confirms no example, test or
doc sample currently uses them as identifiers before the change lands.

Everything else is additive: new declarations, new opcodes, no change to existing
syntax or semantics, and old bytecode still runs.

## 7. Test plan

| Layer | Tests |
|---|---|
| Parser | struct/class shapes, `private`/`static` modifiers, method in a struct (E27), duplicate field (E28), missing brace |
| Checker | every diagnostic E20–E29, plus valid programs that must *not* error |
| Bytecode | round-trip with the new opcodes; verifier rejects a non-string name constant, a bad `argc`, an out-of-range constant; **a hand-written 1.0 chunk still loads** |
| VM | construction, field read/write, method call and `self` mutation, method calling method, static call, equality (structural vs identity), printing and nesting, `type_of` |
| Integration | a Silica program that models something real (a queue, a vector) end to end |
| Docs | the documentation guard already forces every new native into `STANDARD_LIBRARY.md`; `GRAMMAR.md`, `LANGUAGE_SPEC.md` and `BYTECODE.md` are updated in the same change |
| Regression | the full suite must stay green (currently 887 passed, 7 skipped) |

## 8. Decisions needed before implementation

1. **Keywords** — `struct`, `class`, `private`, `static` as above? They match the
   brief's wording and Silica's brace style. Alternatives considered and rejected:
   `record`/`object` (less familiar), a single `type` keyword (loses the
   value-vs-object distinction the equality rule depends on).
2. **Class equality** — identity (recommended, as specified) or structural for
   both? Identity is what makes mutation-by-method coherent; structural class
   equality would make `==` surprising after a method call.
3. **Statics in Phase 2 or 2b** — included above (recommended: they are cheap once
   methods exist, and `Counter.zero(...)` is the natural way to build a
   preconfigured instance). Say the word and they move to 2b.

## 9. Implementation order (once approved)

1. `tokens.py` (4 keywords) → `ast.py` (2 nodes, field/method records).
2. `parser.py` (2 declarations) + `fmt.py` (round-trip) + parser tests.
3. `bytecode.py`: 4 opcodes, stack effects, verifier rules, minor version 1.1 +
   a 1.0-compatibility test.
4. `vm.py`: the instance value and the 4 opcodes + VM tests.
5. `checker.py`: the type registry, member resolution, E20–E29 + checker tests.
6. `compiler.py`: construction, field access, method compilation (`self` in slot 0),
   static calls.
7. `docs/`: `CLASSES.md` reference, `GRAMMAR.md`, `LANGUAGE_SPEC.md`,
   `BYTECODE.md`; `examples/classes.sc`; `CHANGELOG.md` under *Unreleased*.
8. Full suite, then review the diff before anything is pushed.
