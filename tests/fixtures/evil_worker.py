"""A deliberately hostile worker, used only by the adversarial tests.

It speaks the framing correctly and then sends output a well-behaved worker never
would, one mode per run (SILICA_EVIL_MODE). The host must reject every one of
these with a structured InteropError and stay usable.
"""

import os
import sys

from silica.interop import protocol

MODE = os.environ.get("SILICA_EVIL_MODE", "deep")


def _write(kind, request_id, payload):
    sys.stdout.buffer.write(protocol.encode(kind, request_id, payload))
    sys.stdout.buffer.flush()


def _raw(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _bad_value():
    if MODE == "deep":
        value = "x"
        for _ in range(200):
            value = [value]
        return value
    if MODE == "huge":
        return "y" * (2 * 1024 * 1024)
    if MODE == "badhandle":
        return {"__handle__": "not an int"}
    if MODE == "badkind":
        return {"__handle__": 1, "kind": "/etc/passwd"}
    if MODE == "extrakey":
        return {"__handle__": 1, "kind": "module", "evil": True}
    if MODE == "reserved":
        return {"inner": {"__error__": {"type": "X", "message": "y"}}}
    if MODE == "boolhandle":
        return {"__handle__": True, "kind": "module"}
    return None


def main():
    stream = sys.stdin.buffer
    while True:
        frame = protocol.read_frame(stream)
        if frame is None:
            return 0
        kind, request_id, payload = frame
        if kind == "hello":
            _write("hello_ok", request_id,
                   {"protocol": protocol.PROTOCOL_VERSION, "python": "evil"})
            continue
        if kind == "close":
            _write("bye", request_id, {"closed": True})
            return 0
        if kind == "invoke":
            if MODE == "notjson":
                header = protocol._HEADER.pack(protocol.MAGIC,
                                               protocol.PROTOCOL_VERSION,
                                               protocol.KINDS["result"],
                                               request_id, 5)
                _raw(header + b"{{{{{")
                continue
            if MODE == "truncated":
                header = protocol._HEADER.pack(protocol.MAGIC,
                                               protocol.PROTOCOL_VERSION,
                                               protocol.KINDS["result"],
                                               request_id, 100)
                _raw(header + b"{\"value\": ")
                return 0
            if MODE == "badkindcode":
                header = protocol._HEADER.pack(protocol.MAGIC,
                                               protocol.PROTOCOL_VERSION,
                                               250, request_id, 2)
                _raw(header + b"{}")
                continue
            if MODE == "crash":
                return 3
            if MODE == "errorframe":
                _write("error", request_id,
                       {"__error__": {"type": "Explosion",
                                      "message": "line one\nline two"}})
                continue
            _write("result", request_id, {"value": _bad_value()})
            continue
        _write("bye", request_id, {"closed": True})
        return 0


if __name__ == "__main__":
    sys.exit(main())
