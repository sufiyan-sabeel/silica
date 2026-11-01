"""The Python provider: a separate worker process, JSON on a pipe.

No Python code runs inside the Silica VM. The worker is a child process that
speaks the framed protocol in `silica/interop/protocol.py`; the host side here
converts values, owns the opaque tokens and enforces the deadline.

What this does **not** do: it does not install packages, does not import anything
the caller did not name, does not read Silica's capabilities (the VM authorised
the native call before this ran), and does not attempt to sandbox the worker —
a Python worker can do whatever the Python process can do. `docs/SECURITY_MODEL.md`
states that limitation plainly.
"""

import os
import select
import subprocess
import sys

from .. import protocol
from ..errors import InteropError
from ..handles import ForeignHandle
from ..provider import ForeignType, Provider, Signature
from ..values import ForeignValue, Tag

#: The directory *containing* the `silica` package, so the worker can import it
#: without a global install (the worker is started with `-m`).
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(
    __import__("silica").__file__)))

DEFAULT_TIMEOUT = 10.0
#: A timed-out or crashed worker is not reused: it may be stuck mid-frame.
SHUTDOWN_GRACE = 1.0


class _FrameReader(object):
    """Reads frames from a pipe with a deadline and never blocks past it."""

    def __init__(self, stream):
        self.stream = stream
        self.fd = stream.fileno()
        self.buffer = bytearray()
        os.set_blocking(self.fd, False)

    def _fill(self, deadline, clock):
        """Read once into the buffer. Returns False at end of stream."""
        remaining = None if deadline is None else deadline - clock()
        if remaining is not None and remaining <= 0:
            raise InteropError("operation.timeout",
                               "the worker did not answer before its deadline",
                               provider="python",
                               hint="the call was abandoned and the worker stopped")
        ready, _, _ = select.select([self.fd], [], [], remaining)
        if not ready:
            raise InteropError("operation.timeout",
                               "the worker did not answer before its deadline",
                               provider="python",
                               hint="the call was abandoned and the worker stopped")
        try:
            chunk = os.read(self.fd, 65536)
        except (OSError, BlockingIOError):
            return True
        if not chunk:
            return False
        self.buffer.extend(chunk)
        return True

    def frame(self, deadline, clock):
        header = protocol._HEADER
        while len(self.buffer) < header.size:
            if not self._fill(deadline, clock):
                return None
        magic, version, code, request_id, length = header.unpack(
            bytes(self.buffer[:header.size]))
        if length > protocol.MAX_FRAME:
            raise InteropError("value.size",
                               "worker sent a frame of %d bytes" % length,
                               provider="python")
        total = header.size + length
        while len(self.buffer) < total:
            if not self._fill(deadline, clock):
                return None
        body = bytes(self.buffer[header.size:total])
        del self.buffer[:total]
        kind = protocol._BY_CODE.get(code)
        if magic != protocol.MAGIC or kind is None:
            raise InteropError("protocol.frame",
                               "worker sent a malformed frame", provider="python")
        if version != protocol.PROTOCOL_VERSION:
            raise InteropError(
                "protocol.version",
                "worker speaks protocol %d, this build implements %d"
                % (version, protocol.PROTOCOL_VERSION), provider="python")
        import json
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise InteropError("protocol.frame",
                               "worker sent a payload that is not JSON",
                               provider="python")
        return kind, request_id, payload


