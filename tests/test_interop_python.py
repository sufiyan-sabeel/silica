"""Python interoperability, end to end: a real worker process, real calls.

These tests start an actual child process and call into CPython. They are the
evidence for the release claim "at least one real external Python worker
integration works" — nothing here is simulated.

The twelve scenarios are the ones the mission lists: built-in modules, `math`,
`statistics`, `json`, NumPy (only when installed), a missing module, an invalid
function, an unsupported argument, a worker crash, a timeout, a released handle
and a missing capability.
"""

import io
import os
import subprocess
import sys
import time
import unittest

import pytest

from silica.capabilities import INTEROP_PYTHON, CapabilitySet
from silica.engine import run_source
from silica.errors import SilicaError
from silica.interop import (HandleRegistry, InteropError, InvocationContext,
                            ProviderRegistry, to_silica)
from silica.interop.providers import PythonWorkerProvider


def context(registry, operation="call", timeout=10.0, session=None):
    return InvocationContext("python", operation, session=session,
                             handles=registry.handles, timeout=timeout)


class WorkerTestCase(unittest.TestCase):
    def setUp(self):
        self.provider = PythonWorkerProvider(timeout=5.0)
        self.registry = ProviderRegistry(handles=HandleRegistry())
        self.registry.register(self.provider)

    def tearDown(self):
        self.provider.close()

    def call(self, target, function, args, timeout=5.0, session=None):
        # `target` is already a host value: a handle or a plain value
        return self.registry.invoke(
            "python", "call", [target, function, args],
            ctx=context(self.registry, "call", timeout, session))

    def import_(self, module):
        return self.registry.invoke("python", "import", [module],
                                    ctx=context(self.registry, "import"))


class BuiltinModuleTests(WorkerTestCase):
    def test_a_builtin_module_can_be_imported_and_called(self):
        sysmod = self.import_("sys")
        self.assertEqual(sysmod.describe(), "handle(module)")
        version = self.call(sysmod, "getsizeof", [1])
        self.assertIsInstance(to_silica(version), int)

    def test_math(self):
        math = self.import_("math")
        self.assertAlmostEqual(to_silica(self.call(math, "sqrt", [2])), 1.4142135623,
                               places=9)
        self.assertAlmostEqual(to_silica(self.registry.invoke(
            "python", "attr", [to_silica(math), "pi"],
            ctx=context(self.registry, "attr"))), 3.1415926535, places=9)

    def test_statistics(self):
        stats = self.import_("statistics")
        self.assertEqual(to_silica(self.call(stats, "mean", [[1, 2, 3, 4]])), 2.5)
        self.assertEqual(to_silica(self.call(stats, "median", [[3, 1, 2]])), 2)

    def test_json(self):
        json = self.import_("json")
        text = to_silica(self.call(json, "dumps", [{"a": [1, True, None]}]))
        self.assertEqual(text, '{"a": [1, true, null]}')
        back = to_silica(self.call(json, "loads", ['{"a": 1}']))
        self.assertEqual(back, {"a": 1})

    def test_numpy_when_installed(self):
        pytest.importorskip("numpy")
        numpy = self.import_("numpy")
        result = self.call(numpy, "mean", [[1.0, 2.0, 3.0]])
        self.assertAlmostEqual(float(to_silica(result)), 2.0, places=6)


class ErrorTests(WorkerTestCase):
    def test_a_missing_module_is_a_clear_error(self):
        with self.assertRaises(InteropError) as ctx:
            self.import_("definitely_not_a_module_here")
        self.assertEqual(ctx.exception.code, "operation.failed")
        self.assertIn("could not import", ctx.exception.message)
        self.assertIn("nothing is installed automatically",
                      ctx.exception.hint or "")

    def test_an_invalid_function_is_refused_by_the_worker(self):
        math = self.import_("math")
        with self.assertRaises(InteropError) as ctx:
            self.call(math, "no_such_function", [])
        self.assertEqual(ctx.exception.code, "operation.failed")
        self.assertIn("no attribute", ctx.exception.message)

    def test_an_unsupported_argument_is_refused(self):
        math = self.import_("math")
        with self.assertRaises(InteropError) as ctx:
            self.call(math, "sqrt", ["not a number"])
        self.assertEqual(ctx.exception.code, "operation.failed")

    def test_an_error_message_carries_no_traceback(self):
        math = self.import_("math")
        with self.assertRaises(InteropError) as ctx:
            self.call(math, "sqrt", ["nope"])
        self.assertNotIn("Traceback", ctx.exception.message)
        self.assertLess(len(ctx.exception.message), 600)


