"""The parity contract: exact observable behaviour two VMs must agree on.

`docs/design/SILICA_PLATFORM_ARCHITECTURE.md` §16.3 names the places where a
second implementation (the planned Rust VM) silently diverges from the Python
reference VM: integer overflow, division and remainder signs, Unicode indexing,
float formatting, special floats and map ordering.

This test is the executable form of that contract. Every case in `tests/parity/`
is a Silica program plus its expected artefacts:

    <name>.sc        the program
    <name>.expected  exact stdout, byte for byte          (success cases)
    <name>.stderr    exact diagnostic, hints included     (error cases)
    <name>.exit      optional exit code override

What is compared: **stdout, stderr (including `hint:` lines) and the exit code**,
through a subprocess — the same interface a user has and the same one the Rust VM
will be compared through. An in-process call would not do: the CLI renders parse
errors with a `file:line:col:` prefix that the exception object does not carry.

A case whose first line starts `# xfail(strict):` records a **known defect in the
Python VM**. Its expectation holds the *correct* behaviour, so it fails today; the
test passes by design, and it fails loudly (as an XPASS) once the defect is fixed,
until the marker is removed. `RunnerSelfTests` proves that strictness rather than
asserting it.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARITY = os.path.join(HERE, "parity")

STRICT_XFAIL = "# xfail(strict):"


def cases(directory=PARITY):
    if not os.path.isdir(directory):
        return []
    return sorted(name[:-3] for name in os.listdir(directory)
                  if name.endswith(".sc"))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def expected_exit(directory, name):
    """The exit code this case must produce.

    An error case (one with a `.stderr` expectation) must fail; a success case
    must exit 0. A `.exit` file overrides this when a case is neither.
    """
    override = os.path.join(directory, name + ".exit")
    if os.path.exists(override):
        return int(read(override).strip())
    return 1 if os.path.exists(os.path.join(directory, name + ".stderr")) else 0


def execute(directory, name):
    """Run one case as a user would. Returns (stdout, stderr, exit code)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + (os.pathsep + env["PYTHONPATH"]
                                if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [sys.executable, "-m", "silica", "run", name + ".sc"],
        cwd=directory, capture_output=True, text=True, env=env, timeout=120,
    )
    return proc.stdout, proc.stderr, proc.returncode


def compare(directory, name):
    """Return a list of problems for one case; empty means it matches."""
    source = read(os.path.join(directory, name + ".sc"))
    strict = source.lstrip().startswith(STRICT_XFAIL)
    stdout, stderr, code = execute(directory, name)

    problems = []

    wanted_code = expected_exit(directory, name)
    if code != wanted_code:
        problems.append("exit code %d, expected %d" % (code, wanted_code))

    stderr_path = os.path.join(directory, name + ".stderr")
    stdout_path = os.path.join(directory, name + ".expected")

    if os.path.exists(stderr_path):
        wanted = read(stderr_path).rstrip("\n")
        if stderr.rstrip("\n") != wanted:
            problems.append("diagnostic differs:\n--- expected\n%s\n--- actual\n%s"
                            % (wanted, stderr.rstrip("\n")))
    elif os.path.exists(stdout_path):
        wanted = read(stdout_path)
        if stdout != wanted:
            problems.append("stdout differs:\n--- expected\n%r\n--- actual\n%r"
                            % (wanted, stdout))
    else:
        problems.append("no .expected or .stderr file")

    if strict:
        # A strict-xfail case is supposed to disagree with its expectation today.
        # Matching it means the defect is fixed, and that must fail the run.
        if not problems:
            return ["XPASS: marked '# xfail(strict):' but now matches its "
                    "expectation — the defect is fixed, so remove the marker and "
                    "keep the case enforced"]
        return []
    return problems


def compare_all(directory=PARITY):
    return {name: compare(directory, name) for name in cases(directory)}


class ParityContractTests(unittest.TestCase):
    def test_the_corpus_is_not_empty(self):
        self.assertGreaterEqual(len(cases()), 10)

    def test_every_case_has_an_expectation(self):
        for name in cases():
            self.assertTrue(
                os.path.exists(os.path.join(PARITY, name + ".expected"))
                or os.path.exists(os.path.join(PARITY, name + ".stderr")),
                "%s has no .expected or .stderr file" % name)

    def test_the_contract_holds(self):
        for name, problems in compare_all().items():
            with self.subTest(case=name):
                self.assertEqual(problems, [], "%s: %s" % (name, problems))

    def test_error_cases_exit_nonzero_and_success_cases_exit_zero(self):
        """The exit-code rule, stated explicitly rather than implied."""
        for name in cases():
            with self.subTest(case=name):
                _stdout, _stderr, code = execute(PARITY, name)
                self.assertEqual(code, expected_exit(PARITY, name))

    def test_the_corpus_exercises_diagnostic_hints(self):
        """Hints are part of the contract, so the corpus must contain some."""
        with_hints = [
            name for name in cases()
            if os.path.exists(os.path.join(PARITY, name + ".stderr"))
            and "hint:" in read(os.path.join(PARITY, name + ".stderr"))
        ]
        self.assertGreaterEqual(len(with_hints), 3,
                                "too few cases exercise a hint: %r" % with_hints)


class RunnerSelfTests(unittest.TestCase):
    """The runner must actually detect a mismatch, or it proves nothing.

    Each test copies the corpus, corrupts exactly one expectation, and asserts the
    runner reports it. This is what makes the other tests meaningful.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.corpus = os.path.join(self.tmp, "parity")
        shutil.copytree(PARITY, self.corpus)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_detects_a_wrong_stdout(self):
        name = "int_overflow_add"
        path = os.path.join(self.corpus, name + ".expected")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("0\n0\n")
        self.assertTrue(compare(self.corpus, name))

    def test_it_detects_a_wrong_diagnostic(self):
        name = "map_missing_key"
        path = os.path.join(self.corpus, name + ".stderr")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("%s.sc:1: runtime error: something else\n" % name)
        self.assertTrue(compare(self.corpus, name))

    def test_it_detects_a_missing_hint(self):
        name = "map_missing_key"
        path = os.path.join(self.corpus, name + ".stderr")
        text = read(path).splitlines()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(line for line in text
                                   if not line.strip().startswith("hint:")))
        self.assertTrue(compare(self.corpus, name),
                        "dropping the hint line must be detected")

    def test_it_detects_a_wrong_exit_code(self):
        name = "map_missing_key"          # an error case, so 1 is expected
        with open(os.path.join(self.corpus, name + ".exit"), "w") as handle:
            handle.write("0\n")
        problems = compare(self.corpus, name)
        self.assertTrue(any("exit code" in p for p in problems), problems)

    def test_it_reports_an_xpass(self):
        name = "float_negative_zero_intern"
        # Make the expectation match what the VM produces today: the case is then
        # an XPASS and the runner must say so.
        _stdout, _stderr, _code = execute(self.corpus, name)
        path = os.path.join(self.corpus, name + ".expected")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("-0.0\n-0.0\n")
        problems = compare(self.corpus, name)
        self.assertTrue(any("XPASS" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
