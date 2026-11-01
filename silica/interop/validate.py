"""Validation of everything that comes *back* from a provider.

A provider is untrusted input. It may be a worker process this host started, but
it runs foreign code, so its output is validated before it becomes a Silica
value: the shape of the message, the type of every node, the nesting depth, the
size, and the identity of any handle it names.

The point is that malformed output can neither crash the runtime nor smuggle
something past the type checks — a bad payload becomes an `InteropError`, never a
partially converted value and never an exception from inside the VM.
"""

import math

from .errors import InteropError
from .values import DEFAULT_LIMITS, INT_MAX, INT_MIN

#: A handle kind is a short identifier, not free text: it ends up in diagnostics.
MAX_KIND = 64

#: Keys a provider may use to describe a value instead of sending one.
RESERVED = ("__handle__", "__bytes__", "__error__")


def _fail(code, message, provider=None, operation=None, hint=None):
    raise InteropError(code, message, provider=provider, operation=operation,
                       hint=hint)


def validate_payload(value, limits=None, depth=0, counter=None, what="result",
                     provider=None, operation=None):
    """Validate one inbound payload tree and return it unchanged.

    Raises InteropError("value.type" | "value.size" | "value.depth" |
    "value.range" | "protocol.frame") when the payload is not something this host
    is willing to convert.
    """
    limits = limits or DEFAULT_LIMITS
    if counter is None:
        counter = [0]
    limits.check_depth(depth)
    counter[0] += 1
    limits.check_items(counter[0])

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value < INT_MIN or value > INT_MAX:
            _fail("value.range", "%s carries an integer outside 64 bits" % what,
                  provider, operation)
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            _fail("value.type", "%s carries a non-finite float" % what,
                  provider, operation,
                  hint="NaN and Infinity have no Silica representation")
        return value
    if isinstance(value, str):
        limits.check_bytes(len(value.encode("utf-8")))
        return value
    if isinstance(value, list):
        limits.check_items(len(value))
        for item in value:
            validate_payload(item, limits, depth + 1, counter, what, provider,
                             operation)
        return value
    if isinstance(value, dict):
        limits.check_items(len(value))
        for key in value:
            if not isinstance(key, str):
                _fail("value.type", "%s has a non-string key" % what,
                      provider, operation,
                      hint="a Silica Map has String keys")
            limits.check_bytes(len(key.encode("utf-8")))
        reserved = [key for key in value if key in RESERVED]
        if reserved:
            _fail("protocol.frame",
                  "%s uses a reserved key (%s) outside its defined shape"
                  % (what, ", ".join(sorted(reserved))), provider, operation,
                  hint="a provider may not invent values with these keys")
        for item in value.values():
            validate_payload(item, limits, depth + 1, counter, what, provider,
                             operation)
        return value
    _fail("value.type",
          "%s carries a %s, which is not a convertible value"
          % (what, type(value).__name__), provider, operation,
          hint="convert it explicitly, or return a handle")


def is_handle_ref(value):
    return isinstance(value, dict) and "__handle__" in value


def validate_handle_ref(value, limits=None, provider=None, operation=None):
    """Validate `{"__handle__": id, "kind": name}` and return (id, kind).

    The id must be a non-negative integer the worker owns, and the kind must be a
    short identifier — never free text that could carry a path or a secret.
    """
    limits = limits or DEFAULT_LIMITS
    if not isinstance(value, dict):
        _fail("protocol.frame", "a handle reference is not an object",
              provider, operation)
    extra = [key for key in value if key not in ("__handle__", "kind")]
    if extra:
        _fail("protocol.frame",
              "a handle reference carries unexpected keys (%s)"
              % ", ".join(sorted(extra)), provider, operation)
    ident = value.get("__handle__")
    if isinstance(ident, bool) or not isinstance(ident, int) or ident < 0:
        _fail("protocol.frame",
              "a handle reference must carry a non-negative integer id",
              provider, operation)
    kind = value.get("kind", "object")
    if not isinstance(kind, str) or not kind:
        _fail("protocol.frame", "a handle reference needs a kind name",
              provider, operation)
    if len(kind) > MAX_KIND:
        _fail("protocol.frame", "handle kind is longer than %d characters"
              % MAX_KIND, provider, operation)
    if not all(ch.isalnum() or ch in "._-" for ch in kind):
        _fail("protocol.frame",
              "handle kind must be a short identifier, found %r" % (kind,),
              provider, operation,
              hint="a kind is a name, not free text")
    limits.check_bytes(len(kind))
    return ident, kind


def validate_bytes_ref(value, limits=None, provider=None, operation=None):
    """Validate `{"__bytes__": "<base64>"}` and return the decoded bytes."""
    import base64
    import binascii

    limits = limits or DEFAULT_LIMITS
    if not isinstance(value, dict):
        _fail("protocol.frame", "a bytes reference is not an object",
              provider, operation)
    extra = [key for key in value if key != "__bytes__"]
    if extra:
        _fail("protocol.frame",
              "a bytes reference carries unexpected keys (%s)"
              % ", ".join(sorted(extra)), provider, operation)
    encoded = value.get("__bytes__")
    if not isinstance(encoded, str):
        _fail("value.type", "a bytes reference must carry a string",
              provider, operation)
    limits.check_bytes(len(encoded))
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        _fail("value.type", "a bytes reference is not valid base64",
              provider, operation)


def validate_error_payload(value, provider=None, operation=None):
    """Validate `{"__error__": {"type": ..., "message": ...}}` -> (type, message)."""
    if not isinstance(value, dict) or "__error__" not in value:
        _fail("protocol.frame", "an error frame carries no error object",
              provider, operation)
    body = value["__error__"]
    if not isinstance(body, dict):
        _fail("protocol.frame", "the error object is not an object",
              provider, operation)
    kind = body.get("type", "Error")
    message = body.get("message", "the provider reported a failure")
    if not isinstance(kind, str) or not kind:
        kind = "Error"
    if not isinstance(message, str):
        message = "the provider reported a failure"
    # A message is a diagnostic, not a channel: bound it and strip newlines so a
    # provider cannot forge a multi-line report or flood a log.
    message = message.replace("\n", " ")[:500]
    return kind[:80], message
