# Packaging and distribution

How Silica is built, where it is published, and what is deliberately not done.

---

## The package

| | |
|---|---|
| Distribution name | **`silica-lang`** |
| Import name | `silica` |
| Version | `0.9.0` |
| Format | Python wheel (`py3-none-any`) and sdist (`tar.gz`) |
| Requires | Python **3.9+** |
| Runtime dependencies | **none** — pure standard library |
| Console script | `silica` → `silica.cli:main` |
| Licence | MIT |

Silica is a **Python package**, not npm, Cargo or Maven. That was verified from
`pyproject.toml` and the build backend (`setuptools.build_meta`), not assumed.

Development dependencies live under the `dev` extra and are never required to run
the language:

```toml
[project.optional-dependencies]
dev = ["pytest>=7", "pillow>=9", "build>=1", "wheel", "setuptools>=64", "numpy>=1.21"]
```

### What the wheel contains

`silica/`, `silica/gui/`, `silica/ide/`, `silica/tui/`, `silica/ui/`,
`silica/voice/`, plus two resource sets declared in `[tool.setuptools.package-data]`:

* `silica/ui/assets/*.png` — the renderer's logo assets
* `silica/ide/app.html` — the Script Mode editor page

The IDE page is a single self-contained HTML file with no build step, so it ships
as package data and is found relative to `silica/ide/`. The `verify-release`
workflow asserts it is present and non-truncated in the installed wheel, because a
missing `app.html` would break `silica ide` only at run time.

Excluded from the build: caches (`__pycache__`, `*.pyc`), `.pytest_cache`,
`*.egg-info`, `build/`, `dist/`, `.venv/`, and `.sbc` build output. These are in
`.gitignore` and are not part of the wheel.

---

## Where it is published — and why not GitHub Packages

**GitHub Packages does not support Python packages.** Its registries are npm,
RubyGems, Apache Maven, Gradle, NuGet and the container registry; there is no
PyPI-compatible registry. Publishing `silica-lang` there is not possible, so no
such publication is attempted or claimed.

What Silica uses instead, and what the installer consumes:

| Channel | What it is | URL |
|---|---|---|
| GitHub Release assets | the actual distribution | `releases/download/<tag>/silica_lang-<version>-py3-none-any.whl` |
| GitHub Release assets | source distribution | `releases/download/<tag>/silica_lang-<version>.tar.gz` |
| GitHub Release assets | checksums | `releases/download/<tag>/SHA256SUMS.txt` |

Release assets are **not** GitHub Packages and are not described as such. They are
versioned, immutable per tag, and downloadable without authentication.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
```

The installer downloads `SHA256SUMS.txt` **first** and refuses to proceed without
it, so a half-published release fails loudly instead of installing something
unverified.

### Upgrade and rollback

```bash
SILICA_VERSION=0.9.0 sh install.sh   # upgrade or pin to a version
SILICA_VERSION=0.8.0 sh install.sh   # roll back
sh uninstall.sh                      # remove only what the installer created
```

The installer is idempotent: re-running it replaces the environment in place and
leaves `~/.local/bin/silica` pointing at the new version.

### From the source tree

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # development
pip install dist/silica_lang-0.9.0-py3-none-any.whl   # a built artifact
```

### Verify an installation

```bash
silica --version
printf 'sfn main() {\n    sprint("ok")\n}\n' > /tmp/ok.sc
silica /tmp/ok.sc
```

---

## The release pipeline

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | push to `main`, pull request | tests on 3.9/3.11/3.12, Silica-level tests, formatter check |
| `release.yml` | tag `v*` | tests, version-vs-tag check, build, checksums, clean-venv smoke test, publish |
| `verify-release.yml` | release published | downloads the **public** assets, checks checksums, installs, runs a script |

`release.yml` refuses to publish if the tag, `silica/__init__.py` and the
`install.sh` default disagree — that check is what stops a release whose version
numbers have drifted.

`verify-release.yml` exists because release assets are the distribution here. It
tests them the way a stranger would: over HTTPS from the public URL, with the
published checksums, into a clean environment. A missing asset or a wrong checksum
fails the workflow rather than going unnoticed.

Both workflows declare least-privilege `permissions`: `contents: read` for CI and
verification, `contents: write` only for the job that creates the release. No
workflow prints a token, and no credential is stored in the repository.

---

## Dependabot

`.github/dependabot.yml` monitors the two ecosystems that actually exist:

| Ecosystem | Directory | Why |
|---|---|---|
| `github-actions` | `/` | the workflows use `actions/checkout`, `actions/setup-python`, `softprops/action-gh-release` |
| `pip` | `/` | `pyproject.toml` declares development dependencies |

Weekly, Monday 06:00 UTC, at most 5 open pull requests each, labelled
`dependencies`. Build tooling (`build`, `setuptools`, `wheel`) is grouped into one
pull request for minor and patch updates so review stays cheap; `pytest` is not
grouped because a major bump there can change test behaviour.

Silica has **no runtime dependencies**, so the `pip` entries can only ever propose
development-tool updates. Nothing about the language's behaviour depends on them.

Security updates are enabled in the repository's security settings, not in this
file. Dependabot alerts are a notification mechanism, not a guarantee: they only
cover ecosystems GitHub's dependency graph can read, and they do not review a
pull request for you.

### Reviewing a Dependabot pull request

1. Read what changed and why — a major version bump needs the upstream changelog.
2. Let CI run. The suite is 671 tests and covers the language, CLI, IDE, TUI, GUI
   and the installer.
3. For `github-actions`, check the action's release notes for permission or
   input changes; a new major version can rename inputs.
4. Merge only if CI is green. Never merge by skipping the failing job.

---

## Supply-chain notes

* No runtime dependencies means there is no third-party code in the language's
  execution path. That is the strongest security property this project has.
* Development dependencies are only installed in CI and in developer environments.
* Release assets are checksummed, and the installer verifies before installing.
* Workflows use least-privilege permissions and are triggered by tags and pushes
  to `main` only.
* Not done, and not claimed: SHA-pinned actions, signed releases, SBOM generation,
  or provenance attestation. Those are real improvements and none is in place.
