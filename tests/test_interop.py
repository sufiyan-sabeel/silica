"""The interoperability foundation: fake providers only.

Nothing here executes a foreign ecosystem. The providers in this file are fakes
that record what they were asked to do, which is exactly what is needed to prove
registration, invocation, error handling, the capability gate and handle
lifecycle before any real adapter exists.

The audit this design rests on is `docs/INTEROPERABILITY_AUDIT.md`; the design is
`docs/INTEROPERABILITY.md`.
"""

import os
import unittest

from silica import natives
from silica.bytecode import FORMAT_MAJOR, FORMAT_MINOR
from silica.capabilities import FS_READ, CapabilitySet
from silica.errors import SilicaTypeError
from silica.interop import (ABI_VERSION, ForeignHandle, ForeignType,
                            ForeignValue, HandleRegistry, InteropError,
                            InvocationContext, Limits, Provider,
                            ProviderRegistry, Signature, Tag, from_silica,
                            to_silica)

from .helpers import run


def string_type():
    return ForeignType.of(Tag.STRING)


class FakeEcho(Provider):
    """The smallest provider: one operation, no capability, records its calls."""

    name = "echo"
    version = "1.0"
    abi = ABI_VERSION
    capabilities = ()

    def __init__(self):
        self.calls = []
        self.closed = False

    def operations(self):
        return {"upper": Signature("upper", [("text", string_type())],
                                   string_type())}

    def invoke(self, operation, args, ctx):
        self.calls.append((operation, list(args)))
        return ForeignValue.string(args[0].upper())

    def release(self, handle, ctx):
        return None

    def close(self):
        self.closed = True


class FakeFiles(Provider):
    """A privileged fake: it asks the gate before touching a path."""

    name = "files"
    version = "1.0"
    abi = ABI_VERSION
    capabilities = (FS_READ,)

    def __init__(self):
        self.seen = []

    def operations(self):
        return {"read": Signature("read", [("path", string_type())],
                                  string_type())}

    def invoke(self, operation, args, ctx):
        # The same gate the VM uses for natives; the provider never resolves a
        # path itself.
        args = ctx.authorize(FS_READ, args, path_arg=0)
        self.seen.append(args[0])
        return ForeignValue.string("contents of %s" % os.path.basename(args[0]))

    def release(self, handle, ctx):
        return None


class FakeHandles(Provider):
    """Hands out a handle, then consumes it: the lifecycle in miniature."""

    name = "buffers"
    version = "1.0"
    abi = ABI_VERSION
    capabilities = ()

    def __init__(self):
        self.released = []

    def operations(self):
        return {
            "open": Signature("open", [], ForeignType.handle("buffer")),
            "size": Signature("size", [("buf", ForeignType.handle("buffer"))],
                              ForeignType.of(Tag.INT)),
        }

    def invoke(self, operation, args, ctx):
        if operation == "open":
            handle = ctx.handles.create(self.name, "buffer", ctx.session)
            return ForeignValue.handle(handle)
        handle = ctx.handles.use(args[0], self.name, ctx.session)
        return ForeignValue.int_(len(handle.token))

    def release(self, handle, ctx):
        self.released.append(handle)


class BrokenProviders(object):
    """Providers with deliberately bad metadata, one per failure mode."""

    class WrongAbi(FakeEcho):
        name = "wrongabi"
        abi = 99

    class UnknownCapability(FakeEcho):
        name = "badcap"
        capabilities = ("interop.python",)

    class BadSignature(FakeEcho):
        name = "badsig"

        def operations(self):
            return {"mismatch": Signature("other", [], None)}

    class NotAProvider(object):
        name = "nope"


def registry(**kwargs):
    return ProviderRegistry(**kwargs)


