# Generics

Type parameters let one declaration work for many element types **while still
being checked**. `List<Int>` is a list of integers to the checker, so `xs[0]` is
an `Int` — not `Any`.

```silica
struct Pair<K, V> {
    key: K
    value: V
}

class Bag<T> {
    items: List<T>

    sfn add(item: T) {
        push(self.items, item)
    }

    sfn at(index: Int) -> T {
        ret self.items[index]
    }
}

sfn largest<T: Orderable>(items: List<T>) -> T {
    let best: T = items[0]
    per item in items {
        si item > best {
            best = item
        }
    }
    ret best
}

sfn main() {
    let pair: Pair<String, Int> = Pair("age", 42)
    sprint(pair.value)                  # 42

    let words: Bag<String> = Bag([])
    words.add("alpha")
    sprint(words.at(0))                 # alpha

    sprint(largest([2.5, 1.5, 9.0]))    # 9.0
}
```

## Syntax

```ebnf
type-params  = "<" type-param { "," type-param } ">" ;
type-param   = IDENT [ ":" constraint ] ;
type         = IDENT [ "<" type { "," type } ">" ] ;
```

Type parameters go after the name of a `sfn`, `struct` or `class`. Type
arguments go inside a type annotation.

```silica
sfn first<T>(items: List<T>) -> T { … }          # a generic function
struct Box<T> { value: T }                        # a generic struct
class Stack<T> { items: List<T> … }               # a generic class
class Pair<K, V> { key: K
                   value: V }                     # two parameters
let m: Map<String, List<Int>> = {"a": [1]}        # nested arguments
```

## Built-in containers are generic

| Type | Meaning |
|---|---|
| `List<T>` | a list whose elements are `T` |
| `Map<K, V>` | a map with key type `K` and value type `V` |

Element and key types flow through indexing and iteration:

```silica
let xs: List<String> = ["a", "b"]
let s: String = xs[0]        # xs[0] is String
per item in xs {
    let also: String = item  # the loop variable is String
}
let n: Int = xs[0]           # error: cannot initialise Int with a value of type String
```

A **bare** `List` or `Map` still works and means "elements unknown" — that is what
an unannotated, heterogeneous literal gets. A bare container is compatible with
any parameterisation, so existing code keeps compiling; annotate to get the
checks.

Type arguments are **invariant**: `List<Int>` is not a `List<Float>`, because a
list can be mutated. Assign through a fresh annotation or convert the elements.

## Inference

Type arguments are inferred from the arguments you pass:

```silica
sfn first<T>(items: List<T>) -> T { ret items[0] }

first([1, 2])                     # T = Int
first(xs)                         # T = Int, from xs: List<Int>
```

For construction, inference uses the arguments and, if that is not enough, the
**annotation on the binding**:

```silica
let b: Box<Int> = Box(1)          # from the argument
let s: Stack<String> = Stack([])  # from the annotation: [] alone says nothing
```

Two cases fail on purpose, with a message saying what to do:

```silica
sfn same<T>(a: T, b: T) -> T { ret a }
same(1, "x")     # error: argument 2 of 'same' must be T, found String

sfn make<T>() -> List<T> { ret [] }
make()           # error: cannot infer type parameter T
```

Annotation-driven inference applies to the immediate initialiser. Inside a
collection literal, give each element an argument that determines its type
(`[Bag([1]), Bag([2])]` rather than `[Bag([]), Bag([])]`).

## Constraints

A type parameter with no constraint can only be stored, passed, compared for
equality and returned — the checker will not let you do arithmetic or ordering on
it, because it cannot know those are defined:

```silica
sfn twice<T>(x: T) -> T { ret x + x }
# error: '+' cannot be used with a T value: type parameter T is unconstrained
```

Add a constraint to permit the operation:

| Constraint | Admits | Permits |
|---|---|---|
| `Numeric` | `Int`, `Float` | `+ - * / %` |
| `Orderable` | `Int`, `Float`, `String` | `< <= > >=` (and arithmetic on numbers) |
| `Equatable` | every value type | `== !=` |
| *(none)* | anything | storage, passing, returning, `==` |

```silica
sfn twice<T: Numeric>(x: T) -> T { ret x + x }        # ok
sfn biggest<T: Orderable>(a: T, b: T) -> T { … }      # ok
sfn big<T: Numeric>(a: T, b: T) -> T { si a > b { … } }
# error: '>' needs a Orderable value, but T is only constrained to Numeric
```

The constraint is checked twice: in the body (may I use this operator?) and at
each call site (is the inferred argument allowed?).

```silica
twice(2)      # ok: Int is Numeric
twice("a")    # error: type argument T = String does not satisfy Numeric
```

## Erasure, and what that means

Type arguments are checked statically and **erased** at run time:

```silica
let a: Box<Int> = Box(1)
let b: Box<String> = Box("x")
sprint(type_of(a))            # Box   — not Box<Int>
sprint(type_of(a) == type_of(b))   # oui — one runtime type
```

This is a deliberate choice, and it is not the same as skipping the checks:
every use is verified before the program runs, an unconstrained operation is an
error, and the arguments are consistent at every call site. What erasure costs is
runtime reflection on type arguments and per-instantiation specialisation
(`Box<Int>` and `Box<String>` share one compiled body). Monomorphisation — a
separate compiled type per instantiation — is a performance and reflection
feature, not a correctness one, and it is listed as future work rather than
pretended.

Because of erasure, a **static** method of a generic class cannot use the class's
type parameters (there is no receiver to infer them from):

```silica
class Box<T> {
    value: T
    static sfn empty() -> T { … }   # error: static, cannot use T
}
```

Make it an instance method, or give it its own type parameters.

## Errors

| Situation | Message |
|---|---|
| wrong number of type arguments | `List expects 0 or 1 type argument(s), got 2` |
| wrong number for a user type | `Box expects 1 type argument(s), got 0` |
| unknown type argument | `unknown type 'Nope'` |
| conflicting inference | `argument 2 of 'same' must be T, found String` |
| nothing to infer from | `cannot infer type parameter(s) T for 'make'` |
| constraint violated at the call | `type argument T = String does not satisfy Numeric` |
| unconstrained operator use | `'+' cannot be used with a T value: type parameter T is unconstrained` |
| constraint too weak | `'>' needs a Orderable value, but T is only constrained to Numeric` |
| static using a class parameter | `Box.empty is static and cannot use the type parameter(s) T` |
| unknown constraint | `unknown constraint 'Fancy'` |
| duplicate parameter | `duplicate type parameter 'T'` |

## What is not here yet

| Deferred | Why |
|---|---|
| Monomorphisation | Erasure is correct and simpler; specialisation is a performance feature. |
| Explicit type arguments at a call (`first<Int>(xs)`) | `Type<Arg>(…)` in expression position is ambiguous with `<` and `>`. Inference covers the practical cases; annotate the binding to fix a type. |
| User-defined constraints / traits | Needs a trait system. The four built-in kinds cover arithmetic, ordering and equality. |
| Variance annotations | Type arguments are invariant. Covariant read-only containers would need a mutability model. |
| Higher-kinded types, associated types | Out of scope for this phase. |
| Constraining on a user type (`T: MyTrait`) | Needs traits; `Equatable` is the only constraint every type satisfies. |