class PythonWorkerProvider(Provider):
    """Calls Python in a worker process, one operation at a time."""

    name = "python"
    version = "1.0"
    capabilities = ("interop.python",)

    def __init__(self, python=None, timeout=DEFAULT_TIMEOUT, clock=None,
                 worker_module="silica.interop.worker_main"):
        self.python = python or sys.executable
        self.worker_module = worker_module
        #: Post-execution summary, filled by close().
        self.last_report = {}
        self.timeout = timeout
        self._clock = clock or __import__("time").monotonic
        self._process = None
        self._reader = None
        self._next_id = 1
        self._objects = {}          # host token -> worker-side object id
        self._dead = False
        self._python_version = None

    # -- metadata ----------------------------------------------------------
    def operations(self):
        return {
            "import": Signature("import", [("module", ForeignType.of(Tag.STRING))],
                                ForeignType.handle("module")),
            "attr": Signature("attr", [("target", ForeignType.any()),
                                       ("name", ForeignType.of(Tag.STRING))],
                              ForeignType.any()),
            "call": Signature("call", [("target", ForeignType.any()),
                                       ("function", ForeignType.of(Tag.STRING)),
                                       ("args", ForeignType.of(Tag.LIST))],
                              ForeignType.any()),
            "release": Signature("release", [("handle", ForeignType.any())],
                                 ForeignType.any()),
        }

    @property
    def python_version(self):
        return self._python_version

    def alive(self):
        return (self._process is not None and not self._dead
                and self._process.poll() is None)

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        """Start the worker and complete the handshake. Idempotent."""
        if self.alive():
            return self
        if self._dead or self._process is not None:
            self._terminate()
        env = dict(os.environ)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (_PACKAGE_ROOT if not existing
                             else _PACKAGE_ROOT + os.pathsep + existing)
        try:
            self._process = subprocess.Popen(
                [self.python, "-u", "-m", self.worker_module],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, bufsize=0)
        except OSError as exc:
            raise InteropError("worker.start",
                               "could not start the Python worker: %s" % exc,
                               provider=self.name)
        self._reader = _FrameReader(self._process.stdout)
        self._dead = False
        deadline = self._clock() + self.timeout
        self._send("hello", {"protocol": protocol.PROTOCOL_VERSION})
        reply = self._read(deadline, "hello")
        if reply.get("protocol") != protocol.PROTOCOL_VERSION:
            self._terminate()
            raise InteropError(
                "protocol.version",
                "worker speaks protocol %r, this build implements %d"
                % (reply.get("protocol"), protocol.PROTOCOL_VERSION),
                provider=self.name)
        self._python_version = reply.get("python")
        return self

    def close(self):
        """Stop the worker and record what it left behind."""
        leaked = len(self._objects)
        was_alive = self.alive()
        if self._process is not None:
            if not self._dead and self._process.poll() is None:
                try:
                    self._send("close", {})
                    self._read(self._clock() + SHUTDOWN_GRACE, "close")
                except InteropError:
                    pass
            self._terminate()
        self.last_report = {
            "provider": self.name,
            "worker_was_running": was_alive,
            "worker_stopped": not self.alive(),
            "handles_leaked": leaked,
            "python": self._python_version,
        }
        return self.last_report

    def _terminate(self):
        self._dead = True
        process, self._process = self._process, None
        self._reader = None
        self._objects.clear()
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=SHUTDOWN_GRACE)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=SHUTDOWN_GRACE)
        except (OSError, subprocess.SubprocessError):
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    # -- transport ---------------------------------------------------------
    def _send(self, kind, payload):
        request_id = self._next_id
        self._next_id += 1
        try:
            self._process.stdin.write(protocol.encode(kind, request_id, payload))
            self._process.stdin.flush()
        except (OSError, ValueError):
            self._die()
        return request_id

    def _die(self):
        self._terminate()
        raise InteropError("worker.lost",
                           "the Python worker exited or its pipe closed",
                           provider=self.name,
                           hint="call python.start() again to get a new worker")

    def _read(self, deadline, operation):
        while True:
            try:
                frame = (self._reader.frame(deadline, self._clock)
                         if self._reader else None)
            except InteropError as err:
                if err.code == "operation.timeout":
                    # The worker may be stuck mid-frame, so the stream is no
                    # longer trustworthy: stop it rather than reuse it.
                    self._terminate()
                raise
            if frame is None:
                self._die()
            kind, _request_id, payload = frame
            if kind == "error":
                from ..validate import validate_error_payload
                error_type, error_message = validate_error_payload(
                    payload, self.name, operation)
                self._raise_worker_error(operation,
                                         {"type": error_type,
                                          "message": error_message})
            if kind in ("result", "hello_ok", "release_ok", "bye"):
                return payload.get("value", payload)
            if kind == "hello_ok":
                return payload
            self._die()

    def _raise_worker_error(self, operation, error):
        kind = error.get("type") or "Error"
        message = error.get("message") or "the worker reported a failure"
        if kind in ("ModuleNotFoundError", "ImportError"):
            raise InteropError("operation.failed",
                               "the worker could not import what was asked: %s"
                               % message, provider=self.name, operation=operation,
                               hint="install the package yourself; nothing is "
                                    "installed automatically")
        if kind in ("AttributeError", "TypeError", "KeyError", "ValueError"):
            raise InteropError("operation.failed",
                               "the worker rejected the call: %s" % message,
                               provider=self.name, operation=operation)
        raise InteropError("operation.failed", "%s: %s" % (kind, message),
                           provider=self.name, operation=operation)

    # -- the provider interface -------------------------------------------
    def invoke(self, operation, args, ctx):
        self.start()
        deadline = ctx.deadline if ctx.deadline is not None \
            else self._clock() + self.timeout
        if operation == "import":
            return self._do_import(args[0], ctx, deadline)
        if operation == "attr":
            return self._do_attr(args, ctx, deadline)
        if operation == "call":
            return self._do_call(args, ctx, deadline)
        if operation == "release":
            return self._do_release(args[0], ctx, deadline)
        raise InteropError("operation.unknown",
                           "the Python provider has no operation '%s'" % operation,
                           provider=self.name, operation=operation)

    def release(self, handle, ctx):
        self._do_release(handle, ctx, self._clock() + self.timeout)

    # -- operations --------------------------------------------------------
    def _handle_id(self, value, ctx, operation):
        handle = value
        if not isinstance(handle, ForeignHandle):
            raise InteropError("value.type",
                               "%s needs a handle, found %s"
                               % (operation, type(handle).__name__),
                               provider=self.name, operation=operation)
        if ctx.handles is not None:
            ctx.handles.use(handle, self.name, ctx.session)
        ident = self._objects.get(handle.token)
        if ident is None:
            raise InteropError("handle.owner",
                               "that handle was not created by this provider",
                               provider=self.name, operation=operation)
        return ident

    def _store(self, ctx, worker_id, kind):
        if ctx.handles is None:
            raise InteropError("handle.unknown",
                               "no handle registry is available",
                               provider=self.name)
        handle = ctx.handles.create(self.name, kind, ctx.session)
        self._objects[handle.token] = worker_id
        return ForeignValue.handle(handle)

    def _value(self, payload, ctx):
        """Validate a provider payload, then convert it. Never trusts it."""
        from ..validate import (is_handle_ref, validate_handle_ref,
                                validate_payload)
        if is_handle_ref(payload):
            ident, kind = validate_handle_ref(payload, ctx.limits, self.name,
                                              ctx.operation)
            return self._store(ctx, ident, kind)
        validate_payload(payload, ctx.limits, what="result", provider=self.name,
                         operation=ctx.operation)
        from ..values import from_silica
        return from_silica(payload, ctx.limits)

    def _do_import(self, module, ctx, deadline):
        self._send("invoke", {"op": "import", "module": module})
        return self._value(self._read(deadline, "import"), ctx)

    def _do_attr(self, args, ctx, deadline):
        target = args[0]
        payload = {"op": "attr", "name": args[1]}
        if isinstance(target, ForeignHandle):
            payload["target"] = {"__handle__": self._handle_id(target, ctx, "attr")}
        else:
            payload["target"] = target
        self._send("invoke", payload)
        return self._value(self._read(deadline, "attr"), ctx)

    def _do_call(self, args, ctx, deadline):
        target, function, call_args = args[0], args[1], args[2]
        payload = {"op": "call", "function": function,
                   "args": list(call_args or [])}
        if isinstance(target, ForeignHandle):
            payload["target"] = {"__handle__": self._handle_id(target, ctx, "call")}
        else:
            payload["target"] = target
        self._send("invoke", payload)
        return self._value(self._read(deadline, "call"), ctx)

    def _do_release(self, handle, ctx, deadline):
        if not isinstance(handle, ForeignHandle):
            raise InteropError("value.type", "release needs a handle",
                               provider=self.name, operation="release")
        ident = self._objects.get(handle.token)
        if ident is None:
            raise InteropError("handle.released",
                               "that handle is already released", provider=self.name)
        self._send("release", {"id": ident})
        self._read(deadline, "release")
        del self._objects[handle.token]
        if ctx.handles is not None:
            ctx.handles.release(handle)
        return ForeignValue.none()
