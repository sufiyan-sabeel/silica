"""The provider interface: what an ecosystem adapter must implement.

A provider is metadata first and behaviour second. `operations()` must be
callable without starting anything, so a host can inspect what a provider offers
and type a call before any foreign code runs.
"""

from .errors import InteropError
from .values import Tag


#: The provider interface version this build implements. A provider declares the
#: version it was written against; the registry refuses a major mismatch.
ABI_VERSION = 1


class ForeignType(object):
    """The declared type of a parameter or return value."""

    __slots__ = ("tag", "kind", "is_any")

    def __init__(self, tag=None, kind=None):
        self.tag = tag
        self.kind = kind
        self.is_any = tag is None

    @classmethod
    def any(cls):
        return cls(None)

    @classmethod
    def of(cls, tag):
        if tag not in Tag.ALL:
            raise ValueError("unknown foreign tag %r" % (tag,))
        return cls(tag)

    @classmethod
    def handle(cls, kind):
        return cls(Tag.HANDLE, kind)

    def describe(self):
        if self.is_any:
            return "any"
        if self.tag == Tag.HANDLE:
            return "handle(%s)" % (self.kind or "?")
        return self.tag

    def __repr__(self):
        return "ForeignType(%s)" % self.describe()


class Signature(object):
    """Everything needed to type a call without running it."""

    __slots__ = ("name", "params", "ret", "min_args", "max_args", "errors",
                 "blocking", "releases")

    def __init__(self, name, params, ret, min_args=None, max_args=None,
                 errors=(), blocking=False, releases=False):
        self.name = name
        #: list of (parameter name, ForeignType)
        self.params = list(params)
        self.ret = ret
        self.min_args = len(self.params) if min_args is None else min_args
        self.max_args = len(self.params) if max_args is None else max_args
        self.errors = tuple(errors)
        self.blocking = blocking
        #: True when the call consumes (releases) a handle argument.
        self.releases = releases

    def describe(self):
        return "%s(%s) -> %s" % (self.name,
                                 ", ".join("%s: %s" % (n, t.describe())
                                           for n, t in self.params),
                                 self.ret.describe() if self.ret else "unit")

    def __repr__(self):
        return "Signature(%s)" % self.describe()


class Provider(object):
    """Base class for an ecosystem adapter.

    Subclasses set `name`, `version`, `capabilities` and implement the four
    methods. Nothing here starts a process, loads a library or performs I/O: an
    adapter that needs to does it inside `invoke`, after the capability gate.
    """

    #: Unique, lowercase, stable: it is the namespace in `provider.operation`.
    name = ""
    version = "0.0"
    abi = ABI_VERSION
    #: Capability kinds this provider needs. Must be existing kinds; a new kind
    #: is an explicit decision in `silica/capabilities.py`.
    capabilities = ()

    def operations(self):
        """Return {name: Signature}. Must not execute anything."""
        raise NotImplementedError

    def invoke(self, operation, args, ctx):
        """Run one operation and return a ForeignValue."""
        raise NotImplementedError

    def release(self, handle, ctx):
        """Free the foreign object behind a handle. Called exactly once."""
        raise NotImplementedError

    def close(self):
        """Release any remaining state. Must not raise for a normal shutdown."""
        return None

    # -- validation used by the registry ----------------------------------
    def validate(self):
        """Check the provider's metadata. Raises InteropError on a bad shape."""
        if not self.name or not isinstance(self.name, str):
            raise InteropError("provider.signature",
                               "a provider needs a non-empty name")
        if not isinstance(self.version, str):
            raise InteropError("provider.signature",
                               "provider %s has a non-string version" % self.name,
                               provider=self.name)
        if not isinstance(self.abi, int):
            raise InteropError("provider.signature",
                               "provider %s has a non-integer abi" % self.name,
                               provider=self.name)
        if not isinstance(self.capabilities, (tuple, list)):
            raise InteropError("provider.signature",
                               "provider %s declares capabilities as %s"
                               % (self.name, type(self.capabilities).__name__),
                               provider=self.name)
        operations = self.operations()
        if not isinstance(operations, dict):
            raise InteropError("provider.signature",
                               "provider %s operations() must return a dict"
                               % self.name, provider=self.name)
        for key, signature in operations.items():
            if not isinstance(signature, Signature):
                raise InteropError(
                    "provider.signature",
                    "operation '%s' of %s is not a Signature" % (key, self.name),
                    provider=self.name, operation=key)
            if signature.name != key:
                raise InteropError(
                    "provider.signature",
                    "operation key '%s' does not match signature name '%s'"
                    % (key, signature.name), provider=self.name, operation=key)
            for pname, ptype in signature.params:
                if not isinstance(ptype, ForeignType):
                    raise InteropError(
                        "provider.signature",
                        "parameter '%s' of %s.%s is not a ForeignType"
                        % (pname, self.name, key), provider=self.name,
                        operation=key)
            if signature.ret is not None and not isinstance(signature.ret,
                                                            ForeignType):
                raise InteropError(
                    "provider.signature",
                    "return type of %s.%s is not a ForeignType" % (self.name, key),
                    provider=self.name, operation=key)
            if signature.min_args > signature.max_args:
                raise InteropError(
                    "provider.signature",
                    "%s.%s has min_args %d above max_args %d"
                    % (self.name, key, signature.min_args, signature.max_args),
                    provider=self.name, operation=key)
        return operations
