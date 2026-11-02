"""The LLD-first rule, enforced.

"No application code before the LLD" is only a rule if something checks it. These
tests make it checkable:

* every application has `docs/design/<name>-LLD.md`;
* each LLD carries all eleven required sections;
* every example that reaches for a capability (a real application, not a syntax
  demo) is listed in the design index;
* the LLD's security section agrees with what the code actually imports.

Adding an application without a design fails CI here, which is the point.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(ROOT, "docs", "design")
INDEX = os.path.join(DESIGN, "README.md")
EXAMPLES = os.path.join(ROOT, "examples")

REQUIRED_SECTIONS = [
    "overview and scope",
    "architecture and component breakdown",
    "module and file structure",
    "data models and data flow",
    "function signatures and responsibilities",
    "ui/ux structure",
    "error handling and validation",
    "security and capability requirements",
    "dependencies and external integrations",
    "testing strategy and acceptance criteria",
    "implementation phases",
]

#: modules that require a capability grant, i.e. what makes a program an application
CAPABILITY_MODULES = ("fs",)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def index_entries():
    """(example basename, lld filename) pairs from the design index table."""
    text = read(INDEX)
    entries = []
    for line in text.splitlines():
        match = re.match(r"\|\s*`examples/([^`]+)\.sc`\s*\|\s*\[([^\]]+)\]", line)
        if match:
            entries.append((match.group(1), match.group(2)))
    return entries


def headings(text):
    return [line.lstrip("#").strip().lower() for line in text.splitlines()
            if line.startswith("#")]


class DesignIndexTests(unittest.TestCase):
    def test_the_rule_document_exists_and_states_the_rule(self):
        text = read(INDEX).lower()
        self.assertIn("no application code before the lld", text)

    def test_the_index_lists_the_applications(self):
        entries = index_entries()
        self.assertGreaterEqual(len(entries), 3)
        names = {name for name, _lld in entries}
        for expected in ("calculator_app", "task_manager", "data_report"):
            self.assertIn(expected, names)

    def test_every_indexed_design_file_exists(self):
        for name, lld in index_entries():
            path = os.path.join(DESIGN, lld)
            self.assertTrue(os.path.exists(path), "missing design for %s: %s" % (name, lld))


class DesignContentTests(unittest.TestCase):
    def test_every_design_has_all_required_sections(self):
        for name, lld in index_entries():
            text = read(os.path.join(DESIGN, lld))
            found = headings(text)
            for section in REQUIRED_SECTIONS:
                self.assertTrue(
                    any(section in heading for heading in found),
                    "%s is missing the '%s' section" % (lld, section))

    def test_every_design_is_substantial(self):
        # a real engineering document, not an outline written after the code
        for _name, lld in index_entries():
            text = read(os.path.join(DESIGN, lld))
            self.assertGreater(len(text.splitlines()), 60,
                               "%s is too thin to be an LLD" % lld)

    def test_every_design_names_its_capabilities(self):
        for _name, lld in index_entries():
            text = read(os.path.join(DESIGN, lld)).lower()
            self.assertIn("capabilit", text,
                          "%s does not state its capability requirements" % lld)


class DesignMatchesCodeTests(unittest.TestCase):
    """The design and the program must not drift apart."""

    def test_the_declared_capabilities_match_the_imports(self):
        for name, lld in index_entries():
            source = read(os.path.join(EXAMPLES, name + ".sc"))
            design = read(os.path.join(DESIGN, lld)).lower()
            uses_fs = any(re.search(r"^use %s\b" % mod, source, re.M)
                          for mod in CAPABILITY_MODULES)
            if uses_fs:
                self.assertIn("fs.read", design,
                              "%s imports fs but its design claims no capability" % name)
            else:
                self.assertIn("none", design,
                              "%s needs no capability but its design does not say so" % name)

    def test_every_capability_using_example_has_a_design(self):
        # an example that touches the filesystem is an application, not a syntax demo
        indexed = {name for name, _lld in index_entries()}
        for filename in sorted(os.listdir(EXAMPLES)):
            if not filename.endswith(".sc"):
                continue
            source = read(os.path.join(EXAMPLES, filename))
            uses_fs = any(re.search(r"^use %s\b" % mod, source, re.M)
                          for mod in CAPABILITY_MODULES)
            if uses_fs and filename != "fs_demo.sc":   # fs_demo is a syntax demo
                self.assertIn(filename[:-3], indexed,
                              "%s uses a capability but has no LLD in docs/design"
                              % filename)

    def test_every_design_records_its_implementation_status(self):
        for _name, lld in index_entries():
            text = read(os.path.join(DESIGN, lld)).lower()
            self.assertIn("status:", text)


if __name__ == "__main__":
    unittest.main()
