"""The Python worker process.

Started by `silica.interop.providers.python_worker` as a child process; it speaks
the framed JSON protocol on stdin/stdout and nothing else. It is the only place
where foreign Python code runs, and it runs outside the Silica VM.

Safety properties:
- JSON only. Nothing is unpickled, so a hostile payload cannot execute code.
- No ambient authority: the worker does not read Silica's capabilities, does not
  touch the filesystem itself, and only does what the imported module's code does.
- Every object it hands out is referenced by an integer id it owns; the host keeps
  the opaque token, so a Silica program never sees either an address or a Python
  object.
- A failure is reported as a type name and a one-line message, never a traceback,
  so host paths and internals do not leak.

Run by hand to debug:  python -m silica.interop.worker_main
"""

import base64
import json
import sys

from . import protocol

#: Objects this worker is holding, by id. The host owns the opaque tokens; this
#: table only exists so an object can be found again for the next call.
_OBJECTS = {}
_NEXT_ID = [1]

#: Message text is truncated: an exception message is a diagnostic, not a channel.
MAX_MESSAGE = 500


def _new_handle(value, kind=None):
    ident = _NEXT_ID[0]
    _NEXT_ID[0] += 1
    _OBJECTS[ident] = value
    return {"__handle__": ident, "kind": kind or type(value).__name__}


def _encode(value, depth=0):
    """Python value -> JSON-safe payload."""
    if depth > 32:
        return {"__error__": {"type": "DepthError",
                              "message": "value nests deeper than 32 levels"}}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [_encode(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value):
            return dict((key, _encode(item, depth + 1))
                        for key, item in value.items())
        return _new_handle(value, "dict")
    if isinstance(value, (set, frozenset)):
        return _new_handle(value, "set")
    return _new_handle(value)


def _decode(value):
    """JSON-safe payload -> Python value."""
    if isinstance(value, dict):
        if "__handle__" in value:
            ident = value["__handle__"]
            if ident not in _OBJECTS:
                raise KeyError("handle %r is not held by this worker" % (ident,))
            return _OBJECTS[ident]
        if "__bytes__" in value:
            return base64.b64decode(value["__bytes__"])
        return dict((key, _decode(item)) for key, item in value.items())
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def _failure(exc):
    message = str(exc).replace("\n", " ")[:MAX_MESSAGE]
    return {"__error__": {"type": type(exc).__name__, "message": message}}


def _invoke(payload):
    operation = payload.get("op")
    if operation == "import":
        module = payload.get("module")
        if not isinstance(module, str) or not module:
            raise ValueError("import needs a module name")
        return _new_handle(__import__(module), "module")
    if operation == "attr":
        target = _decode(payload.get("target"))
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("attr needs an attribute name")
        return _encode(getattr(target, name))
    if operation == "call":
        target = _decode(payload.get("target"))
        function = payload.get("function")
        args = [_decode(item) for item in payload.get("args") or []]
        kwargs = dict((key, _decode(item))
                      for key, item in (payload.get("kwargs") or {}).items())
        if function is None:
            callable_ = target
        else:
            if not isinstance(function, str):
                raise ValueError("call needs a function name")
            callable_ = getattr(target, function)
        if not callable(callable_):
            raise TypeError("%r is not callable" % (function or "target",))
        return _encode(callable_(*args, **kwargs))
    if operation == "release":
        ident = payload.get("id")
        if ident in _OBJECTS:
            del _OBJECTS[ident]
            return {"released": True}
        return {"released": False}
    raise ValueError("unknown operation %r" % (operation,))


def _write(kind, request_id, payload):
    sys.stdout.buffer.write(protocol.encode(kind, request_id, payload))
    sys.stdout.buffer.flush()


def main():
    stream = sys.stdin.buffer
    while True:
        try:
            frame = protocol.read_frame(stream)
        except Exception as exc:                     # a broken frame ends the worker
            _write("error", 0, _failure(exc))
            return 1
        if frame is None:
            return 0
        kind, request_id, payload = frame
        if kind == "hello":
            offered = payload.get("protocol")
            if offered != protocol.PROTOCOL_VERSION:
                _write("error", request_id,
                       {"__error__": {"type": "ProtocolVersion",
                                      "message": "host speaks protocol %r, this "
                                                 "worker implements %d"
                                                 % (offered, protocol.PROTOCOL_VERSION)}})
                return 1
            _write("hello_ok", request_id,
                   {"protocol": protocol.PROTOCOL_VERSION,
                    "implementation": "CPython",
                    "python": "%d.%d.%d" % sys.version_info[:3]})
            continue
        if kind == "invoke":
            try:
                result = _invoke(payload)
            except BaseException as exc:             # noqa: BLE001 - reported, not swallowed
                _write("error", request_id, _failure(exc))
                continue
            if isinstance(result, dict) and "__error__" in result:
                _write("error", request_id, result)
            else:
                _write("result", request_id, {"value": result})
            continue
        if kind == "release":
            ident = payload.get("id")
            released = _OBJECTS.pop(ident, None) is not None
            _write("release_ok", request_id, {"released": released})
            continue
        if kind == "close":
            _OBJECTS.clear()
            _write("bye", request_id, {"closed": True})
            return 0
        _write("error", request_id,
               {"__error__": {"type": "ProtocolError",
                              "message": "unexpected frame kind %r" % (kind,)}})
        return 1


if __name__ == "__main__":
    sys.exit(main())
