"""Structured errors for the interoperability layer.

Every failure is an `InteropError` with a stable code, so a host can branch on
`error.code` instead of matching message text, and a message never carries a host
secret (no paths the program was not granted, no environment values, no
provider-internal detail such as a stack trace or an address).

`InteropError` subclasses `SilicaError` so that, when a provider call is made on
behalf of a Silica call site, the VM can attach line/column/filename exactly as it
does for a native (see `silica/vm.py`, CALL_NATIVE).
"""

from ..errors import SilicaError


#: The closed set of codes this layer may raise. Adding one is a deliberate act:
#: hosts branch on these strings, so they are part of the interface.
CODES = frozenset({
    # provider lifecycle
    "provider.unknown",          # no provider registered under that name
    "provider.duplicate",        # a provider with that name is already registered
    "provider.abi",              # provider targets an interface version we lack
    "provider.capability",       # provider needs a capability kind that is unknown
    "provider.signature",        # malformed operation metadata
    "provider.closed",           # operation attempted after close
    # invocation
    "operation.unknown",         # provider has no such operation
    "operation.arity",           # wrong number of arguments
    "operation.denied",          # capability refused the call
    "operation.timeout",         # deadline exceeded
    "operation.failed",          # provider reported failure
    # values
    "value.type",                # tag does not match the declared type
    "value.range",               # integer outside 64-bit range
    "value.size",                # payload or container too large
    "value.depth",               # nesting too deep
    "value.cycle",               # a container contains itself
    "value.encoding",            # bytes that are not valid UTF-8
    # handles
    "handle.unknown",            # token names no live handle
    "handle.released",           # token was released
    "handle.owner",              # token belongs to another provider or session
    # protocol (reserved for the worker layer, not implemented yet)
    "protocol.version",
    "protocol.frame",
})


class InteropError(SilicaError):
    """One interoperability failure, with a stable code and its context."""

    kind = "interop error"

    def __init__(self, code, message, provider=None, operation=None, hint=None,
                 line=0, col=0, filename=None):
        if code not in CODES:
            raise ValueError("unknown interop error code %r" % (code,))
        super().__init__(message, line, col, filename, hint)
        self.code = code
        self.provider = provider
        self.operation = operation

    def __str__(self):
        return "%s: %s" % (self.code, self.message)

    def context(self):
        """A dict for a host that wants to log or translate the failure."""
        return {"code": self.code, "provider": self.provider,
                "operation": self.operation, "message": self.message,
                "hint": self.hint}