class RegistrationTests(unittest.TestCase):
    def test_a_provider_registers_and_describes_itself(self):
        reg = registry()
        reg.register(FakeEcho())
        self.assertEqual(reg.names(), ["echo"])
        described = reg.describe("echo")
        self.assertEqual(described["name"], "echo")
        self.assertEqual(described["abi"], ABI_VERSION)
        self.assertEqual(described["operations"], ["upper(text: string) -> string"])

    def test_describing_does_not_execute_anything(self):
        provider = FakeEcho()
        reg = registry()
        reg.register(provider)
        reg.describe("echo")
        reg.operations("echo")
        self.assertEqual(provider.calls, [])

    def test_a_duplicate_name_is_refused(self):
        reg = registry()
        reg.register(FakeEcho())
        with self.assertRaises(InteropError) as ctx:
            reg.register(FakeEcho())
        self.assertEqual(ctx.exception.code, "provider.duplicate")

    def test_a_mismatched_abi_is_refused(self):
        reg = registry()
        with self.assertRaises(InteropError) as ctx:
            reg.register(BrokenProviders.WrongAbi())
        self.assertEqual(ctx.exception.code, "provider.abi")
        self.assertIn(str(ABI_VERSION), ctx.exception.message)

    def test_an_unknown_capability_kind_is_refused(self):
        reg = registry()
        with self.assertRaises(InteropError) as ctx:
            reg.register(BrokenProviders.UnknownCapability())
        self.assertEqual(ctx.exception.code, "provider.capability")

    def test_a_malformed_signature_is_refused(self):
        reg = registry()
        with self.assertRaises(InteropError) as ctx:
            reg.register(BrokenProviders.BadSignature())
        self.assertEqual(ctx.exception.code, "provider.signature")

    def test_only_a_provider_can_be_registered(self):
        reg = registry()
        with self.assertRaises(InteropError) as ctx:
            reg.register(BrokenProviders.NotAProvider())
        self.assertEqual(ctx.exception.code, "provider.signature")

    def test_an_unknown_provider_is_named(self):
        with self.assertRaises(InteropError) as ctx:
            registry().invoke("nope", "x", [])
        self.assertEqual(ctx.exception.code, "provider.unknown")

    def test_unregister_closes_and_forgets(self):
        provider = FakeEcho()
        reg = registry()
        reg.register(provider)
        self.assertTrue(reg.unregister("echo"))
        self.assertTrue(provider.closed)
        self.assertEqual(reg.names(), [])
        self.assertFalse(reg.unregister("echo"))

    def test_a_closed_provider_cannot_be_invoked(self):
        reg = registry()
        reg.register(FakeEcho())
        reg.close()
        with self.assertRaises(InteropError) as ctx:
            reg.invoke("echo", "upper", ["x"])
        self.assertEqual(ctx.exception.code, "provider.closed")


class InvocationTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeEcho()
        self.reg = registry()
        self.reg.register(self.provider)

    def test_an_operation_runs_and_returns_a_foreign_value(self):
        result = self.reg.invoke("echo", "upper", ["hi"])
        self.assertIsInstance(result, ForeignValue)
        self.assertEqual(to_silica(result), "HI")
        self.assertEqual(self.provider.calls, [("upper", ["hi"])])

    def test_an_unknown_operation_lists_what_exists(self):
        with self.assertRaises(InteropError) as ctx:
            self.reg.invoke("echo", "nope", [])
        self.assertEqual(ctx.exception.code, "operation.unknown")
        self.assertIn("upper", ctx.exception.hint or "")

    def test_arity_is_checked(self):
        with self.assertRaises(InteropError) as ctx:
            self.reg.invoke("echo", "upper", [])
        self.assertEqual(ctx.exception.code, "operation.arity")

    def test_argument_types_are_checked(self):
        with self.assertRaises(InteropError) as ctx:
            self.reg.invoke("echo", "upper", [42])
        self.assertEqual(ctx.exception.code, "value.type")
        self.assertEqual(self.provider.calls, [])

    def test_a_provider_that_returns_a_raw_value_is_refused(self):
        class Raw(Provider):
            name = "raw"
            version = "1.0"

            def operations(self):
                return {"bad": Signature("bad", [], None)}

            def invoke(self, operation, args, ctx):
                return "not a foreign value"

            def release(self, handle, ctx):
                return None

        reg = registry()
        reg.register(Raw())
        with self.assertRaises(InteropError) as ctx:
            reg.invoke("raw", "bad", [])
        self.assertEqual(ctx.exception.code, "operation.failed")

    def test_a_result_of_the_wrong_tag_is_refused(self):
        class Liar(Provider):
            name = "liar"
            version = "1.0"

            def operations(self):
                return {"f": Signature("f", [], ForeignType.of(Tag.INT))}

            def invoke(self, operation, args, ctx):
                return ForeignValue.string("not an int")

            def release(self, handle, ctx):
                return None

        reg = registry()
        reg.register(Liar())
        with self.assertRaises(InteropError) as ctx:
            reg.invoke("liar", "f", [])
        self.assertEqual(ctx.exception.code, "value.type")

    def test_a_deadline_is_enforced(self):
        ctx = InvocationContext("echo", "upper", timeout=0)
        with self.assertRaises(InteropError) as exc:
            self.reg.invoke("echo", "upper", ["x"], ctx=ctx)
        self.assertEqual(exc.exception.code, "operation.timeout")


