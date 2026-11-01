"""The `path` module: path text only, and the containment rule it documents."""

import unittest

from .helpers import run


def program(body):
    return "use path\n\nsfn main() {\n" + body + "\n}\n"


def out(body):
    code, text = run(program(body))
    return text


class SplitTests(unittest.TestCase):
    def test_join_base_dir_ext_stem(self):
        self.assertEqual(out('sprint(path.join(["a", "b", "c.txt"]))'), "a/b/c.txt\n")
        self.assertEqual(out('sprint(path.base("a/b/c.txt"))'), "c.txt\n")
        self.assertEqual(out('sprint(path.dir("a/b/c.txt"))'), "a/b\n")
        self.assertEqual(out('sprint(path.ext("a/b/c.txt"))'), ".txt\n")
        self.assertEqual(out('sprint(path.stem("a/b/c.txt"))'), "c\n")

    def test_a_path_without_an_extension(self):
        self.assertEqual(out('sprint(path.ext("Makefile"))'), "\n")
        self.assertEqual(out('sprint(path.stem("Makefile"))'), "Makefile\n")

    def test_a_dotfile_is_not_an_extension(self):
        # ".bashrc" is a name, not an extension
        self.assertEqual(out('sprint(path.ext(".bashrc"))'), "\n")

    def test_split(self):
        self.assertEqual(out('sprint(path.split("a/b/c.txt"))'),
                         '["a/b", "c.txt"]\n')

    def test_join_of_an_empty_list(self):
        self.assertEqual(out('sprint(path.join([]))'), "\n")

    def test_with_suffix(self):
        self.assertEqual(out('sprint(path.with_suffix("a/b.txt", ".md"))'), "a/b.md\n")
        self.assertEqual(out('sprint(path.with_suffix("a/b.txt", "md"))'), "a/b.md\n")

    def test_sep_constant(self):
        self.assertEqual(out("sprint(len(path.sep))"), "1\n")


class NormaliseTests(unittest.TestCase):
    def test_dot_and_dotdot_collapse(self):
        self.assertEqual(out('sprint(path.normalise("data/./x/../y.txt"))'),
                         "data/y.txt\n")
        self.assertEqual(out('sprint(path.normalise("a//b"))'), "a/b\n")

    def test_normalise_is_lexical_not_filesystem(self):
        # the path does not exist, and that changes nothing
        self.assertEqual(out('sprint(path.normalise("/no/such/dir/../f"))'),
                         "/no/such/f\n")

    def test_is_absolute(self):
        self.assertEqual(out('sprint(path.is_absolute("/a/b"))'), "oui\n")
        self.assertEqual(out('sprint(path.is_absolute("a/b"))'), "nein\n")


class ContainmentTests(unittest.TestCase):
    """`is_within` is a lexical check; these are the cases that matter."""

    def test_a_path_below_the_root_is_inside(self):
        self.assertEqual(out('sprint(path.is_within("data/x/y.txt", "data"))'), "oui\n")

    def test_the_root_itself_is_inside(self):
        self.assertEqual(out('sprint(path.is_within("data", "data"))'), "oui\n")

    def test_a_parent_traversal_is_outside(self):
        self.assertEqual(out('sprint(path.is_within("data/../etc/passwd", "data"))'),
                         "nein\n")
        self.assertEqual(out(out and 'sprint(path.is_within("../etc/passwd", "data"))'),
                         "nein\n")

    def test_a_sibling_with_the_same_prefix_is_outside(self):
        # "datax" must not pass a naive startswith("data") check
        self.assertEqual(out('sprint(path.is_within("datax/y", "data"))'), "nein\n")

    def test_an_absolute_path_outside_the_root(self):
        self.assertEqual(out('sprint(path.is_within("/etc/passwd", "data"))'), "nein\n")

    def test_absolute_forms_compare_correctly(self):
        self.assertEqual(
            out('sprint(path.is_within("/srv/data/x", "/srv/data"))'), "oui\n")


class SafetyTests(unittest.TestCase):
    def test_a_nul_byte_is_refused(self):
        for body in ('sprint(path.base("a\\u0000b"))',
                     'sprint(path.join(["a\\u0000"]))',
                     'sprint(path.normalise("x\\u0000"))'):
            with self.subTest(body=body):
                with self.assertRaises(Exception) as ctx:
                    run(program(body))
                self.assertIn("NUL", str(ctx.exception))

    def test_a_non_string_argument_is_refused(self):
        # the checker catches it before the runtime does, which is the better error
        with self.assertRaises(Exception) as ctx:
            run(program("sprint(path.base(1))"))
        self.assertIn("must be String", str(ctx.exception))

    def test_join_needs_a_list(self):
        with self.assertRaises(Exception) as ctx:
            run(program('sprint(path.join("a/b"))'))
        self.assertIn("must be List", str(ctx.exception))

    def test_the_module_requires_no_capability(self):
        # no capability is granted here, and every call still works
        from silica.natives import MODULES
        for name, native in MODULES["path"].items():
            self.assertIsNone(native.requires, name)
