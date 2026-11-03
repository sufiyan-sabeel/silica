"""The parity contract: exact observable behaviour two VMs must agree on.

`docs/design/SILICA_PLATFORM_ARCHITECTURE.md` §16.3 names the places where a
second implementation (the planned Rust VM) silently diverges from the Python
reference VM: integer overflow, division and modulo signs, Unicode indexing,
float formatting, special floats, and map ordering.

This test is the executable form of that contract. Every case in `tests/parity/`
is a Silica program plus one expected artefact:

    <name>.sc        the program
    <name>.expected  exact stdout, byte for byte
    <name>.stderr    exact diagnostic, when the program is supposed to fail

A case whose first line starts with `# xfail:` is a **known defect in the Python
VM**, recorded rather than enforced. If such a case starts passing, this test
fails on purpose: the defect was fixed, and the marker must be removed.

Expectations were produced by running the reference VM, so this file cannot drift
from the implementation it describes without a test failing.
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARITY = os.path.join(HERE, "parity")

XFAIL = "# xfail:"


def cases():
    if not os.path.isdir(PARITY):
        return []
    return sorted(
        name[:-3] for name in os.listdir(PARITY) if name.endswith(".sc")
    )


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def execute(name):
    """Run one case exactly as a user would, and return (stdout, stderr or None).

    A subprocess rather than an in-process call: the CLI renders parse errors with
    a `file:line:col:` prefix that the exception object does not carry, and the
    contract is about what a user sees. It is also the interface the Rust VM will
    be compared through.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + (os.pathsep + env["PYTHONPATH"]
                                if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [sys.executable, "-m", "silica", "run", name + ".sc"],
        cwd=PARITY, capture_output=True, text=True, env=env, timeout=120,
    )
    return proc.stdout, (proc.stderr or None)


class ParityContractTests(unittest.TestCase):
    def test_the_corpus_is_not_empty(self):
        self.assertGreaterEqual(len(cases()), 10)

    def test_every_case_has_an_expectation(self):
        for name in cases():
            has_stdout = os.path.exists(os.path.join(PARITY, name + ".expected"))
            has_stderr = os.path.exists(os.path.join(PARITY, name + ".stderr"))
            self.assertTrue(has_stdout or has_stderr,
                            "%s has no .expected or .stderr file" % name)

    def test_the_contract_holds(self):
        for name in cases():
            with self.subTest(case=name):
                source = read(os.path.join(PARITY, name + ".sc"))
                expected_failure = source.lstrip().startswith(XFAIL)
                stdout, error = execute(name)

                expected_stdout_path = os.path.join(PARITY, name + ".expected")
                expected_stderr_path = os.path.join(PARITY, name + ".stderr")

                if os.path.exists(expected_stderr_path):
                    expected_error = read(expected_stderr_path).rstrip("\n")
                    matches = error is not None and error.rstrip("\n") == expected_error
                else:
                    expected_stdout = read(expected_stdout_path)
                    matches = error is None and stdout == expected_stdout

                if expected_failure:
                    self.assertFalse(
                        matches,
                        "%s is marked as a known defect but now matches its "
                        "expectation — remove the '# xfail:' line and keep the "
                        "case enforced" % name,
                    )
                else:
                    if os.path.exists(expected_stderr_path):
                        self.assertEqual(
                            (error or "").rstrip("\n"),
                            read(expected_stderr_path).rstrip("\n"),
                            "%s: diagnostic differs" % name,
                        )
                    else:
                        self.assertIsNone(error, "%s: unexpected error: %s" % (name, error))
                        self.assertEqual(
                            stdout, read(expected_stdout_path),
                            "%s: stdout differs" % name,
                        )


if __name__ == "__main__":
    unittest.main()
