"""The `fs` module, exercised through the VM with real capability grants.

Every test builds its own temporary directory and grants exactly the capability
it needs, so a test that accidentally works without a grant would fail.
"""

import os
import shutil
import tempfile
import unittest

from silica.capabilities import FS_LIST, FS_READ, FS_WRITE, CapabilitySet
from silica.engine import compile_source, run_chunk
from silica.errors import CapabilityError, SilicaRuntimeError

from .helpers import run

import io


class FsTestCase(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.data = os.path.join(self.root, "data")
        os.makedirs(self.data)
        self.note = os.path.join(self.data, "note.txt")
        with open(self.note, "w", encoding="utf-8") as handle:
            handle.write("hello")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def caps(self, *kinds):
        caps = CapabilitySet.empty(base=self.root)
        for kind in kinds:
            caps = caps.grant(kind, self.root)
        return caps

    def run_prog(self, body, caps=None):
        source = "use fs\nsfn main() {\n" + body + "\n}\n"
        chunk = compile_source(source, "<fs-test>").chunk
        out = io.StringIO()
        code = run_chunk(chunk, "<fs-test>", stdin=io.StringIO(""), stdout=out,
                         stderr=io.StringIO(), capabilities=caps)
        return code, out.getvalue()


class ReadTests(FsTestCase):
    def test_read_text(self):
        code, text = self.run_prog('sprint(fs.read_text("data/note.txt"))',
                                   self.caps(FS_READ))
        self.assertEqual(code, 0)
        self.assertEqual(text, "hello\n")

    def test_exists_true_and_false(self):
        code, text = self.run_prog(
            'sprint(fs.exists("data/note.txt"))\nsprint(fs.exists("data/nope.txt"))',
            self.caps(FS_READ))
        self.assertEqual(text, "oui\nnein\n")

    def test_missing_file_is_a_located_error(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            self.run_prog('sprint(fs.read_text("data/nope.txt"))', self.caps(FS_READ))
        self.assertIn("no such file", str(ctx.exception))
        self.assertTrue(ctx.exception.line)

    def test_directory_instead_of_file(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            self.run_prog('sprint(fs.read_text("data"))', self.caps(FS_READ))
        self.assertIn("is a directory", str(ctx.exception))

    def test_invalid_utf8(self):
        path = os.path.join(self.data, "bin.dat")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe\x00binary")
        with self.assertRaises(SilicaRuntimeError) as ctx:
            self.run_prog('sprint(fs.read_text("data/bin.dat"))', self.caps(FS_READ))
        self.assertIn("not valid UTF-8", str(ctx.exception))

    def test_utf8_text_round_trips(self):
        path = os.path.join(self.data, "unicode.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("café — naïve")
        _code, text = self.run_prog('sprint(fs.read_text("data/unicode.txt"))',
                                    self.caps(FS_READ))
        self.assertEqual(text, "café — naïve\n")


class WriteTests(FsTestCase):
    def test_write_then_read(self):
        code, _text = self.run_prog(
            'fs.write_text("data/out.txt", "written")', self.caps(FS_WRITE))
        self.assertEqual(code, 0)
        with open(os.path.join(self.data, "out.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "written")

    def test_write_overwrites(self):
        self.run_prog('fs.write_text("data/note.txt", "replaced")', self.caps(FS_WRITE))
        with open(self.note, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "replaced")

    def test_missing_parent_directory_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            self.run_prog('fs.write_text("data/nested/deep/out.txt", "x")',
                          self.caps(FS_WRITE))
        self.assertIn("directory does not exist", str(ctx.exception))

    def test_write_does_not_imply_read(self):
        with self.assertRaises(CapabilityError):
            self.run_prog('sprint(fs.read_text("data/note.txt"))', self.caps(FS_WRITE))


class ListTests(FsTestCase):
    def test_list_dir_is_sorted(self):
        for name in ("b.txt", "a.txt", "c.txt"):
            open(os.path.join(self.data, name), "w").close()
        _code, text = self.run_prog('sprint(fs.list_dir("data"))', self.caps(FS_LIST))
        self.assertEqual(text, '["a.txt", "b.txt", "c.txt", "note.txt"]\n')

    def test_list_file_is_an_error(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            self.run_prog('sprint(fs.list_dir("data/note.txt"))', self.caps(FS_LIST))
        self.assertIn("is a file", str(ctx.exception))

    def test_list_missing_directory(self):
        with self.assertRaises(SilicaRuntimeError) as ctx:
            self.run_prog('sprint(fs.list_dir("nope"))', self.caps(FS_LIST))
        self.assertIn("no such directory", str(ctx.exception))


class DenialTests(FsTestCase):
    def test_no_capabilities_denies_read(self):
        with self.assertRaises(CapabilityError) as ctx:
            self.run_prog('sprint(fs.read_text("data/note.txt"))')
        self.assertIn("fs.read", str(ctx.exception))

    def test_no_capabilities_denies_write(self):
        with self.assertRaises(CapabilityError):
            self.run_prog('fs.write_text("data/x.txt", "x")')

    def test_no_capabilities_denies_list(self):
        with self.assertRaises(CapabilityError):
            self.run_prog('sprint(fs.list_dir("data"))')

    def test_no_capabilities_denies_exists(self):
        with self.assertRaises(CapabilityError):
            self.run_prog('sprint(fs.exists("data/note.txt"))')

    def test_denied_capability_wins_over_grant(self):
        caps = self.caps(FS_READ).deny(FS_READ)
        with self.assertRaises(CapabilityError) as ctx:
            self.run_prog('sprint(fs.read_text("data/note.txt"))', caps)
        self.assertIn("denied", str(ctx.exception))

    def test_traversal_outside_root(self):
        outside = os.path.join(self.root, "..", "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("secret")
        try:
            caps = CapabilitySet.empty(base=self.data).grant(FS_READ, self.data)
            with self.assertRaises(CapabilityError):
                self.run_prog('sprint(fs.read_text("../outside.txt"))', caps)
        finally:
            os.unlink(outside)

    def test_absolute_path_outside_root(self):
        caps = self.caps(FS_READ)
        with self.assertRaises(CapabilityError):
            self.run_prog('sprint(fs.read_text("/etc/hostname"))', caps)


class ArityTests(FsTestCase):
    def test_wrong_arity_is_a_type_error(self):
        from silica.errors import SilicaTypeError
        source = 'use fs\nsfn main() {\n sprint(fs.read_text())\n}\n'
        with self.assertRaises(SilicaTypeError):
            compile_source(source, "<fs-test>")

    def test_non_string_path_is_a_type_error(self):
        from silica.errors import SilicaTypeError
        source = 'use fs\nsfn main() {\n sprint(fs.read_text(42))\n}\n'
        with self.assertRaises(SilicaTypeError):
            compile_source(source, "<fs-test>")


class SandboxDefaultTests(unittest.TestCase):
    def test_a_program_cannot_escape_without_flags(self):
        """The default `silica run` path grants nothing at all."""
        with self.assertRaises(CapabilityError) as ctx:
            run('use fs\nsfn main() {\n sprint(fs.exists("."))\n}\n')
        self.assertIn("fs.read", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
