"""The provider registry.

Deliberately separate from `silica.natives.MODULES`: a provider operation never
appears in the standard-library namespace, cannot shadow `core`, `fs`, `math` or
any other module, and cannot be reached from Silica source. Registration is
explicit — nothing is imported, scanned or started unless a host asks for it.
"""

from ..capabilities import KNOWN as KNOWN_CAPABILITIES
from .context import InvocationContext
from .errors import InteropError
from .handles import HandleRegistry
from .provider import ABI_VERSION, Provider
from .values import ForeignValue, check_type, from_silica


class ProviderRegistry(object):
    """Holds the registered providers and validates every invocation."""

    def __init__(self, capabilities=None, handles=None, clock=None):
        self.capabilities = capabilities
        self.handles = handles or HandleRegistry()
        self._clock = clock
        self._providers = {}
        self._closed = set()

    # -- registration ------------------------------------------------------
    def register(self, provider):
        """Register a provider, or raise. Nothing is started."""
        if not isinstance(provider, Provider):
            raise InteropError("provider.signature",
                               "only a Provider can be registered, found %s"
                               % type(provider).__name__)
        if provider.name in self._providers:
            raise InteropError("provider.duplicate",
                               "a provider named '%s' is already registered"
                               % provider.name, provider=provider.name)
        if provider.abi != ABI_VERSION:
            raise InteropError(
                "provider.abi",
                "provider '%s' targets interface version %d; this build "
                "implements %d" % (provider.name, provider.abi, ABI_VERSION),
                provider=provider.name,
                hint="rebuild the provider against the current interface")
        for kind in provider.capabilities:
            if kind not in KNOWN_CAPABILITIES:
                raise InteropError(
                    "provider.capability",
                    "provider '%s' needs unknown capability '%s'"
                    % (provider.name, kind), provider=provider.name,
                    hint="known capabilities: %s" % ", ".join(KNOWN_CAPABILITIES))
        provider.validate()
        self._providers[provider.name] = provider
        return provider

    def unregister(self, name):
        """Close and forget a provider. Returns True when it was registered."""
        provider = self._providers.pop(name, None)
        if provider is None:
            return False
        self._closed.add(name)
        provider.close()
        return True

    # -- inspection --------------------------------------------------------
    def get(self, name):
        return self._providers.get(name)

    def names(self):
        return sorted(self._providers)

    def operations(self, name):
        provider = self._require(name)
        return provider.operations()

    def describe(self, name):
        """A host-facing summary. Metadata only; nothing is executed."""
        provider = self._require(name)
        return {
            "name": provider.name,
            "version": provider.version,
            "abi": provider.abi,
            "capabilities": list(provider.capabilities),
            "operations": [signature.describe()
                           for signature in provider.operations().values()],
        }

    def _require(self, name):
        provider = self._providers.get(name)
        if provider is None:
            raise InteropError("provider.unknown",
                               "no provider named '%s' is registered" % name,
                               provider=name,
                               hint="registered: %s"
                                    % (", ".join(self.names()) or "none"))
        return provider

    # -- invocation --------------------------------------------------------
    def invoke(self, name, operation, args, ctx=None):
        """Validate and run one operation, returning a ForeignValue.

        The order is fixed: the provider must be registered, the operation must
        exist, the arity must match, every argument must satisfy its declared
        type, and the result must satisfy the declared return type.
        """
        if name in self._closed:
            raise InteropError("provider.closed",
                               "provider '%s' is closed" % name, provider=name,
                               hint="a closed provider cannot be invoked")
        provider = self._require(name)
        signature = provider.operations().get(operation)
        if signature is None:
            raise InteropError(
                "operation.unknown",
                "provider '%s' has no operation '%s'" % (name, operation),
                provider=name, operation=operation,
                hint="operations: %s"
                     % (", ".join(sorted(provider.operations())) or "none"))
        count = len(args)
        if count < signature.min_args or count > signature.max_args:
            raise InteropError(
                "operation.arity",
                "%s.%s takes %d to %d argument(s), got %d"
                % (name, operation, signature.min_args, signature.max_args, count),
                provider=name, operation=operation)
        ctx = ctx or InvocationContext(name, operation, handles=self.handles,
                                       capabilities=self.capabilities,
                                       clock=self._clock)
        ctx.check_deadline()

        converted = []
        for index, value in enumerate(args):
            pname, ptype = signature.params[index]
            foreign = from_silica(value, ctx.limits)
            converted.append(check_type(foreign, ptype, name, operation))

        result = provider.invoke(operation, converted, ctx)
        ctx.check_deadline()
        if not isinstance(result, ForeignValue):
            raise InteropError(
                "operation.failed",
                "%s.%s returned %s, not a ForeignValue"
                % (name, operation, type(result).__name__),
                provider=name, operation=operation,
                hint="a provider must convert its result explicitly")
        if signature.ret is not None:
            check_type(result, signature.ret, name, operation)
        return result

    # -- shutdown ----------------------------------------------------------
    def close(self):
        """Close every provider, releasing their handles. Returns a summary."""
        summary = {"providers": [], "handles_released": 0}
        for name in list(self._providers):
            handles = self.handles.release_session(None)
            summary["handles_released"] += handles
            self._providers.pop(name).close()
            self._closed.add(name)
            summary["providers"].append(name)
        return summary
