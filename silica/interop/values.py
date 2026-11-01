"""The value that crosses an interoperability boundary.

A `ForeignValue` is a tagged union, not a wrapper around an arbitrary Python
object: a provider cannot smuggle something into the VM, and the VM cannot leak
something out. Conversion is explicit, total and bounded in both directions —
there is no "best effort" mapping and no implicit coercion.

Nothing here executes anything, starts a process or loads a library.
"""

from .errors import InteropError


class Tag(object):
    """The closed set of tags a foreign value may carry."""

    NONE = "none"
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BYTES = "bytes"
    LIST = "list"
    MAP = "map"
    HANDLE = "handle"

    ALL = (NONE, BOOL, INT, FLOAT, STRING, BYTES, LIST, MAP, HANDLE)


#: 64-bit signed, matching Silica's `Int`.
INT_MIN = -(2 ** 63)
INT_MAX = 2 ** 63 - 1

#: Bounds applied to both conversion directions. They are deliberately generous
#: but finite: an unbounded boundary is how a provider turns into an outage.
MAX_DEPTH = 32
MAX_ITEMS = 100000
MAX_BYTES = 16 * 1024 * 1024


class Limits(object):
    """Depth, item-count and byte bounds for one conversion."""

    __slots__ = ("max_depth", "max_items", "max_bytes")

    def __init__(self, max_depth=MAX_DEPTH, max_items=MAX_ITEMS,
                 max_bytes=MAX_BYTES):
        self.max_depth = max_depth
        self.max_items = max_items
        self.max_bytes = max_bytes

    def check_depth(self, depth):
        if depth > self.max_depth:
            raise InteropError("value.depth",
                               "value nests deeper than %d levels" % self.max_depth,
                               hint="pass less structure, or raise the limit")

    def check_items(self, count):
        if count > self.max_items:
            raise InteropError("value.size",
                               "container holds %d items, more than %d"
                               % (count, self.max_items))

    def check_bytes(self, size):
        if size > self.max_bytes:
            raise InteropError("value.size",
                               "payload is %d bytes, more than %d"
                               % (size, self.max_bytes))


DEFAULT_LIMITS = Limits()


class ForeignValue(object):
    """One value crossing the boundary. Immutable by convention."""

    __slots__ = ("tag", "value")

    def __init__(self, tag, value=None):
        if tag not in Tag.ALL:
            raise ValueError("unknown foreign tag %r" % (tag,))
        if tag == Tag.NONE and value is not None:
            raise ValueError("a none value carries no payload")
        if tag == Tag.BOOL and not isinstance(value, bool):
            raise ValueError("a bool value needs a bool")
        if tag == Tag.INT:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("an int value needs an int, not a bool")
            if value < INT_MIN or value > INT_MAX:
                raise ValueError("int %d does not fit in 64 bits" % value)
        if tag == Tag.FLOAT and isinstance(value, bool):
            raise ValueError("a float value cannot be a bool")
        if tag == Tag.STRING and not isinstance(value, str):
            raise ValueError("a string value needs a str")
        if tag == Tag.BYTES and not isinstance(value, (bytes, bytearray)):
            raise ValueError("a bytes value needs bytes")
        if tag in (Tag.LIST, Tag.MAP) and value is None:
            raise ValueError("a container value needs a payload")
        self.tag = tag
        self.value = value

    # -- constructors ------------------------------------------------------
    @classmethod
    def none(cls):
        return cls(Tag.NONE)

    @classmethod
    def bool_(cls, value):
        return cls(Tag.BOOL, bool(value))

    @classmethod
    def int_(cls, value):
        return cls(Tag.INT, value)

    @classmethod
    def float_(cls, value):
        return cls(Tag.FLOAT, float(value))

    @classmethod
    def string(cls, value):
        return cls(Tag.STRING, value)

    @classmethod
    def bytes_(cls, value):
        return cls(Tag.BYTES, bytes(value))

    @classmethod
    def list_(cls, items):
        return cls(Tag.LIST, list(items))

    @classmethod
    def map_(cls, pairs):
        return cls(Tag.MAP, dict(pairs))

    @classmethod
    def handle(cls, handle):
        return cls(Tag.HANDLE, handle)

    # -- inspection --------------------------------------------------------
    @property
    def is_handle(self):
        return self.tag == Tag.HANDLE

    def describe(self):
        """A short, secret-free description for diagnostics."""
        if self.tag == Tag.HANDLE:
            return "handle(%s)" % (getattr(self.value, "kind", "?"),)
        if self.tag in (Tag.LIST, Tag.MAP):
            return "%s of %d" % (self.tag, len(self.value))
        if self.tag == Tag.STRING:
            return "string of %d" % len(self.value)
        return self.tag

    def __repr__(self):
        return "ForeignValue(%s)" % self.describe()

    def __eq__(self, other):
        if not isinstance(other, ForeignValue):
            return NotImplemented
        if self.tag != other.tag:
            return False
        if self.tag == Tag.HANDLE:
            return self.value is other.value
        return self.value == other.value

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result


