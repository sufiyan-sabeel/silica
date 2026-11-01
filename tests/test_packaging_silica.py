"""The Silica-written packaging check, exercised end to end.

Two kinds of test here:

* the real repository, built for real, must pass;
* a synthetic repository with one thing broken must fail with the *specific*
  message that names the breakage — because a checker that passes everything is
  worse than no checker.

The checker is `tools/package/verify.sc` (Silica). Only fact collection is Python
(`tools/package/facts.py`), because Silica has no zip/tar reader and no SHA-256.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY = os.path.join(ROOT, "tools", "package", "verify.sc")
SUMS = os.path.join(ROOT, "tools", "package", "sums.sc")

VERSION = "0.10.0"
WHEEL = "silica_lang-0.10.0-py3-none-any.whl"
SDIST = "silica_lang-0.10.0.tar.gz"


def run_silica(script, directory, flags=("--allow-fs-read", ".",
                                         "--allow-fs-write", ".")):
    """Run the real CLI from ROOT against a program in `directory`.

    The fixture creates a `silica/` package in the temporary directory, so
    `python -m silica` would import that instead of the engine. Importing the CLI
    with ROOT first on sys.path avoids the shadowing and keeps argv exact.
    """
    code = ("import sys; sys.path.insert(0, %r); "
            "from silica.cli import main; sys.exit(main(%r))"
            % (ROOT, ["run"] + list(flags) + [script]))
    completed = subprocess.run([sys.executable, "-c", code], cwd=directory,
                               capture_output=True, text=True, timeout=180,
                               env=dict(os.environ))
    return completed.returncode, completed.stdout, completed.stderr


def facts(version=VERSION, wheel_files=None, sdist_files=None,
          wheel_sha="a" * 64, sdist_sha="b" * 64):
    return {
        "distribution": "silica-lang",
        "version": version,
        "version_source": "test",
        "entry_point": "silica",
        "wheel": {"name": WHEEL, "sha256": wheel_sha,
                  "files": wheel_files if wheel_files is not None else [
                      "silica/cli.py", "silica/vm.py", "silica/checker.py",
                      "silica/compiler.py", "silica/parser.py",
                      "silica/bytecode.py", "silica/natives.py",
                      "silica/capabilities.py",
                      "silica/interop/worker_main.py",
                      "silica/interop/providers/python_worker.py",
                      "silica/stdlib_path.py", "silica/stdlib_time.py",
                      "silica/stdlib_random.py", "silica/ide/app.html",
                      "silica_lang-0.10.0.dist-info/METADATA",
                      "silica_lang-0.10.0.dist-info/entry_points.txt",
                  ]},
        "sdist": {"name": SDIST, "sha256": sdist_sha,
                  "files": sdist_files if sdist_files is not None else [
                      "examples/stdlib_tour.sc", "examples/data/sales.csv",
                      "docs/APPLICATIONS.md", "docs/SECURITY_MODEL.md",
                      "tests/test_interop.py", "install.sh", "uninstall.sh",
                      "MANIFEST.in",
                  ]},
        "required_wheel": [
            "silica/cli.py", "silica/vm.py", "silica/checker.py",
            "silica/compiler.py", "silica/parser.py", "silica/bytecode.py",
            "silica/natives.py", "silica/capabilities.py",
            "silica/interop/worker_main.py",
            "silica/interop/providers/python_worker.py",
            "silica/stdlib_path.py", "silica/stdlib_time.py",
            "silica/stdlib_random.py", "silica/ide/app.html"],
        "forbidden_wheel_prefixes": ["tests/", "examples/", "docs/",
                                     "benchmarks/", "editors/", "packaging/"],
        "required_sdist_suffixes": [
            "examples/stdlib_tour.sc", "examples/data/sales.csv",
            "docs/APPLICATIONS.md", "docs/SECURITY_MODEL.md",
            "tests/test_interop.py", "install.sh", "uninstall.sh",
            "MANIFEST.in"],
        "sums": {},
    }


class SyntheticRepo(object):
    """A minimal tree that satisfies every check, ready to be broken one way."""

    def __init__(self, root):
        self.root = root
        self.write("pyproject.toml",
                   '[project]\nname = "silica-lang"\nversion = "%s"\n'
                   '[project.scripts]\nsilica = "silica.cli:main"\n' % VERSION)
        self.write("silica/__init__.py", '__version__ = "%s"\n' % VERSION)
        self.write("silica/cli.py", 'VERSION = "%s"\n' % VERSION)
        self.write("install.sh", 'VERSION="${SILICA_VERSION:-%s}"\n' % VERSION)
        self.write("CHANGELOG.md", "## [%s] — 2026-11-01\n" % VERSION)
        self.write_facts(facts())
        self.write_sums("a" * 64, "b" * 64)

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def write_facts(self, data):
        self.write(os.path.join("build", "packaging", "facts.json"),
                   json.dumps(data, indent=2))

    def write_sums(self, wheel_sha, sdist_sha):
        self.write(os.path.join("dist", "SHA256SUMS.txt"),
                   "%s  %s\n%s  %s\n" % (wheel_sha, WHEEL, sdist_sha, SDIST))


class RealRepositoryTests(unittest.TestCase):
    def test_the_shipped_tree_passes_every_check(self):
        # Self-sufficient: it builds the artefacts into a temporary directory, so
        # it works in a clean clone where `dist/` does not exist yet.
        with tempfile.TemporaryDirectory() as tmp:
            dist = os.path.join(tmp, "dist")
            facts_path = os.path.join(tmp, "facts.json")
            build = subprocess.run(
                [sys.executable, "-m", "build", "--outdir", dist],
                cwd=ROOT, capture_output=True, text=True, timeout=600,
                env=dict(os.environ, PIP_USER="0"))
            self.assertEqual(build.returncode, 0, build.stderr[-800:])
            built = subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "package", "facts.py"),
                 "--repo", ROOT, "--dist-dir", dist, "--out", facts_path],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(built.returncode, 0, built.stderr)
            data = json.load(open(facts_path, encoding="utf-8"))

            repo = SyntheticRepo(tmp)          # version files, in the temp root
            for name in ("pyproject.toml", "install.sh", "CHANGELOG.md",
                         "silica/__init__.py", "silica/cli.py"):
                with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
                    repo.write(name, fh.read())
            repo.write_facts(data)

            code, out, err = run_silica(SUMS, tmp)
            self.assertEqual(code, 0, err)
            code, out, err = run_silica(VERIFY, tmp)
            self.assertEqual(code, 0, out + err)
            self.assertIn("all checks passed", out)
            report = json.load(open(os.path.join(tmp, "build", "packaging",
                                                 "report.json"), encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(report["version"], VERSION)
            self.assertEqual(report["problems"], [])


class PolicyTests(unittest.TestCase):
    """One breakage per test: the checker must name it."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="silica-pkg-")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.repo = SyntheticRepo(self.directory)

    def assert_fails(self, expected):
        code, out, err = run_silica(VERIFY, self.directory)
        self.assertEqual(code, 1, "expected failure, got: %s%s" % (out, err))
        self.assertIn(expected, out)

    def test_a_valid_synthetic_tree_passes_first(self):
        code, out, err = run_silica(VERIFY, self.directory)
        self.assertEqual(code, 0, out + err)

    def test_a_stale_installer_pin_is_caught(self):
        # exactly the regression this repository had at release time
        self.repo.write("install.sh", 'VERSION="${SILICA_VERSION:-0.9.3}"\n')
        self.assert_fails("version in the installer")

    def test_a_stale_changelog_is_caught(self):
        self.repo.write("CHANGELOG.md", "## [0.9.3] — 2026-10-31\n")
        self.assert_fails("version in the changelog")

    def test_a_stale_package_version_is_caught(self):
        self.repo.write("silica/__init__.py", '__version__ = "0.9.3"\n')
        self.assert_fails("version in the package")

    def test_a_wrong_distribution_name_is_caught(self):
        self.repo.write("pyproject.toml", '[project]\nname = "silica"\n'
                                          'version = "%s"\n'
                                          '[project.scripts]\n'
                                          'silica = "silica.cli:main"\n' % VERSION)
        self.assert_fails("distribution name")

    def test_a_missing_entry_point_is_caught(self):
        self.repo.write("pyproject.toml", '[project]\nname = "silica-lang"\n'
                                          'version = "%s"\n' % VERSION)
        self.assert_fails("entry point")

    def test_a_missing_worker_in_the_wheel_is_caught(self):
        data = facts(wheel_files=["silica/cli.py",
                                  "silica_lang-0.10.0.dist-info/METADATA",
                                  "silica_lang-0.10.0.dist-info/entry_points.txt"])
        self.repo.write_facts(data)
        self.assert_fails("wheel is missing silica/vm.py")

    def test_a_source_file_in_the_wheel_is_caught(self):
        data = facts()
        data["wheel"]["files"] = data["wheel"]["files"] + ["tests/test_cli.py"]
        self.repo.write_facts(data)
        self.assert_fails("source-only file tests/test_cli.py")

    def test_a_wheel_without_entry_points_is_caught(self):
        data = facts()
        data["wheel"]["files"] = [f for f in data["wheel"]["files"]
                                  if not f.endswith("entry_points.txt")]
        self.repo.write_facts(data)
        self.assert_fails("no silica command")

    def test_an_sdist_missing_the_examples_is_caught(self):
        data = facts(sdist_files=["install.sh", "uninstall.sh", "MANIFEST.in",
                                  "docs/APPLICATIONS.md", "docs/SECURITY_MODEL.md",
                                  "tests/test_interop.py",
                                  "examples/data/sales.csv"])
        self.repo.write_facts(data)
        self.assert_fails("sdist is missing examples/stdlib_tour.sc")

    def test_a_checksum_mismatch_is_caught(self):
        self.repo.write_sums("c" * 64, "b" * 64)      # wheel digest differs
        self.assert_fails("checksum mismatch for " + WHEEL)

    def test_a_sums_file_missing_an_artefact_is_caught(self):
        self.repo.write(os.path.join("dist", "SHA256SUMS.txt"),
                        "%s  %s\n" % ("a" * 64, WHEEL))
        self.assert_fails("SHA256SUMS.txt does not list " + SDIST)

    def test_a_missing_sums_file_is_caught(self):
        os.remove(os.path.join(self.directory, "dist", "SHA256SUMS.txt"))
        self.assert_fails("no SHA256SUMS.txt")

    def test_a_version_mismatch_between_artefacts_and_metadata_is_caught(self):
        data = facts(version="0.10.1")
        self.repo.write_facts(data)
        self.assert_fails("wheel name does not carry the version")

    def test_missing_facts_stop_the_check(self):
        os.remove(os.path.join(self.directory, "build", "packaging", "facts.json"))
        self.assert_fails("not found")