class CapabilityGateTests(unittest.TestCase):
    """The gate must be the same one the VM uses, and deny by default."""

    def test_a_privileged_call_without_grants_is_denied(self):
        provider = FakeFiles()
        reg = registry()
        reg.register(provider)
        with self.assertRaises(InteropError) as ctx:
            reg.invoke("files", "read", ["/etc/passwd"])
        self.assertEqual(ctx.exception.code, "operation.denied")
        self.assertEqual(provider.seen, [])          # no I/O was attempted

    def test_a_granted_call_receives_the_resolved_path(self):
        root = os.path.abspath(os.getcwd())
        caps = CapabilitySet().grant(FS_READ, root)
        provider = FakeFiles()
        reg = registry(capabilities=caps)
        reg.register(provider)
        result = reg.invoke("files", "read", [os.path.join(root, "notes.txt")])
        self.assertEqual(to_silica(result), "contents of notes.txt")
        self.assertEqual(provider.seen, [os.path.join(root, "notes.txt")])

    def test_a_path_outside_the_grant_is_denied(self):
        caps = CapabilitySet().grant(FS_READ, os.path.abspath("allowed"))
        provider = FakeFiles()
        reg = registry(capabilities=caps)
        reg.register(provider)
        with self.assertRaises(InteropError) as ctx:
            reg.invoke("files", "read", [os.path.abspath("elsewhere/secret.txt")])
        self.assertEqual(ctx.exception.code, "operation.denied")
        self.assertEqual(provider.seen, [])

    def test_an_operation_that_needs_no_capability_passes_through(self):
        reg = registry()
        reg.register(FakeEcho())
        self.assertEqual(to_silica(reg.invoke("echo", "upper", ["x"])), "X")

    def test_the_gate_is_the_capability_sets_authorize_call(self):
        # proves the reuse rather than reimplementing it: a recording set is
        # consulted exactly once, through the same method the VM calls
        class Recording(object):
            def __init__(self):
                self.calls = []

            def authorize_call(self, native, args):
                self.calls.append((native.requires, native.qualified, list(args)))
                return args

        recording = Recording()
        ctx = InvocationContext("files", "read", capabilities=recording)
        ctx.authorize(FS_READ, ["/tmp/x"], path_arg=0)
        self.assertEqual(len(recording.calls), 1)
        self.assertEqual(recording.calls[0][0], FS_READ)
        self.assertEqual(recording.calls[0][1], "files.read")


