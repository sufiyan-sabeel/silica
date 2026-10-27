"""Installer, packaging and distribution tests.

These run the real `install.sh` and `uninstall.sh` against a throwaway HOME and a
wheel built from this checkout, so what is tested is the shipped script, not a
description of it. No network access is needed: the release URL is overridden
with a local `file://` directory, which exercises the same download-and-verify
code path.

What these cannot test is a real Termux device. The Termux branch is covered by
setting the environment variables Termux sets (`TERMUX_VERSION`, `PREFIX`) and
checking that the launcher lands in `$PREFIX/bin`, but the Android filesystem and
`pkg` are not exercised. `docs/INSTALL.md` says so.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install.sh")
UNINSTALL = os.path.join(ROOT, "uninstall.sh")

HAVE_SH = shutil.which("sh") is not None


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def pyproject_text():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
        return handle.read()


def project_version():
    """Read the version without a TOML parser: tomllib is 3.11+, and the 3.9
    fallback in capabilities.py only understands the [capabilities] shape, not
    inline tables like `license = { text = "MIT" }`."""
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"', pyproject_text(), re.M)
    if match is None:
        raise AssertionError("pyproject.toml has no version line")
    return match.group(1)


def run(cmd, env=None, cwd=None, input_text=None):
    return subprocess.run(
        cmd, cwd=cwd, env=env, input=input_text,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)


@unittest.skipUnless(HAVE_SH, "no POSIX shell available")
class ScriptTests(unittest.TestCase):
    def test_both_scripts_are_valid_posix_shell(self):
        for path in (INSTALL, UNINSTALL):
            with self.subTest(script=os.path.basename(path)):
                result = run(["sh", "-n", path])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_scripts_are_executable_in_the_checkout(self):
        for path in (INSTALL, UNINSTALL):
            with self.subTest(script=os.path.basename(path)):
                self.assertTrue(os.access(path, os.X_OK),
                                "%s is not executable" % path)

    def test_installer_defaults_to_the_project_version(self):
        """A stale default would download a release that does not exist."""
        match = re.search(r'VERSION="\$\{SILICA_VERSION:-([0-9]+\.[0-9]+\.[0-9]+)\}"',
                          read(INSTALL))
        self.assertIsNotNone(match, "install.sh has no SILICA_VERSION default")
        self.assertEqual(match.group(1), project_version())

    def test_installer_never_executes_sudo_unless_asked(self):
        """Advice like "sudo apt install python3" is fine; running sudo is not."""
        offenders = []
        for number, line in enumerate(read(INSTALL).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # a command position: start of line, or after && ; or a pipe
            for segment in re.split(r"&&|\|\||;|\|", stripped):
                if re.match(r"^\s*sudo\b", segment):
                    offenders.append((number, stripped))
        self.assertEqual(offenders, [],
                         "install.sh runs sudo outside the SILICA_SYSTEM branch")

    def test_installer_pins_https_for_the_default_release_url(self):
        self.assertIn("--proto '=https'", read(INSTALL))

    def test_uninstaller_only_deletes_marked_launchers(self):
        self.assertIn("silica-managed-launcher", read(UNINSTALL))
        self.assertIn("refusing to delete", read(UNINSTALL))


@unittest.skipUnless(HAVE_SH, "no POSIX shell available")
class EndToEndTests(unittest.TestCase):
    """Build a wheel once, then install it into throwaway HOMEs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="silica-install-")
        cls.dist = os.path.join(cls.tmp, "dist")
        os.makedirs(cls.dist)
        build = run([sys.executable, "-m", "build", "--wheel", "--no-isolation",
                     "--outdir", cls.dist], cwd=ROOT)
        if build.returncode != 0:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            # fail rather than skip: a silent skip would hide a broken installer
            raise RuntimeError(
                "could not build a wheel; is the 'build' package installed "
                "(pip install .[dev])?\n%s" % build.stderr[-800:])
        wheels = [n for n in os.listdir(cls.dist) if n.endswith(".whl")]
        if not wheels:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise RuntimeError("build produced no wheel")
        cls.wheel = os.path.join(cls.dist, wheels[0])

        # a local "release": the wheel plus its checksum file
        cls.release = os.path.join(cls.tmp, "release")
        os.makedirs(cls.release)
        shutil.copy(cls.wheel, cls.release)
        import hashlib
        with open(cls.wheel, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        with open(os.path.join(cls.release, "SHA256SUMS.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (digest, os.path.basename(cls.wheel)))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def shared_home(cls):
        """One install reused by every read-only assertion, to keep the suite fast."""
        if getattr(cls, "_shared", None) is None:
            home = tempfile.mkdtemp(prefix="home-shared-", dir=cls.tmp)
            result = run(["sh", INSTALL], env=cls.base_env(home), cwd=home)
            cls._shared = (home, result)
        return cls._shared

    @classmethod
    def base_env(cls, home, **extra):
        # inherit PATH rather than hardcoding it: on GitHub runners the
        # interpreter lives in a toolcache directory, and replacing PATH would
        # make the installer's Python check fail for the wrong reason.
        env = {
            "HOME": home,
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "SILICA_ARTIFACT": cls.wheel,
            "SILICA_YES": "1",
            "PIP_CACHE_DIR": os.path.join(cls.tmp, "pip-cache"),
        }
        env.update(extra)
        return env

    def home(self):
        path = tempfile.mkdtemp(prefix="home-", dir=self.tmp)
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def env(self, home, **extra):
        return self.base_env(home, **extra)

    def install(self, home, **extra):
        return run(["sh", INSTALL], env=self.env(home, **extra), cwd=home)

    # -- the happy path -------------------------------------------------------
    def test_install_places_a_working_launcher(self):
        home, result = self.shared_home()
        self.assertEqual(result.returncode, 0, result.stderr)
        launcher = os.path.join(home, ".local", "bin", "silica")
        self.assertTrue(os.path.exists(launcher), result.stdout)
        self.assertIn("Silica %s installed" % project_version(), result.stdout)

    def test_the_installed_command_works_outside_the_repository(self):
        home, _ = self.shared_home()
        launcher = os.path.join(home, ".local", "bin", "silica")
        elsewhere = tempfile.mkdtemp(prefix="cwd-", dir=self.tmp)

        version = run([launcher, "--version"], env=self.env(home), cwd=elsewhere)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "silica %s" % project_version())

        script = os.path.join(elsewhere, "hello.sc")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write('sfn main() {\n    sprint("outside the repo")\n}\n')
        ran = run([launcher, script], env=self.env(home), cwd=elsewhere)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(ran.stdout, "outside the repo\n")

    def test_the_interpreter_starts_from_the_installed_command(self):
        home, _ = self.shared_home()
        launcher = os.path.join(home, ".local", "bin", "silica")
        session = run([launcher], env=self.env(home), input_text="1 + 1\nexit\n")
        self.assertEqual(session.returncode, 0, session.stderr)
        self.assertIn("Silica Interpreter v%s" % project_version(), session.stdout)
        self.assertIn("\u00a2 2", session.stdout)

    def test_installer_is_idempotent(self):
        home = self.home()
        first = self.install(home)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.install(home)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("reusing", second.stdout)
        launcher = os.path.join(home, ".local", "bin", "silica")
        self.assertEqual(run([launcher, "--version"], env=self.env(home)).returncode, 0)

    def test_path_warning_is_printed_when_bin_dir_is_not_on_path(self):
        _home, result = self.shared_home()
        self.assertEqual(result.returncode, 0)
        self.assertIn("is not on your PATH", result.stderr)
        self.assertIn("export PATH=", result.stdout)

    # -- Termux branch --------------------------------------------------------
    def test_termux_environment_puts_the_launcher_in_prefix_bin(self):
        home = self.home()
        prefix = tempfile.mkdtemp(prefix="prefix-", dir=self.tmp)
        result = self.install(home, TERMUX_VERSION="0.118", PREFIX=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("platform    : termux", result.stdout)
        self.assertTrue(os.path.exists(os.path.join(prefix, "bin", "silica")),
                        result.stdout)

    # -- verification ---------------------------------------------------------
    def test_a_verified_download_installs(self):
        home = self.home()
        env_extra = {"SILICA_ARTIFACT": "", "SILICA_BASE_URL": "file://" + self.release}
        result = self.install(home, **env_extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checksum    : verified", result.stdout)

    def test_a_tampered_artifact_is_refused(self):
        home = self.home()
        bad = os.path.join(self.tmp, "bad-release")
        shutil.rmtree(bad, ignore_errors=True)
        shutil.copytree(self.release, bad)
        with open(os.path.join(bad, os.path.basename(self.wheel)), "ab") as handle:
            handle.write(b"tampered")
        result = self.install(home, SILICA_ARTIFACT="",
                              SILICA_BASE_URL="file://" + bad)
        self.assertEqual(result.returncode, 1)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(home, ".local", "bin", "silica")),
                         "a tampered artifact must not install")

    def test_a_missing_artifact_path_is_a_clear_error(self):
        home = self.home()
        result = self.install(home, SILICA_ARTIFACT=os.path.join(self.tmp, "nope.whl"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("SILICA_ARTIFACT is not a file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    # -- uninstall ------------------------------------------------------------
    def test_uninstall_removes_only_what_it_created(self):
        home = self.home()
        self.assertEqual(self.install(home).returncode, 0)
        bin_dir = os.path.join(home, ".local", "bin")
        launcher = os.path.join(bin_dir, "silica")
        venv = os.path.join(home, ".local", "share", "silica", "venv")
        keeper = os.path.join(bin_dir, "something-else")
        with open(keeper, "w", encoding="utf-8") as handle:
            handle.write("not silica\n")

        result = run(["sh", UNINSTALL], env=self.env(home), cwd=home)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.subTest(check="launcher removed"):
            self.assertFalse(os.path.exists(launcher))
        with self.subTest(check="venv removed"):
            self.assertFalse(os.path.exists(venv))
        with self.subTest(check="unrelated file kept"):
            self.assertTrue(os.path.exists(keeper),
                            "uninstall deleted a file it did not create")

    def test_uninstall_refuses_a_launcher_it_did_not_create(self):
        home = self.home()
        self.assertEqual(self.install(home).returncode, 0)
        launcher = os.path.join(home, ".local", "bin", "silica")
        with open(launcher, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\necho someone else's silica\n")

        result = run(["sh", UNINSTALL], env=self.env(home), cwd=home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(launcher),
                        "uninstall removed a launcher it did not create")
        self.assertIn("not created by install.sh", result.stdout)

    def test_uninstall_without_a_manifest_is_a_no_op(self):
        home = self.home()
        result = run(["sh", UNINSTALL], env=self.env(home), cwd=home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("does not look installed", result.stdout)


class PackagingTests(unittest.TestCase):
    """The wheel must be installable and complete on its own."""

    def test_console_entry_point_is_declared(self):
        self.assertIn('silica = "silica.cli:main"', pyproject_text())

    def test_requires_python_matches_the_installer_check(self):
        self.assertIn('requires-python = ">=3.9"', pyproject_text())
        self.assertIn("(3, 9)", read(INSTALL))

    def test_package_data_covers_the_renderer_icon(self):
        text = pyproject_text()
        self.assertIn('"silica.ui" = ["assets/*.png"]', text)
        self.assertTrue(os.path.exists(
            os.path.join(ROOT, "silica", "ui", "assets", "silica-32.png")))

    def test_every_subpackage_is_declared_for_packaging(self):
        """A subpackage missing from `packages` builds a wheel that cannot import."""
        import re as _re
        declared = set(_re.findall(r'"(silica(?:\.[a-z_]+)*)"',
                                   _re.search(r"^packages = \[(.*?)\]",
                                              pyproject_text(), _re.M | _re.S).group(0)))
        root = os.path.join(ROOT, "silica")
        found = {"silica"}
        for entry in sorted(os.listdir(root)):
            if os.path.isdir(os.path.join(root, entry)) and os.path.exists(
                    os.path.join(root, entry, "__init__.py")):
                found.add("silica." + entry)
        self.assertEqual(found - declared, set(),
                         "these subpackages are missing from pyproject `packages`")

    def test_documentation_the_installer_points_at_exists(self):
        for name in ("INSTALL.md", "RELEASING.md"):
            with self.subTest(doc=name):
                self.assertTrue(os.path.exists(os.path.join(ROOT, "docs", name)))


if __name__ == "__main__":
    unittest.main()