class BoundaryTests(unittest.TestCase):
    """What the Silica side is allowed to do."""

    def test_the_verifier_uses_only_stdlib_modules(self):
        with open(VERIFY, encoding="utf-8") as handle:
            source = handle.read()
        uses = {line.split()[1] for line in source.splitlines()
                if line.startswith("use ")}
        self.assertEqual(uses, {"fs", "json", "string"})

    def test_the_verifier_runs_no_process_and_no_network(self):
        with open(VERIFY, encoding="utf-8") as handle:
            source = handle.read().lower()
        for forbidden in ("subprocess", "popen", "exec(", "eval(", "socket",
                          "urllib", "http", "curl", "sh "):
            self.assertNotIn(forbidden, source, forbidden)

    def test_the_bridge_executes_only_a_fixed_build_command(self):
        with open(os.path.join(ROOT, "tools", "package", "facts.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        # the only subprocess use is the fixed build invocation
        self.assertEqual(source.count("subprocess.run"), 1)
        self.assertIn('"--build"', source)
        self.assertIn("[sys.executable, \"-m\", \"build\"]", source)
        for forbidden in ("shell=True", "os.system", "urllib", "requests",
                          "token", "password"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_the_verifier_needs_a_capability_to_read_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            SyntheticRepo(tmp)
            code, out, err = run_silica(VERIFY, tmp, flags=())
            self.assertEqual(code, 1)
            self.assertIn("capability", err.lower())


if __name__ == "__main__":
    unittest.main()


class RecipeTests(unittest.TestCase):
    """The Termux recipe must match the conventions it claims to follow."""

    RECIPE = os.path.join(ROOT, "packaging", "termux", "silica-lang", "build.sh")

    def source(self):
        with open(self.RECIPE, encoding="utf-8") as handle:
            return handle.read()

    def test_it_declares_the_python_package_variables(self):
        source = self.source()
        for required in ("TERMUX_PKG_SETUP_PYTHON=true",
                         "TERMUX_PKG_BUILD_IN_SRC=true",
                         "TERMUX_PKG_PLATFORM_INDEPENDENT=true",
                         'TERMUX_PKG_DEPENDS="python, python-pip"'):
            self.assertIn(required, source)

    def test_it_installs_with_cross_pip_not_plain_pip(self):
        # plain `pip` would install for the build host; Termux builds inside a
        # crossenv prepared by TERMUX_PKG_SETUP_PYTHON=true
        source = self.source()
        self.assertIn("cross-pip install", source)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("pip install") or " pip wheel" in stripped:
                self.fail("recipe uses plain pip: %s" % stripped)

    def test_it_pins_a_plausible_source_checksum(self):
        import re
        match = re.search(r"TERMUX_PKG_SHA256=([0-9a-f]{64})\b", self.source())
        self.assertIsNotNone(match, "no 64-hex SHA256 in the recipe")

    def test_it_keeps_everything_inside_the_prefix(self):
        source = self.source()
        self.assertIn('"$TERMUX_PREFIX"', source)
        for forbidden in ("/usr/local", "sudo", "/data/data/com.termux/files/usr/lib"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_the_launcher_is_made_executable(self):
        self.assertIn('chmod 755 "$TERMUX_PREFIX/bin/silica"', self.source())


class DocumentationHonestyTests(unittest.TestCase):
    """No document may claim an installation command works before it does."""

    DOCUMENTS = ["README.md", "docs/PACKAGING.md", "docs/PUBLICATION.md",
                 "packaging/termux/README.md", "packaging/termux/PR.md"]

    #: wording that marks the command as not working; matched case-insensitively
    QUALIFIERS = ("fail", "not available", "unavailable", "does not work",
                  "not submitted", "not in the termux", "not published",
                  "not yet")

    def test_the_termux_command_is_never_presented_as_working(self):
        for name in self.DOCUMENTS:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            if "pkg install silica-lang" not in text:
                continue
            lowered = text.lower()
            self.assertTrue(
                any(q.lower() in lowered for q in self.QUALIFIERS),
                "%s mentions 'pkg install silica-lang' without saying it is "
                "unavailable" % name)

    def test_the_pip_command_is_marked_unpublished(self):
        with open(os.path.join(ROOT, "docs", "PUBLICATION.md"),
                  encoding="utf-8") as handle:
            text = handle.read().lower()
        self.assertIn("pip install silica-lang", text)
        self.assertTrue(
            any(q in text for q in ("fail", "not published", "unpublished")),
            "PUBLICATION.md must say the pip command does not work yet")
        # and the state table must not mark it published
        self.assertIn("| **published**", text)

    def test_android_support_is_described_as_unverified(self):
        with open(os.path.join(ROOT, "packaging", "termux", "PR.md"),
                  encoding="utf-8") as handle:
            text = handle.read().lower()
        self.assertIn("not", text)
        self.assertIn("device", text)
        self.assertNotIn("works on termux", text)
        self.assertNotIn("android support is verified", text)