class HandleTests(unittest.TestCase):
    def test_create_use_release(self):
        reg = HandleRegistry()
        handle = reg.create("python", "file", session="s1")
        self.assertEqual(len(handle.token), 32)
        self.assertIs(reg.use(handle, "python", "s1"), handle)
        self.assertTrue(reg.release(handle))
        self.assertEqual(reg.live(), 0)

    def test_release_is_idempotent(self):
        reg = HandleRegistry()
        handle = reg.create("python", "file")
        self.assertTrue(reg.release(handle))
        self.assertFalse(reg.release(handle))

    def test_use_after_release_is_its_own_error(self):
        reg = HandleRegistry()
        handle = reg.create("python", "file")
        reg.release(handle)
        with self.assertRaises(InteropError) as ctx:
            reg.use(handle, "python")
        self.assertEqual(ctx.exception.code, "handle.released")

    def test_an_unknown_token_is_not_a_released_one(self):
        with self.assertRaises(InteropError) as ctx:
            HandleRegistry().use("0" * 32, "python")
        self.assertEqual(ctx.exception.code, "handle.unknown")

    def test_ownership_is_per_provider_and_session(self):
        reg = HandleRegistry()
        handle = reg.create("python", "file", session="s1")
        with self.assertRaises(InteropError) as ctx:
            reg.use(handle, "c", "s1")
        self.assertEqual(ctx.exception.code, "handle.owner")
        with self.assertRaises(InteropError) as ctx:
            reg.use(handle, "python", "s2")
        self.assertEqual(ctx.exception.code, "handle.owner")

    def test_a_session_release_frees_everything_it_owns(self):
        reg = HandleRegistry()
        reg.create("python", "file", session="s1")
        reg.create("c", "buffer", session="s1")
        reg.create("python", "file", session="s2")
        self.assertEqual(reg.release_session("s1"), 2)
        self.assertEqual(reg.live(), 1)

    def test_the_handle_limit_is_enforced(self):
        reg = HandleRegistry(max_handles=2)
        reg.create("python", "file")
        reg.create("python", "file")
        with self.assertRaises(InteropError) as ctx:
            reg.create("python", "file")
        self.assertIn("2 handles", ctx.exception.message)

    def test_a_handle_crosses_the_boundary_as_a_handle(self):
        provider = FakeHandles()
        reg = registry()
        reg.register(provider)
        opened = reg.invoke("buffers", "open", [])
        self.assertTrue(opened.is_handle)
        size = reg.invoke("buffers", "size", [to_silica(opened)])
        self.assertEqual(to_silica(size), 32)

    def test_a_handle_of_the_wrong_kind_is_refused(self):
        class WrongKind(Provider):
            name = "wrongkind"
            version = "1.0"

            def operations(self):
                return {"size": Signature("size",
                                          [("b", ForeignType.handle("file"))],
                                          ForeignType.of(Tag.INT))}

            def invoke(self, operation, args, ctx):
                return ForeignValue.int_(0)

            def release(self, handle, ctx):
                return None

        reg = registry()
        reg.register(WrongKind())
        reg.register(FakeHandles())
        opened = reg.invoke("buffers", "open", [])
        with self.assertRaises(InteropError) as ctx:
            reg.invoke("wrongkind", "size", [to_silica(opened)])
        self.assertEqual(ctx.exception.code, "value.type")


