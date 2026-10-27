"""Capability model tests.

These cover the four things the model has to get right: least privilege by
default, grants that are scoped to roots, denies that override grants, and
inheritance that can only narrow. They also assert the structural guarantee —
that no privileged native exists without a declared capability, and that the VM
authorises the call rather than the native checking itself.
"""

import os
import tempfile
import unittest

from silica import capabilities
from silica.capabilities import (FS_LIST, FS_READ, FS_WRITE, KNOWN, CapabilitySet)
from silica.errors import CapabilityError
from silica.natives import MODULES
from silica.vm import VM

from .helpers import run


class DefaultDenyTests(unittest.TestCase):
    def test_empty_set_grants_nothing(self):
        caps = CapabilitySet.empty()
        self.assertTrue(caps.is_empty())
        for kind in KNOWN:
            self.assertFalse(caps.is_granted(kind))
            with self.assertRaises(CapabilityError):
                caps.require(kind)

    def test_empty_set_message_names_the_flag(self):
        caps = CapabilitySet.empty()
        with self.assertRaises(CapabilityError) as ctx:
            caps.require(FS_READ)
        self.assertIn("not granted", str(ctx.exception))
        self.assertIn("--allow-fs-read", ctx.exception.hint)

    def test_report_of_empty_set(self):
        text = "\n".join(CapabilitySet.empty().report())
        for kind in KNOWN:
            self.assertIn(kind, text)
            self.assertIn("not granted", text)


class GrantTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.data = os.path.join(self.root, "data")
        os.makedirs(self.data)
        self.inner = os.path.join(self.data, "inner.txt")
        with open(self.inner, "w", encoding="utf-8") as handle:
            handle.write("x")

    def test_grant_allows_inside_root(self):
        caps = CapabilitySet.empty(base=self.root).grant(FS_READ, "data")
        self.assertTrue(caps.is_granted(FS_READ))
        resolved = caps.resolve_path(FS_READ, "data/inner.txt")
        self.assertEqual(resolved, self.inner)

    def test_grant_does_not_cover_siblings(self):
        caps = CapabilitySet.empty(base=self.root).grant(FS_READ, "data")
        with self.assertRaises(CapabilityError) as ctx:
            caps.resolve_path(FS_READ, "elsewhere.txt")
        self.assertIn("outside the granted roots", str(ctx.exception))

    def test_traversal_is_refused(self):
        caps = CapabilitySet.empty(base=self.root).grant(FS_READ, "data")
        with self.assertRaises(CapabilityError) as ctx:
            caps.resolve_path(FS_READ, "data/../../etc/passwd")
        self.assertIn("traversal", ctx.exception.hint)

    def test_symlink_escape_is_refused(self):
        outside = os.path.join(self.root, "secret.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("secret")
        link = os.path.join(self.data, "link.txt")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):  # pragma: no cover
            self.skipTest("symlinks unavailable")
        caps = CapabilitySet.empty(base=self.root).grant(FS_READ, "data")
        with self.assertRaises(CapabilityError):
            caps.resolve_path(FS_READ, "data/link.txt")

    def test_grant_is_immutable(self):
        base = CapabilitySet.empty(base=self.root)
        granted = base.grant(FS_READ, "data")
        self.assertFalse(base.is_granted(FS_READ))
        self.assertTrue(granted.is_granted(FS_READ))

    def test_unknown_capability_is_refused(self):
        with self.assertRaises(CapabilityError) as ctx:
            CapabilitySet.empty().grant("fs.delete", "data")
        self.assertIn("unknown capability", str(ctx.exception))


class DenyTests(unittest.TestCase):
    def test_deny_overrides_grant(self):
        caps = (CapabilitySet.empty(base="/tmp")
                .grant(FS_WRITE, "/tmp")
                .deny(FS_WRITE))
        self.assertFalse(caps.is_granted(FS_WRITE))
        with self.assertRaises(CapabilityError) as ctx:
            caps.require(FS_WRITE)
        self.assertIn("denied", str(ctx.exception))

    def test_deny_is_reported(self):
        caps = CapabilitySet.empty().deny(FS_LIST)
        self.assertIn("denied", "\n".join(caps.report()))

    def test_deny_survives_a_later_grant(self):
        caps = CapabilitySet.empty(base="/tmp").deny(FS_READ).grant(FS_READ, "/tmp")
        self.assertFalse(caps.is_granted(FS_READ))


