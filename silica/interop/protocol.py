"""Framing for the worker protocol.

A frame is:

    magic "SIW1" | version (1 byte) | kind (1 byte) | request id (4, big-endian)
    | payload length (4, big-endian) | payload (UTF-8 JSON)

JSON only: nothing is unpickled, so a compromised worker cannot execute code in
the host and a malformed payload cannot construct arbitrary objects. Every frame
is length-bounded, so a worker cannot make the host allocate without limit.
"""

import json
import struct

from .errors import InteropError

#: Bumped only for an incompatible framing or message-shape change.
PROTOCOL_VERSION = 1

MAGIC = b"SIW1"
_HEADER = struct.Struct(">4sBBII")

#: 8 MiB per frame. The context limit is configurable; this is the hard ceiling.
MAX_FRAME = 8 * 1024 * 1024

KINDS = {
    "hello": 1,
    "hello_ok": 2,
    "invoke": 3,
    "result": 4,
    "error": 5,
    "release": 6,
    "release_ok": 7,
    "close": 8,
    "bye": 9,
}
_BY_CODE = dict((code, name) for name, code in KINDS.items())


def encode(kind, request_id, payload=None):
    """Serialise one frame."""
    code = KINDS.get(kind)
    if code is None:
        raise ValueError("unknown frame kind %r" % (kind,))
    body = json.dumps(payload if payload is not None else {},
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise InteropError("value.size",
                           "frame payload is %d bytes, limit is %d"
                           % (len(body), MAX_FRAME))
    return _HEADER.pack(MAGIC, PROTOCOL_VERSION, code, request_id,
                        len(body)) + body


def read_exactly(stream, count):
    """Read exactly `count` bytes, or return fewer at end of stream."""
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream, max_size=MAX_FRAME):
    """Read one frame. Returns (kind, request_id, payload).

    Raises InteropError("protocol.frame") for a malformed or oversized frame and
    InteropError("protocol.version") for a version mismatch. Returns None at a
    clean end of stream.
    """
    header = read_exactly(stream, _HEADER.size)
    if not header:
        return None
    if len(header) < _HEADER.size:
        raise InteropError("protocol.frame", "truncated frame header")
    magic, version, code, request_id, length = _HEADER.unpack(header)
    if magic != MAGIC:
        raise InteropError("protocol.frame", "bad frame magic")
    if version != PROTOCOL_VERSION:
        raise InteropError(
            "protocol.version",
            "worker speaks protocol %d, this build implements %d"
            % (version, PROTOCOL_VERSION))
    if length > max_size:
        raise InteropError("value.size",
                           "frame of %d bytes exceeds the %d limit"
                           % (length, max_size))
    kind = _BY_CODE.get(code)
    if kind is None:
        raise InteropError("protocol.frame", "unknown frame kind code %d" % code)
    body = read_exactly(stream, length)
    if len(body) < length:
        raise InteropError("protocol.frame", "truncated frame body")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InteropError("protocol.frame",
                           "frame payload is not valid JSON: %s" % exc)
    if not isinstance(payload, dict):
        raise InteropError("protocol.frame", "frame payload is not an object")
    return kind, request_id, payload
