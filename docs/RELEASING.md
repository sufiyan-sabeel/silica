# Releasing Silica

How a version goes from `main` to something a stranger can install and verify.

## What a release consists of

| Artifact | Purpose |
|---|---|
| `silica_lang-<version>-py3-none-any.whl` | what `install.sh` installs |
| `silica_lang-<version>.tar.gz` | source distribution, for `pip install` and auditing |
| `SHA256SUMS.txt` | checksums for both, verified by the installer |

The git tag is `v<version>`. The version in `pyproject.toml` and the default in
`install.sh` must both match it; a test fails if they drift.

## Before tagging

Run all of this and keep the output — a release claim without recorded results is
a guess.

```bash
# 1. the full suite, including the installer tests (they build and install a
#    real wheel into throwaway homes; expect about a minute)
python3 -m unittest discover -s tests -t .

# 2. the Silica-level tests and the formatter check
python3 -m silica test tests
python3 -m silica fmt --check examples/*.sc tests/silica/*.sc benchmarks/silica/*.sc

# 3. build the artifacts
rm -rf dist
python3 -m build

# 4. install the built wheel into a clean environment and use it from elsewhere
python3 -m venv /tmp/silica-check
/tmp/silica-check/bin/pip install dist/silica_lang-*.whl
cd /tmp && /tmp/silica-check/bin/silica --version
printf 'sfn main() {\n    sprint("ok")\n}\n' > /tmp/ok.sc
/tmp/silica-check/bin/silica /tmp/ok.sc

# 5. checksums
cd dist && sha256sum *.whl *.tar.gz > SHA256SUMS.txt && cat SHA256SUMS.txt
```

## Bumping the version

Three places, all of which a test checks:

1. `pyproject.toml` — `[project] version`
2. `silica/__init__.py` — `__version__`
3. `install.sh` — the `SILICA_VERSION` default

`silica/cli.py` reads the version from `silica/__init__.py`, so the interpreter
banner and `silica --version` cannot disagree.

## Tagging and publishing

```bash
git tag -a v0.8.0 -m "Silica 0.8.0"
git push origin v0.8.0
```

Then create the release on GitHub and attach the three files from `dist/`. The
`Release` workflow (`.github/workflows/release.yml`) does this automatically on a
tag push: it runs the tests, builds, generates the checksums and uploads the
assets. Manual upload is the fallback if the workflow is unavailable.

A release is **not** published until the wheel, the sdist and `SHA256SUMS.txt` are
all attached. Publishing the tag also triggers `verify-release.yml`, which
downloads the public assets, verifies the checksums and installs them in a clean
environment — so a broken release fails a workflow rather than a user.

Silica is distributed through **GitHub Release assets only**. GitHub Packages has
no Python registry, so nothing is published there; see `docs/PACKAGING.md`. `install.sh` downloads the checksum file first and stops if it is
missing, so a half-populated release fails loudly rather than installing something
unverified.

## After publishing

Verify the public path, not just the local build:

```bash
curl -fsSL https://github.com/sufiyan-sabeel/silica/releases/download/v0.8.0/SHA256SUMS.txt
HOME=/tmp/fresh sh install.sh          # fresh HOME, real download
/tmp/fresh/.local/bin/silica --version
```

## Verifying a release you did not build

```bash
VERSION=0.8.0
BASE=https://github.com/sufiyan-sabeel/silica/releases/download/v$VERSION

curl -fsSLO "$BASE/silica_lang-$VERSION-py3-none-any.whl"
curl -fsSLO "$BASE/SHA256SUMS.txt"

# check the checksum line for the file you downloaded
grep "silica_lang-$VERSION-py3-none-any.whl" SHA256SUMS.txt
sha256sum -c <(grep "silica_lang-$VERSION-py3-none-any.whl" SHA256SUMS.txt)
```

`sha256sum -c` prints `OK` when the file matches. If it does not, do not install
it.

The checksum protects against a corrupt or swapped asset on the same release. It
does not protect against a compromised repository account, because the checksum
lives beside the artifact. For that, build from source at a tag you have verified
yourself.

## Tag history — a tag is a fixed pointer

A published tag is never moved: it names one commit for good. One consequence is
worth knowing before the next release:

| Tag | Points at | Note |
|---|---|---|
| `v0.8.0` | `88a90f346f` | cut **before** the README rewrite (`9e441fe453`) |

So the source archive of `v0.8.0` still contains the previous, longer README.
That tag is deliberately left where it is — moving it would silently change what
everyone who already downloaded 0.8.0 has. The corrected README ships in the next
release, **v0.9.2**, which is cut from a commit that contains it. Check before
publishing:

```bash
# the tag's README must be the current one, not the pre-0.8.0 text
git show v0.9.2:README.md | head -5
```

If a release archive turns out to carry a stale README, cut a new patch version.
Do not re-tag.

## Rolling back

Old releases are never deleted, so rollback is a version change, not a rebuild:

```bash
SILICA_VERSION=0.2.1 sh install.sh
```

`install.sh` upgrades in place, so this downgrades the existing virtual
environment cleanly.

## PyPI

Silica is **not** published on PyPI. Publishing would need the package name
checked for availability and explicit authorisation from the maintainer; neither
has happened. Until then, install from a release or from source, as
`docs/INSTALL.md` describes.