class DeriveTests(unittest.TestCase):
    def test_derive_can_narrow(self):
        caps = (CapabilitySet.empty(base="/tmp")
                .grant(FS_READ, "/tmp")
                .grant(FS_READ, "/usr"))
        narrower = caps.derive(grants={FS_READ: "/tmp"})
        self.assertEqual(narrower.roots(FS_READ), ("/tmp",))

    def test_derive_cannot_widen_a_root(self):
        caps = CapabilitySet.empty(base="/tmp").grant(FS_READ, "/tmp")
        with self.assertRaises(CapabilityError) as ctx:
            caps.derive(grants={FS_READ: "/etc"})
        self.assertIn("not granted", str(ctx.exception))

    def test_derive_cannot_add_an_ungranted_capability(self):
        caps = CapabilitySet.empty(base="/tmp").grant(FS_READ, "/tmp")
        with self.assertRaises(CapabilityError):
            caps.derive(grants={FS_WRITE: "/tmp"})

    def test_derive_cannot_revive_a_denied_capability(self):
        caps = CapabilitySet.empty(base="/tmp").grant(FS_READ, "/tmp").deny(FS_READ)
        with self.assertRaises(CapabilityError):
            caps.derive(grants={FS_READ: "/tmp"})


class ConfigTests(unittest.TestCase):
    def test_nested_shape(self):
        caps = CapabilitySet.from_mapping(
            {"fs": {"read": ["data"], "list": ["data"]}, "deny": ["fs.write"]},
            base="/tmp")
        self.assertTrue(caps.is_granted(FS_READ))
        self.assertTrue(caps.is_granted(FS_LIST))
        self.assertTrue(caps.is_denied(FS_WRITE))

    def test_shorthand_shape(self):
        caps = CapabilitySet.from_mapping({"read": ["data"]}, base="/tmp")
        self.assertTrue(caps.is_granted(FS_READ))

    def test_flat_shape(self):
        caps = CapabilitySet.from_mapping({"fs.read": ["data"]}, base="/tmp")
        self.assertTrue(caps.is_granted(FS_READ))

    def test_single_string_root(self):
        caps = CapabilitySet.from_mapping({"read": "data"}, base="/tmp")
        self.assertTrue(caps.is_granted(FS_READ))

    def test_unknown_key_is_refused(self):
        with self.assertRaises(CapabilityError) as ctx:
            CapabilitySet.from_mapping({"padinng": ["x"]}, base="/tmp")
        self.assertIn("unknown key", str(ctx.exception))

    def test_wrong_root_type_is_refused(self):
        with self.assertRaises(CapabilityError) as ctx:
            CapabilitySet.from_mapping({"read": 3}, base="/tmp")
        self.assertIn("must be a list", str(ctx.exception))

    def test_unknown_capability_name_is_refused(self):
        with self.assertRaises(CapabilityError):
            CapabilitySet.from_mapping({"fs": {"delete": ["x"]}}, base="/tmp")

    def test_missing_file(self):
        with self.assertRaises(CapabilityError) as ctx:
            CapabilitySet.from_file("/nonexistent/caps.toml")
        self.assertIn("no such capability file", str(ctx.exception))

    def test_invalid_toml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write("not toml [[[\n")
            path = handle.name
        try:
            with self.assertRaises(CapabilityError) as ctx:
                CapabilitySet.from_file(path)
            self.assertIn("not valid TOML", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_missing_capabilities_table(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write("[package]\nname = \"x\"\n")
            path = handle.name
        try:
            with self.assertRaises(CapabilityError) as ctx:
                CapabilitySet.from_file(path)
            self.assertIn("no [capabilities] table", str(ctx.exception))
        finally:
            os.unlink(path)


class TomlFallbackTests(unittest.TestCase):
    """The Python 3.9 reader must agree with tomllib on the documented shape."""

    TEXT = """
# a capability file
[capabilities]
deny = ["fs.write"]

[capabilities.fs]
read = ["data", "notes"]
write = ["out"]
list = ["data"]
"""

    def test_subset_reader_parses_the_documented_shape(self):
        from silica.capabilities import parse_toml_subset
        document = parse_toml_subset(self.TEXT)
        self.assertEqual(document["capabilities"]["fs"]["read"], ["data", "notes"])
        self.assertEqual(document["capabilities"]["deny"], ["fs.write"])

    def test_both_readers_agree(self):
        from silica.capabilities import load_toml
        ours = load_toml(self.TEXT.encode("utf-8"), "caps.toml")
        try:
            import tomllib
        except ModuleNotFoundError:
            self.skipTest("tomllib unavailable; only one reader exists")
        theirs = tomllib.loads(self.TEXT)
        self.assertEqual(ours, theirs)

    def test_subset_reader_handles_comments_inside_arrays(self):
        from silica.capabilities import parse_toml_subset
        document = parse_toml_subset('[capabilities]\nread = ["a", "b"]  # trailing\n')
        self.assertEqual(document["capabilities"]["read"], ["a", "b"])

    def test_subset_reader_rejects_a_bad_line(self):
        from silica.capabilities import parse_toml_subset
        with self.assertRaises(CapabilityError):
            parse_toml_subset("[capabilities]\nnonsense\n")

    def test_subset_reader_rejects_a_bad_value(self):
        from silica.capabilities import parse_toml_subset
        with self.assertRaises(CapabilityError):
            parse_toml_subset("[capabilities]\nread = data\n")

    def test_from_file_works_through_either_reader(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(self.TEXT)
            path = handle.name
        try:
            caps = CapabilitySet.from_file(path, base="/tmp")
            self.assertTrue(caps.is_granted(FS_READ))
            self.assertTrue(caps.is_denied(FS_WRITE))
        finally:
            os.unlink(path)


class StructuralTests(unittest.TestCase):
    """The guarantees that make the model hard to bypass."""

    def test_every_privileged_native_names_a_known_capability(self):
        for module, functions in MODULES.items():
            for name, native in functions.items():
                if native.requires is None:
                    continue
                with self.subTest(native="%s.%s" % (module, name)):
                    self.assertIn(native.requires, KNOWN)

    def test_the_speech_module_is_guarded_where_it_matters(self):
        guarded = {"speak": "speech.speak", "save": "speech.speak",
                   "transcribe": "speech.listen"}
        for name, kind in guarded.items():
            with self.subTest(native=name):
                self.assertEqual(MODULES["speech"][name].requires, kind)
        for name in ("voices", "languages", "status"):
            with self.subTest(native=name):
                self.assertIsNone(MODULES["speech"][name].requires)

    def test_every_fs_native_is_guarded(self):
        self.assertIn("fs", MODULES)
        for name, native in MODULES["fs"].items():
            with self.subTest(native=name):
                self.assertIsNotNone(native.requires,
                                     "fs.%s has no capability guard" % name)
                self.assertIsNotNone(native.path_arg,
                                     "fs.%s has no path argument" % name)

    def test_no_other_module_claims_a_capability(self):
        # only the modules that touch the machine may declare capabilities
        privileged = {"fs", "speech"}
        for module, functions in MODULES.items():
            if module in privileged:
                continue
            for name, native in functions.items():
                with self.subTest(native="%s.%s" % (module, name)):
                    self.assertIsNone(native.requires)

    def test_vm_denies_before_the_native_body_runs(self):
        """The guard is in dispatch: the native never gets to open a file."""
        called = []
        native = MODULES["fs"]["read_text"]
        original = native.fn

        def spy(ctx, args):  # pragma: no cover - must not be reached
            called.append(args)
            return original(ctx, args)

        native.fn = spy
        try:
            with self.assertRaises(CapabilityError):
                run('use fs\nsfn main() {\n sprint(fs.read_text("README.md"))\n}\n')
        finally:
            native.fn = original
        self.assertEqual(called, [])

    def test_vm_carries_the_set_it_was_given(self):
        from silica.engine import compile_source
        chunk = compile_source("sfn main() {\n}\n").chunk
        caps = CapabilitySet.empty().grant(FS_READ, "/tmp")
        vm = VM(chunk, capabilities=caps)
        self.assertIs(vm.capabilities, caps)

    def test_vm_defaults_to_no_capabilities(self):
        from silica.engine import compile_source
        chunk = compile_source("sfn main() {\n}\n").chunk
        self.assertTrue(VM(chunk).capabilities.is_empty())


class LocatedErrorTests(unittest.TestCase):
    def test_denial_reports_file_line_and_column(self):
        source = 'use fs\nsfn main() {\n    sprint(fs.read_text("x"))\n}\n'
        with self.assertRaises(CapabilityError) as ctx:
            run(source, filename="prog.sc")
        err = ctx.exception
        self.assertEqual(err.line, 3)
        self.assertEqual(err.filename, "prog.sc")
        self.assertIn("capability error", err.format())


class FlagParsingTests(unittest.TestCase):
    def test_allow_flags_accumulate(self):
        from silica.cli import _parse_capabilities
        caps, rest = _parse_capabilities(
            ["prog.sc", "--allow-fs-read", "a", "--allow-fs-read", "b",
             "--allow-fs-list", "a"])
        self.assertEqual(rest, ["prog.sc"])
        self.assertEqual(len(caps.roots(FS_READ)), 2)
        self.assertTrue(caps.is_granted(FS_LIST))

    def test_equals_form(self):
        from silica.cli import _parse_capabilities
        caps, rest = _parse_capabilities(["--allow-fs-write=/tmp/x", "prog.sc"])
        self.assertEqual(rest, ["prog.sc"])
        self.assertTrue(caps.is_granted(FS_WRITE))

    def test_deny_flag(self):
        from silica.cli import _parse_capabilities
        caps, _rest = _parse_capabilities(["--allow-fs-write", "/tmp", "--deny-fs-write"])
        self.assertFalse(caps.is_granted(FS_WRITE))

    def test_flag_without_value_is_an_error(self):
        from silica.cli import _parse_capabilities
        with self.assertRaises(CapabilityError):
            _parse_capabilities(["--allow-fs-read"])


if __name__ == "__main__":
    unittest.main()