# -- Silica side -> foreign ------------------------------------------------

def from_silica(value, limits=None, depth=0, path=None):
    """Convert a Silica/host value into a `ForeignValue`, or raise.

    Explicit and total: a value with no declared foreign shape (a struct or class
    instance, an Iterator) is refused rather than approximated.
    """
    limits = limits or DEFAULT_LIMITS
    limits.check_depth(depth)
    path = path if path is not None else set()

    if value is None:
        return ForeignValue.none()
    if isinstance(value, bool):
        return ForeignValue.bool_(value)
    if isinstance(value, int):
        if value < INT_MIN or value > INT_MAX:
            raise InteropError("value.range",
                               "integer %d does not fit in 64 bits" % value,
                               hint="Int is signed 64-bit at the boundary too")
        return ForeignValue.int_(value)
    if isinstance(value, float):
        return ForeignValue.float_(value)
    if isinstance(value, str):
        limits.check_bytes(len(value.encode("utf-8")))
        return ForeignValue.string(value)
    if isinstance(value, (bytes, bytearray)):
        limits.check_bytes(len(value))
        return ForeignValue.bytes_(value)
    if isinstance(value, ForeignValue):
        return value

    from .handles import ForeignHandle
    if isinstance(value, ForeignHandle):
        return ForeignValue.handle(value)

    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in path:
            raise InteropError("value.cycle", "container contains itself")
        limits.check_items(len(value))
        path.add(marker)
        try:
            items = [from_silica(item, limits, depth + 1, path) for item in value]
        finally:
            path.discard(marker)
        return ForeignValue.list_(items)

    if isinstance(value, dict):
        marker = id(value)
        if marker in path:
            raise InteropError("value.cycle", "container contains itself")
        limits.check_items(len(value))
        path.add(marker)
        try:
            pairs = []
            for key, item in value.items():
                if not isinstance(key, str):
                    raise InteropError(
                        "value.type",
                        "map keys must be String at the boundary, found %s"
                        % type(key).__name__,
                        hint="Silica's Map has String keys")
                pairs.append((key, from_silica(item, limits, depth + 1, path)))
        finally:
            path.discard(marker)
        return ForeignValue.map_(pairs)

    raise InteropError(
        "value.type",
        "a %s has no foreign representation" % type(value).__name__,
        hint="convert it explicitly: structs and classes do not cross implicitly")


# -- foreign -> Silica side ------------------------------------------------

def to_silica(value, limits=None, depth=0):
    """Convert a `ForeignValue` into a host value, or raise.

    A handle converts to its `ForeignHandle`; it is never turned into a number or
    a string, so a program can only pass it back to the provider that owns it.
    """
    limits = limits or DEFAULT_LIMITS
    limits.check_depth(depth)
    if not isinstance(value, ForeignValue):
        raise InteropError("value.type",
                           "expected a foreign value, found %s"
                           % type(value).__name__)
    tag = value.tag
    if tag in (Tag.NONE, Tag.BOOL, Tag.INT, Tag.FLOAT, Tag.STRING):
        return value.value
    if tag == Tag.BYTES:
        limits.check_bytes(len(value.value))
        return bytes(value.value)
    if tag == Tag.HANDLE:
        return value.value
    if tag == Tag.LIST:
        limits.check_items(len(value.value))
        return [to_silica(item, limits, depth + 1) for item in value.value]
    if tag == Tag.MAP:
        limits.check_items(len(value.value))
        return dict((key, to_silica(item, limits, depth + 1))
                    for key, item in value.value.items())
    raise InteropError("value.type", "unknown foreign tag %r" % (tag,))


def check_type(value, expected, provider=None, operation=None):
    """Check a value against a declared `ForeignType`, converting it.

    `expected` is a `ForeignType` (see `provider.py`). Returns the host value.
    """
    from .provider import ForeignType
    if not isinstance(expected, ForeignType):
        raise InteropError("provider.signature",
                           "expected type metadata is not a ForeignType",
                           provider=provider, operation=operation)
    if expected.is_any:
        return to_silica(value)
    if expected.tag != value.tag:
        raise InteropError(
            "value.type",
            "%s returned %s where %s was declared"
            % (operation or "provider", value.describe(), expected.describe()),
            provider=provider, operation=operation)
    if expected.tag == Tag.HANDLE and expected.kind:
        actual = getattr(value.value, "kind", None)
        if actual != expected.kind:
            raise InteropError(
                "value.type",
                "%s returned handle of kind %s where %s was declared"
                % (operation or "provider", actual, expected.kind),
                provider=provider, operation=operation)
    return to_silica(value)