class ValueTests(unittest.TestCase):
    def test_scalars_round_trip(self):
        for value in (None, True, False, 0, -1, 2 ** 62, 1.5, "text"):
            self.assertEqual(to_silica(from_silica(value)), value)

    def test_containers_round_trip(self):
        value = {"a": [1, 2.5, "x", True, None], "b": {"c": 3}}
        self.assertEqual(to_silica(from_silica(value)), value)

    def test_bytes_survive(self):
        self.assertEqual(to_silica(from_silica(b"\x00\xff")), b"\x00\xff")

    def test_a_bool_is_not_an_int(self):
        self.assertEqual(from_silica(True).tag, Tag.BOOL)

    def test_an_int_outside_64_bits_is_refused(self):
        with self.assertRaises(InteropError) as ctx:
            from_silica(2 ** 63)
        self.assertEqual(ctx.exception.code, "value.range")

    def test_a_map_key_must_be_a_string(self):
        with self.assertRaises(InteropError) as ctx:
            from_silica({1: "a"})
        self.assertEqual(ctx.exception.code, "value.type")

    def test_a_cycle_is_refused(self):
        loop = []
        loop.append(loop)
        with self.assertRaises(InteropError) as ctx:
            from_silica(loop)
        self.assertEqual(ctx.exception.code, "value.cycle")

    def test_depth_is_bounded(self):
        value = []
        cursor = value
        for _ in range(40):
            child = []
            cursor.append(child)
            cursor = child
        with self.assertRaises(InteropError) as ctx:
            from_silica(value, Limits(max_depth=8))
        self.assertEqual(ctx.exception.code, "value.depth")

    def test_size_is_bounded(self):
        with self.assertRaises(InteropError) as ctx:
            from_silica("x" * 100, Limits(max_bytes=10))
        self.assertEqual(ctx.exception.code, "value.size")

    def test_a_struct_or_class_does_not_cross_implicitly(self):
        class Thing(object):
            pass

        with self.assertRaises(InteropError) as ctx:
            from_silica(Thing())
        self.assertEqual(ctx.exception.code, "value.type")

    def test_errors_carry_a_stable_code_and_no_secret(self):
        error = InteropError("handle.released", "gone", provider="python",
                             operation="read")
        self.assertEqual(error.context()["code"], "handle.released")
        self.assertNotIn("token", error.message)
        with self.assertRaises(ValueError):
            InteropError("not.a.code", "x")


class IsolationTests(unittest.TestCase):
    """The foundation must not change the language or the standard library."""

    def test_no_interop_module_exists_for_silica_source(self):
        self.assertNotIn("interop", natives.MODULES)
        self.assertIsNone(natives.get_native("interop", "call"))

    def test_use_interop_still_fails_as_unknown(self):
        with self.assertRaises(SilicaTypeError) as ctx:
            run("use interop\nsfn main() {\n}\n")
        self.assertIn("unknown module", str(ctx.exception))

    def test_no_provider_operation_enters_the_native_namespace(self):
        before = set(natives.MODULES)
        reg = registry()
        reg.register(FakeEcho())
        reg.invoke("echo", "upper", ["x"])
        self.assertEqual(set(natives.MODULES), before)
        self.assertNotIn("echo", natives.MODULES)

    def test_the_bytecode_format_is_unchanged(self):
        self.assertEqual((FORMAT_MAJOR, FORMAT_MINOR), (1, 0))

    def test_the_package_executes_nothing(self):
        # No process, no library, no socket: the foundation is data structures.
        package = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "silica", "interop")
        forbidden = ("subprocess", "ctypes", "socket", "os.system", "popen",
                     "multiprocessing", "threading")
        for name in sorted(os.listdir(package)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(package, name), encoding="utf-8") as handle:
                text = handle.read()
            for word in forbidden:
                self.assertNotIn(word, text,
                                 "%s mentions %s" % (name, word))


class ShutdownTests(unittest.TestCase):
    def test_close_releases_handles_and_closes_providers(self):
        provider = FakeEcho()
        handles = HandleRegistry()
        handles.create("echo", "buffer", session=None)
        reg = ProviderRegistry(handles=handles)
        reg.register(provider)
        summary = reg.close()
        self.assertEqual(summary["providers"], ["echo"])
        self.assertEqual(summary["handles_released"], 1)
        self.assertTrue(provider.closed)
        self.assertEqual(handles.live(), 0)

    def test_stats_never_contain_tokens(self):
        reg = HandleRegistry()
        handle = reg.create("python", "file")
        stats = reg.stats()
        self.assertEqual(stats["live"], 1)
        self.assertNotIn(handle.token, str(stats))


if __name__ == "__main__":
    unittest.main()
