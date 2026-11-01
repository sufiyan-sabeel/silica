"""The context one provider invocation runs inside.

It carries the deadline, the size bounds, the handle registry and — crucially —
the capability check. `InvocationContext.authorize` calls
`CapabilitySet.authorize_call`, the same function the VM uses for natives
(`silica/vm.py`, CALL_NATIVE), so interoperability does not add a second place
where privilege is decided.
"""

import time

from ..capabilities import CapabilityError
from .errors import InteropError
from .values import DEFAULT_LIMITS


class _GateRecord(object):
    """The shape `CapabilitySet.authorize_call` expects from a native."""

    __slots__ = ("requires", "path_arg", "qualified")

    def __init__(self, requires, path_arg, qualified):
        self.requires = requires
        self.path_arg = path_arg
        self.qualified = qualified


class InvocationContext(object):
    """Everything a provider may know about the call it is serving."""

    __slots__ = ("provider", "operation", "session", "deadline", "limits",
                 "handles", "capabilities", "_clock")

    def __init__(self, provider, operation=None, session=None, timeout=None,
                 limits=None, handles=None, capabilities=None, clock=None):
        self.provider = provider
        self.operation = operation
        self.session = session
        self.limits = limits or DEFAULT_LIMITS
        self.handles = handles
        self.capabilities = capabilities
        self._clock = clock or time.monotonic
        self.deadline = None if timeout is None else self._clock() + timeout

    # -- deadline ----------------------------------------------------------
    def remaining(self):
        """Seconds left, or None when the call has no deadline."""
        if self.deadline is None:
            return None
        return self.deadline - self._clock()

    def check_deadline(self):
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            raise InteropError(
                "operation.timeout",
                "%s exceeded its deadline" % (self.operation or "operation"),
                provider=self.provider, operation=self.operation,
                hint="the call was abandoned; release any handle it returned")

    # -- the single authorization gate ------------------------------------
    def authorize(self, requires, args, path_arg=None):
        """Authorise a privileged operation, returning the arguments to use.

        Deny by default: with no capability set, a privileged call is refused.
        A call that needs no capability (`requires is None`) passes through.
        """
        if requires is None:
            return args
        if self.capabilities is None:
            raise InteropError(
                "operation.denied",
                "%s needs capability '%s' but no grant set was supplied"
                % (self.operation or "operation", requires),
                provider=self.provider, operation=self.operation,
                hint="Silica grants nothing by default")
        gate = _GateRecord(requires, path_arg,
                           "%s.%s" % (self.provider, self.operation or "call"))
        try:
            return self.capabilities.authorize_call(gate, args)
        except CapabilityError as err:
            raise InteropError("operation.denied", err.message,
                               provider=self.provider,
                               operation=self.operation, hint=err.hint)

    # -- bounds ------------------------------------------------------------
    def check_size(self, size):
        self.limits.check_bytes(size)
