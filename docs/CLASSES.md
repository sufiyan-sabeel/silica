# Structs and Classes

Silica has two ways to group named data: `struct` (a value) and `class` (an
object with behaviour). Both are declared at the top level, both have typed
fields, and both are constructed by calling the type name.

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

    static sfn zero(label: String) -> Counter {
        ret Counter(0, label)
    }
}

sfn main() {
    let p: Point = Point(3, 4)
    sprint(p.x + p.y)            # 7
    p.x = 10
    sprint(p)                    # Point { x: 10, y: 4 }

    let c: Counter = Counter.zero("hits")
    sprint(c.add(2))             # 2
}
```

## Struct or class?

| | `struct` | `class` |
|---|---|---|
| Fields | yes | yes |
| Methods | no (a `sfn` inside a struct is a parse error) | yes |
| `private` fields | no (nothing could read them) | yes |
| `==` | **structural** — `Point(1, 2) == Point(1, 2)` is `oui` | **identity** — two equal-looking instances are `nein` unless they are the same object |
| Use it for | coordinates, records, small immutable-ish data | things with state that methods change |

The equality difference is deliberate, not an inconsistency: a struct is a
*value*, so two structs with the same fields are the same value. A class is an
*object*, so `==` asks "is this the same object?", which is the only answer that
stays true after a method mutates it.

## Declarations

```ebnf
struct-decl = "struct" IDENT "{" { NEWLINE | field-decl } "}" ;
class-decl  = "class" IDENT "{" { NEWLINE | field-decl | method-decl } "}" ;
field-decl  = [ "private" ] IDENT ":" type NEWLINE ;
method-decl = [ "private" ] [ "static" ] func-decl ;
```

* A field is `name: Type`. There are no defaults and no `let`/`const` — a field
  declaration is not a binding.
* A method is an ordinary `sfn` inside a class body.
* Declarations are top level, like `sfn` and `use`. Types may reference each
  other in any order: `struct Node { next: Point }` works with `Point` declared
  below `Node`.

## Construction

`Name(args…)` builds an instance. Arguments are positional, in **field
declaration order**, and must match the field count and types exactly. There is
no `new` keyword: a type name used as a call is construction.

```silica
let p: Point = Point(3, 4)      # x = 3, y = 4
Point(3)                        # error: expects 2 arguments (x: Int, y: Int)
Point(3, "four")                # error: argument 2 must be Int, found String
```

## Fields

Read with `obj.field`, write with `obj.field = value`. A `private` field is
readable and writable only inside a method of its own class.

```silica
class Counter {
    value: Int
    private label: String
    sfn rename(new_label: String) {
        self.label = new_label       # allowed: same class
    }
}

let c: Counter = Counter(0, "a")
c.value                          # fine
c.label                          # error: 'label' is private to Counter
c.value = 5                      # fine
```

## Methods and `self`

Inside a method the receiver is bound to `self`: an ordinary identifier (not a
keyword) that cannot be reassigned. A method may read and write `self`'s fields —
including private ones — and call other methods on `self`.

```silica
sfn double() -> Int {
    ret self.base * 2
}

sfn quadruple() -> Int {
    ret self.double() * 2        # methods may call methods
}
```

Dispatch is by method name on the receiver's type at run time, so two classes may
each have a `describe()` method without interfering.

## Static methods

`static sfn` has no `self`, is called as `Type.name(args…)`, and cannot touch
instance fields. They are the natural way to build a preconfigured instance:

```silica
class Queue {
    tickets: List
    private next_id: Int
    static sfn empty() -> Queue {
        ret Queue([], 0)
    }
}

let q: Queue = Queue.empty()
```

Calling a static on an instance, or an instance method on the type, is an error
that says which one you wrote.

## Printing and `type_of`

`sprint` / `str` render `Type { field: value, … }` in declaration order, and
nested instances nest:

```silica
sprint(Ticket(1, "write the docs", oui))
# Ticket { id: 1, title: write the docs, open: oui }
```

`type_of` returns the declared type name (`"Ticket"`, not `"class"`). There is no
cycle detection: a structure that contains itself recurses until the engine's
depth limit.

## Mutability and copying

Both structs and classes are mutable, and **assignment copies nothing**:

```silica
let a: Point = Point(1, 2)
let b: Point = a
b.x = 9
sprint(a.x)      # 9 — a and b are the same instance
```

Value semantics (copy on assignment) are not claimed in this phase. If you need
an independent copy, construct a new value from the fields.

## Errors

| Situation | Message |
|---|---|
| unknown type | `unknown type 'Piont' (did you mean 'Point'?)` |
| wrong argument count | `Point expects 2 argument(s) (x: Int, y: Int), got 1` |
| wrong argument type | `argument 2 of Point must be Int, found String` |
| unknown member | `Point has no member 'z' (did you mean 'x'?)` |
| private access | `'label' is private to Counter` |
| static on an instance | `Counter.zero is a static method` |
| instance method on the type | `Counter.add is an instance method` |
| `self` outside a method | `'self' is only available inside a method` |
| `self` in a static method | `a static method cannot use 'self'` |
| method in a struct | `struct Point cannot declare methods` |
| duplicate field | `'x' is declared twice in Point` |
| a type as a value | `'Point' is a type, not a value` |

All of these carry `file:line:column`.

## Bytecode

Four opcodes implement this, and the format moved to **1.1**:

| Opcode | Operands | Stack effect |
|---|---|---|
| `NEW` | type name const, field count | `argc → 1` |
| `GET_FIELD` | field name const | `1 → 1` |
| `SET_FIELD` | field name const | `2 → 0` |
| `CALL_METHOD` | method name const, argc | `argc + 1 → 1` |

The verifier checks all four against a **type table** carried in the bytecode
(declared types, their fields in order, and their methods with arity and function
index), so a malformed or hostile `.sbc` cannot construct an undeclared type or
call a method that does not exist. `docs/BYTECODE.md` has the layout.

**Compatibility:** 1.0 files still load and run — the type table is read only for
`minor >= 1`, and a test ships a hand-built 1.0 payload to prove it.

## What is not here yet

| Deferred | Why |
|---|---|
| Inheritance | This phase chose **composition**: a field of another type. Inheritance is a later decision. |
| Interfaces / traits | Nothing to dispatch them on until inheritance or dynamic typing exists. |
| Constructors with logic | Construction is positional field initialisation. Validation in an `init` method comes with field defaults. |
| Field defaults | Every field is set by construction, so there is no uninitialised state. |
| Generics on types | Phase 3. A `List` of instances works, but its element type is `Any`, so member access on an element is resolved at run time. |
| Operator overloading, custom `toString` | One documented representation for now. |
| Destructors / finalisers | No lifetime model in the VM. |
