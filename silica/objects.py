"""Instances of user-declared structs and classes.

The value model lives here rather than in `vm.py` because three other modules
need it and importing the VM from them would be a cycle:

* `natives.py` — `type_of` and `sprint`/`str` must render an instance,
* `vm.py` — `NEW`, `GET_FIELD`, `SET_FIELD`, `CALL_METHOD` and `==`,
* `bytecode.py` — the verifier needs the type table, not the values.

Two rules that are easy to get wrong, so they are stated once here:

* **A struct is a value, a class is an object.** Struct equality is structural
  (`Point(1, 2) == Point(1, 2)`), class equality is identity — a class has state
  that methods mutate, so structural equality would make `==` surprising after a
  method call.
* **Assignment copies nothing.** `let q = p` binds the same instance. Value
  semantics (copy on assign) are not claimed in this phase.
"""

__all__ = ["Instance", "is_instance", "equal", "render", "type_name_of"]


class Instance:
    """One constructed value: its declared type name and its fields."""

    __slots__ = ("type_name", "fields", "order", "is_struct")

    def __init__(self, type_name, field_names, values, is_struct):
        self.type_name = type_name
        self.fields = dict(zip(field_names, values))
        self.order = tuple(field_names)
        self.is_struct = bool(is_struct)

    # -- field access --------------------------------------------------------
    def get(self, name):
        try:
            return self.fields[name]
        except KeyError:
            raise KeyError(name)

    def set(self, name, value):
        if name not in self.fields:
            raise KeyError(name)
        self.fields[name] = value

    def __repr__(self):                      # pragma: no cover - debugging aid
        return "Instance(%s, %r)" % (self.type_name, self.fields)


def is_instance(value):
    return isinstance(value, Instance)


def type_name_of(value):
    return value.type_name


def equal(first, second):
    """Equality with Silica's rules, including instances.

    Structs compare field by field; classes compare by identity. Nested lists,
    maps and instances are compared recursively. Numbers compare across Int and
    Float; Bool never equals a number.
    """
    if isinstance(first, Instance) or isinstance(second, Instance):
        if not (isinstance(first, Instance) and isinstance(second, Instance)):
            return False
        if first.type_name != second.type_name:
            return False
        if not first.is_struct:
            return first is second
        if first.order != second.order:
            return False
        return all(equal(first.fields[name], second.fields[name])
                   for name in first.order)

    if isinstance(first, bool) != isinstance(second, bool):
        return False
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return first == second
    if type(first) is not type(second):
        return False
    if isinstance(first, list):
        return (len(first) == len(second)
                and all(equal(a, b) for a, b in zip(first, second)))
    if isinstance(first, dict):
        if set(first) != set(second):
            return False
        return all(equal(first[key], second[key]) for key in first)
    return first == second


def render(value, format_value):
    """`Point { x: 10, y: 4 }` — fields in declaration order.

    `format_value` is the caller's renderer, passed in to avoid a cycle with
    `natives.py`. There is no cycle detection: a structure that contains itself
    recurses until the engine's depth limit, which is documented rather than
    silently truncated.
    """
    parts = ["%s: %s" % (name, format_value(value.fields[name]))
             for name in value.order]
    return "%s { %s }" % (value.type_name, ", ".join(parts))
