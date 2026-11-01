"""The `python` module: Silica's first real interoperability surface.

Every function here is a native, so it is compiled to `CALL_NATIVE`, verified
against this table at load, and authorised at the VM's single gate before its
body runs. The provider registry behind it is separate from the standard-library
native registry, as `docs/INTEROPERABILITY.md` requires.

    use python
    let m: Any = python.import("math")
    sprint(python.call(m, "sqrt", [2.0]))   # 1.4142...
    python.release(m)
    python.stop()

Capability: `interop.python` (grant with `--allow-interop-python`). Without it
every call here is refused before the worker is even started.
"""

from . import InvocationContext, InteropError, ProviderRegistry, HandleRegistry
from .providers import PythonWorkerProvider

#: One worker per interpreter process, started on first use and stopped by
#: `python.stop()` or at exit. Kept here rather than in the VM so that the VM
#: keeps knowing nothing about foreign runtimes.
_SESSION = {"registry": None, "provider": None, "handles": None}


def _session():
    if _SESSION["registry"] is None:
        handles = HandleRegistry()
        provider = PythonWorkerProvider()
        registry = ProviderRegistry(handles=handles)
        registry.register(provider)
        _SESSION.update(registry=registry, provider=provider, handles=handles)
    return _SESSION["registry"], _SESSION["provider"], _SESSION["handles"]


def _context(operation):
    _registry, provider, handles = _session()
    return InvocationContext(provider.name, operation, handles=handles,
                             timeout=provider.timeout)


def _result(foreign):
    """A foreign value becomes a Silica value, or a handle the program can pass back."""
    from .values import to_silica
    return to_silica(foreign)


def _start(ctx, args):
    _registry, provider, _handles = _session()
    provider.start()
    return None


def _stop(ctx, args):
    _registry, provider, _handles = _session()
    if provider is not None:
        provider.close()
    _SESSION.update(registry=None, provider=None, handles=None)
    return None


def _import(ctx, args):
    module = args[0]
    if not isinstance(module, str):
        raise InteropError("value.type", "python.import needs a module name",
                           provider="python", operation="import")
    registry, _provider, _handles = _session()
    return _result(registry.invoke("python", "import", [module],
                                   ctx=_context("import")))


def _attr(ctx, args):
    registry, _provider, _handles = _session()
    return _result(registry.invoke("python", "attr", [args[0], args[1]],
                                   ctx=_context("attr")))


def _call(ctx, args):
    target, function = args[0], args[1]
    call_args = args[2] if len(args) > 2 else []
    if not isinstance(function, str):
        raise InteropError("value.type", "python.call needs a function name",
                           provider="python", operation="call")
    if not isinstance(call_args, list):
        raise InteropError("value.type", "python.call needs a List of arguments",
                           provider="python", operation="call")
    registry, _provider, _handles = _session()
    return _result(registry.invoke("python", "call", [target, function, call_args],
                                   ctx=_context("call")))


def _release(ctx, args):
    registry, _provider, _handles = _session()
    registry.invoke("python", "release", [args[0]], ctx=_context("release"))
    return None


def _info(ctx, args):
    _registry, provider, handles = _session()
    return {
        "running": provider.alive() if provider is not None else False,
        "python": provider.python_version if provider is not None else None,
        "handles": handles.live() if handles is not None else 0,
        "capability": "interop.python",
    }


#: (name, params, ret, function, min_args, max_args, requires, path_arg)
FUNCTIONS = (
    ("start", [], "Unit", _start, 0, 0, "interop.python", None),
    ("stop", [], "Unit", _stop, 0, 0, "interop.python", None),
    ("import", ["String"], "Any", _import, 1, 1, "interop.python", None),
    ("attr", ["Any", "String"], "Any", _attr, 2, 2, "interop.python", None),
    ("call", ["Any", "String", "List"], "Any", _call, 2, 3, "interop.python", None),
    ("release", ["Any"], "Unit", _release, 1, 1, "interop.python", None),
    # Metadata only, so it needs no capability: it starts nothing.
    ("info", [], "Map", _info, 0, 0, None, None),
)
