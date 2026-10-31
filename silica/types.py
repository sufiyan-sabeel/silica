"""Type expressions: parsing, substitution and inference for generics.

Silica's checker has always represented a type as a string. Phase 3 keeps that
shape and extends it with a parameterised form, so `"List<Int>"` is a string that
can be split into a base name and its arguments. The alternative — replacing
every `"Int"` with a type object — would have touched the checker, the compiler,
the bytecode metadata and the formatter at once; this keeps the change local to
the places that actually need structure.

Grammar of a type expression:

    type        = NAME [ "<" type { "," type } ">" ]
    NAME        = IDENT

Examples: ``Int``, ``List<Int>``, ``Map<String, List<Int>>``, ``Box<T>``.

**Erasure.** Type arguments are checked statically and then erased: at run time a
``Box<Int>`` and a ``Box<String>`` are both a ``Box``, and ``type_of`` reports
``Box``. That is a deliberate, documented choice — see docs/GENERICS.md. Nothing
here simulates generics with untyped dynamic values: every use is checked before
the program runs, and an unconstrained operation on a type parameter is an error.
"""

__all__ = [
    "TypeError_", "parse", "base", "args", "make", "render", "substitute",
    "unify", "is_variable", "KINDS", "satisfies",
]


class TypeError_(ValueError):
    """A malformed type expression."""


KINDS = {
    # constraint -> the concrete types it admits
    "Numeric": ("Int", "Float"),
    "Orderable": ("Int", "Float", "String"),
    "Equatable": ("Int", "Float", "Bool", "String", "List", "Map", "Unit"),
    "Any": (),
}


def parse(text):
    """``"Map<String, List<Int>>"`` -> ``("Map", (("String", ()), ("List", (("Int", ()),))))``.

    Returns a nested tuple ``(name, args)``; ``args`` is a tuple of the same shape.
    """
    if not isinstance(text, str):
        raise TypeError_("a type must be a string")
    text = text.strip()
    if not text:
        raise TypeError_("a type cannot be empty")
    name, index = _name(text, 0)
    node, index = _arguments(text, index, name)
    index = _skip_space(text, index)
    if index != len(text):
        raise TypeError_("unexpected %r after a type" % text[index:])
    return node


def _skip_space(text, index):
    while index < len(text) and text[index] in " \t":
        index += 1
    return index


def _name(text, index):
    index = _skip_space(text, index)
    start = index
    while index < len(text) and (text[index].isalnum() or text[index] == "_"):
        index += 1
    if start == index:
        raise TypeError_("expected a type name at %r" % text[start:start + 12])
    return text[start:index], index


def _arguments(text, index, name):
    index = _skip_space(text, index)
    if index >= len(text) or text[index] != "<":
        return (name, ()), index
    index += 1
    items = []
    while True:
        item, index = _type_at(text, index)
        items.append(item)
        index = _skip_space(text, index)
        if index < len(text) and text[index] == ",":
            index += 1
            continue
        if index < len(text) and text[index] == ">":
            index += 1
            break
        raise TypeError_("expected ',' or '>' in the type arguments of %s" % name)
    return (name, tuple(items)), index


def _type_at(text, index):
    name, index = _name(text, index)
    return _arguments(text, index, name)


def render(node):
    """A nested tuple back to its textual form."""
    name, items = node
    if not items:
        return name
    return "%s<%s>" % (name, ", ".join(render(item) for item in items))


def base(text):
    """The base name of a type expression: ``"List<Int>"`` -> ``"List"``."""
    return parse(text)[0]


def args(text):
    """The type arguments as strings: ``"Map<String, Int>"`` -> ``("String", "Int")``."""
    return tuple(render(item) for item in parse(text)[1])


def make(name, arguments):
    """Build a type expression string."""
    if not arguments:
        return name
    return "%s<%s>" % (name, ", ".join(arguments))


def is_variable(text, variables):
    """True when `text` is one of the declared type parameters."""
    try:
        name, items = parse(text)
    except TypeError_:
        return False
    return not items and name in variables


def substitute(text, mapping):
    """Replace type parameters with concrete types, recursively.

    ``substitute("List<T>", {"T": "Int"})`` is ``"List<Int>"``.
    """
    if not mapping:
        return text
    node = parse(text)
    return _substitute_node(node, mapping)


def _substitute_node(node, mapping):
    name, items = node
    if not items and name in mapping:
        return mapping[name]
    if not items:
        return name
    return make(name, [_substitute_node(item, mapping) for item in items])


def unify(pattern, actual, mapping):
    """Bind the type parameters in `pattern` so that it matches `actual`.

    Returns True when it matched (adding bindings to `mapping`). A parameter that
    is already bound must match the existing binding, which is how
    ``same<T>(a: T, b: T)`` rejects ``same(1, "x")``.
    """
    try:
        return _unify(parse(pattern), parse(actual), mapping)
    except TypeError_:
        return False


def _unify(pattern, actual, mapping):
    p_name, p_items = pattern
    a_name, a_items = actual
    if not p_items and p_name.isupper() and len(p_name) == 1:
        bound = mapping.get(p_name)
        if bound is None:
            mapping[p_name] = render(actual)
            return True
        return base(bound) == a_name or bound == render(actual)
    if p_name != a_name:
        return False
    if not p_items and not a_items:
        return True
    if not p_items:
        # a bare container in the pattern accepts any parameterisation
        return not a_items or a_name in ("List", "Map")
    if not a_items:
        # a bare actual (an unannotated literal) cannot bind anything, but it
        # does not contradict the pattern either
        return True
    if len(p_items) != len(a_items):
        return False
    return all(_unify(p, a, mapping) for p, a in zip(p_items, a_items))


def kinds_of(constraint):
    """The concrete types a constraint admits, for error hints."""
    return KINDS.get(constraint, ())


def satisfies(concrete, constraint):
    """True when `concrete` is admitted by a constraint name."""
    if constraint in (None, "", "Any"):
        return True
    allowed = KINDS.get(constraint)
    if allowed is None:
        return False
    try:
        name = base(concrete)
    except TypeError_:
        return False
    return name in allowed