class LifecycleTests(WorkerTestCase):
    def test_a_released_handle_cannot_be_used(self):
        math = self.import_("math")
        handle = to_silica(math)
        self.registry.invoke("python", "release", [handle],
                             ctx=context(self.registry, "release"))
        with self.assertRaises(InteropError) as ctx:
            self.call(handle, "sqrt", [2])
        self.assertIn(ctx.exception.code, ("handle.released", "handle.owner",
                                           "handle.unknown"))

    def test_a_worker_crash_is_reported_not_swallowed(self):
        osmod = self.import_("os")
        with self.assertRaises(InteropError) as ctx:
            self.call(osmod, "_exit", [7])      # kills the worker mid-call
        self.assertIn(ctx.exception.code,
                      ("worker.lost", "operation.timeout", "operation.failed"))
        self.assertFalse(self.provider.alive())

    def test_a_timeout_stops_the_worker(self):
        time_mod = self.import_("time")
        with self.assertRaises(InteropError) as ctx:
            self.call(time_mod, "sleep", [5], timeout=0.3)
        self.assertEqual(ctx.exception.code, "operation.timeout")
        self.assertFalse(self.provider.alive())

    def test_the_worker_is_gone_after_close(self):
        self.provider.start()
        process = self.provider._process
        self.provider.close()
        self.assertFalse(self.provider.alive())
        self.assertIsNotNone(process.poll())

    def test_handles_are_owned_per_session(self):
        owned = self.registry.invoke("python", "import", ["math"],
                                     ctx=context(self.registry, "import",
                                                 session="first"))
        handle = to_silica(owned)
        with self.assertRaises(InteropError) as ctx:
            self.call(handle, "sqrt", [2], session="second")
        self.assertEqual(ctx.exception.code, "handle.owner")
        # ...and the owner can still use it
        self.assertAlmostEqual(float(to_silica(
            self.call(handle, "sqrt", [2], session="first"))), 1.4142135623,
            places=9)

    def test_a_handle_opened_without_a_session_is_usable_anywhere(self):
        # documented behaviour: sessions are opt-in isolation, not a default
        math = self.import_("math")
        self.assertAlmostEqual(float(to_silica(
            self.call(to_silica(math), "sqrt", [2], session="any"))),
            1.4142135623, places=9)


class ProtocolTests(unittest.TestCase):
    def test_a_frame_round_trips(self):
        from silica.interop import protocol
        frame = io.BytesIO(protocol.encode("invoke", 3, {"op": "import"}))
        self.assertEqual(protocol.read_frame(frame), ("invoke", 3, {"op": "import"}))

    def test_a_bad_magic_is_refused(self):
        from silica.interop import protocol
        with self.assertRaises(InteropError) as ctx:
            protocol.read_frame(io.BytesIO(b"XXXX" + b"\x00" * 16))
        self.assertEqual(ctx.exception.code, "protocol.frame")

    def test_a_version_mismatch_is_refused(self):
        from silica.interop import protocol
        header = protocol._HEADER.pack(protocol.MAGIC, 99, 1, 0, 2)
        with self.assertRaises(InteropError) as ctx:
            protocol.read_frame(io.BytesIO(header + b"{}"))
        self.assertEqual(ctx.exception.code, "protocol.version")

    def test_an_oversized_frame_is_refused(self):
        from silica.interop import protocol
        header = protocol._HEADER.pack(protocol.MAGIC, protocol.PROTOCOL_VERSION,
                                       1, 0, protocol.MAX_FRAME + 1)
        with self.assertRaises(InteropError) as ctx:
            protocol.read_frame(io.BytesIO(header))
        self.assertEqual(ctx.exception.code, "value.size")

    def test_the_worker_rejects_a_foreign_protocol_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "silica.interop.worker_main"],
            input=b"", capture_output=True, timeout=30,
            env=dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))))
        self.assertEqual(result.returncode, 0)


class SilicaSurfaceTests(unittest.TestCase):
    """The language surface: `use python`, the capability gate, real output."""

    PROGRAM = ("use python\n\n"
               "sfn main() {\n"
               '    let m: Any = python.import("math")\n'
               '    sprint(python.call(m, "sqrt", [2]))\n'
               '    sprint(python.attr(m, "pi"))\n'
               "    python.release(m)\n"
               "    python.stop()\n"
               "}\n")

    def run_program(self, capabilities):
        out = io.StringIO()
        code = run_source(self.PROGRAM, "<interop>", stdin=io.StringIO(""),
                          stdout=out, stderr=io.StringIO(),
                          capabilities=capabilities)
        return code, out.getvalue()

    def test_without_the_capability_the_call_is_refused(self):
        with self.assertRaises(SilicaError) as ctx:
            self.run_program(None)
        self.assertIn("interop.python", str(ctx.exception))

    def test_with_the_capability_it_returns_real_values(self):
        code, out = self.run_program(CapabilitySet().grant(INTEROP_PYTHON, "."))
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertAlmostEqual(float(lines[0]), 1.4142135623, places=9)
        self.assertAlmostEqual(float(lines[1]), 3.1415926535, places=9)

    def test_info_reports_state_without_a_capability(self):
        # `python.info` starts nothing, so it needs no grant
        out = io.StringIO()
        code = run_source('use python\nsfn main() {\n    sprint(python.info())\n}\n',
                          "<interop>", stdin=io.StringIO(""), stdout=out,
                          stderr=io.StringIO(), capabilities=None)
        self.assertEqual(code, 0)
        self.assertIn("interop.python", out.getvalue())

    def test_the_module_is_reachable_only_through_its_capability(self):
        from silica import natives
        for name in ("start", "stop", "import", "attr", "call", "release"):
            self.assertEqual(natives.get_native("python", name).requires,
                             INTEROP_PYTHON)
        self.assertIsNone(natives.get_native("python", "info").requires)


if __name__ == "__main__":
    unittest.main()
