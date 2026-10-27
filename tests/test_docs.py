"""Documentation consistency tests.

Docs drift silently. These tests fail when the code grows something the
documentation does not mention, so the spec, the stdlib reference and the README
stay true.
"""

import os
import unittest

from silica import cli
from silica.natives import CONSTANTS, MODULES, PLANNED_MODULES
from silica.tokens import KEYWORDS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class DocumentationTests(unittest.TestCase):
    def test_expected_documents_exist(self):
        for name in ("LANGUAGE_SPEC.md", "GRAMMAR.md", "BYTECODE.md",
                     "STANDARD_LIBRARY.md", "PERFORMANCE.md", "BOOTSTRAP.md",
                     "ROADMAP.md"):
            self.assertTrue(os.path.exists(os.path.join(DOCS, name)), name)
        for name in ("README.md", "LICENSE", "CONTRIBUTING.md",
                     "CODE_OF_CONDUCT.md", "SECURITY.md", "CHANGELOG.md",
                     "pyproject.toml", "silica.toml"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, name)), name)

    def test_every_native_is_documented(self):
        text = read(os.path.join(DOCS, "STANDARD_LIBRARY.md"))
        for module, functions in MODULES.items():
            for name in functions:
                # core natives are called bare (sprint, len, ...); everything
                # else is qualified (math.abs, string.split, ...)
                needle = name if module == "core" else "%s.%s" % (module, name)
                with self.subTest(native="%s.%s" % (module, name)):
                    self.assertIn(needle, text)

    def test_every_module_constant_is_documented(self):
        text = read(os.path.join(DOCS, "STANDARD_LIBRARY.md"))
        for module, constants in CONSTANTS.items():
            for name in constants:
                with self.subTest(constant="%s.%s" % (module, name)):
                    self.assertIn("%s.%s" % (module, name), text)

    def test_planned_modules_are_declared(self):
        text = read(os.path.join(DOCS, "STANDARD_LIBRARY.md"))
        for module in PLANNED_MODULES:
            self.assertIn(module, text)

    def test_every_keyword_is_in_the_spec(self):
        text = read(os.path.join(DOCS, "LANGUAGE_SPEC.md"))
        for keyword in KEYWORDS:
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, text)

    def test_every_command_is_in_the_readme(self):
        text = read(os.path.join(ROOT, "README.md"))
        for command in cli.COMMANDS:
            self.assertIn("silica %s" % command, text)
        for command in cli.PLANNED:
            self.assertIn(command, text)

    def test_readme_states_the_real_version(self):
        from silica import __version__
        text = read(os.path.join(ROOT, "README.md"))
        self.assertIn(__version__, text)
        self.assertIn(__version__, cli.VERSION)

    def test_bytecode_doc_lists_every_opcode(self):
        from silica.bytecode import OPS
        text = read(os.path.join(DOCS, "BYTECODE.md"))
        for name, code in OPS.items():
            with self.subTest(opcode=name):
                self.assertIn(name, text)
                self.assertIn("0x%02X" % code, text)

    def test_spec_and_roadmap_agree_on_limitations(self):
        spec = read(os.path.join(DOCS, "LANGUAGE_SPEC.md"))
        roadmap = read(os.path.join(DOCS, "ROADMAP.md"))
        for phrase in ("generics", "self-host"):
            self.assertIn(phrase, spec.lower() + roadmap.lower())

    def test_performance_doc_reports_measurements_not_claims(self):
        text = read(os.path.join(DOCS, "PERFORMANCE.md")).lower()
        self.assertIn("slower", text)
        self.assertIn("measured", text)
        self.assertIn("slower than cpython", text)
        # any mention of being faster must be negated, never asserted
        for sentence in text.replace("\n", " ").split("."):
            if "faster than" in sentence:
                self.assertIn("not", sentence, sentence.strip())


if __name__ == "__main__":
    unittest.main()
