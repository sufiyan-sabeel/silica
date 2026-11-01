# Packaging and distribution

How Silica is built, where it is published, and what is deliberately not done.

---

## The package

| | |
|---|---|
| Distribution name | **`silica-lang`** |
| Import name | `silica` |
| Version | `0.9.3` |
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
`build/`, `dist/`, `.venv/`, and `.sbc` build output. These are in `.gitignore`
and appear in neither archive.

One nuance worth stating: the **sdist contains `silica_lang.egg-info/`**, because
setuptools generates it as part of building an sdist. That is standard, not a
leftover — the repository tree contains no `egg-info` directory. The `package`
job in `ci.yml` therefore rejects `egg-info` inside the **wheel** only, and
rejects caches in both.

The `package` job also builds and installs the wheel on every push, so packaging
breakage is caught on a normal commit instead of at tag time.

---

## The packaging check is written in Silica

`tools/package/` implements the packaging policy in `.sc` source:

| Step | Language | File |
|---|---|---|
| build, list archive members, hash artefacts | Python | `facts.py` |
| write `dist/SHA256SUMS.txt` | **Silica** | `sums.sc` |
| verify metadata, manifests, checksums | **Silica** | `verify.sc` |

Silica cannot read a zip or a tar, has no SHA-256 (its `crypto` module is still
planned) and cannot start a process, so those four operations are delegated to one
small Python file that decides nothing. Every rule about what a valid release looks
like — version consistency across five files, the wheel containing the interop
worker, no source files leaking into the wheel, the sdist carrying the examples,
checksums matching — is Silica code.

It runs in CI, in the release workflow and in the publish workflow, so a package
cannot be published without passing it. `tools/package/README.md` documents the
split and the exact commands.

## Distribution channels and their status

Three ways to get Silica, and exactly what is true about each one today.

| Channel | Command | Status |
|---|---|---|
| GitHub Release assets | download the wheel from the release page | **verified** — checksum matches `SHA256SUMS.txt`, installs and runs |
| PyPI | `pip install silica-lang` | **not published** — workflow ready, name still unregistered |
| Termux | `pkg install silica-lang` | **not published** — recipe ready in `packaging/termux/`, not in `termux-packages` |

### PyPI

`.github/workflows/publish.yml` builds the wheel and sdist, checks that the wheel
carries every runtime module and no source-only files, and uploads through
**trusted publishing** (OIDC). No API token exists in this repository, in a
secret, or in any workflow file — that is the point of trusted publishing.

The full runbook — exact trusted-publisher fields, publish steps, post-publication
verification and rollback policy — is [`PUBLICATION.md`](PUBLICATION.md). In short,
the owner must, once:

1. Register the trusted publisher at
   `https://pypi.org/manage/account/publishing/` with owner `sufiyan-sabeel`,
   repository `silica`, workflow `publish.yml`, environment `pypi`.
2. Create the `pypi` (and, for rehearsal, `testpypi`) environment in the
   repository settings.
3. Run the workflow by hand against `testpypi` first, then publish the release.

`test.pypi.org` was **not reachable** from the environment this was developed in,
so the rehearsal step is documented rather than performed. The name `silica-lang`
returned `404` from `https://pypi.org/pypi/silica-lang/json`, which is how a
free name answers; it was free at the time of writing and nothing here reserves
it.

### Termux

`packaging/termux/silica-lang/build.sh` follows the `termux-packages`
conventions: the v0.10.0 tag tarball pinned by SHA-256, `python` as the only
dependency, `TERMUX_PKG_PLATFORM_INDEPENDENT=true` (the engine is pure Python, so
aarch64 and arm share one package), installation entirely inside `$PREFIX`, and
the launcher forced to mode 755.

The recipe was audited against `packages/httpie/build.sh` and corrected: Termux
builds Python packages inside a crossenv, so it uses `cross-pip` and
`TERMUX_PKG_SETUP_PYTHON=true`, not plain `pip`. A ready-to-submit pull request
description is in `packaging/termux/PR.md`.

**Nothing has been built or run on Android.** No Termux/ARM64 device was
available. `packaging/termux/README.md` says so, lists the exact commands to try
on a device, and lists what to verify before proposing it upstream. Passing the
test suite on Linux x86_64 says nothing about Android.

### What a wheel and an sdist carry

| | wheel | sdist |
|---|---|---|
| Engine, CLI, standard library, interop worker | yes | yes |
| IDE `app.html`, UI assets | yes | yes |
| Examples, docs, tests, benchmarks, installers | no | **yes** |
| Size | 71 files | 117 source files |

The wheel stays lean because those files belong to the source tree; the sdist
carries them because a source distribution of a language should let you read and
run the language. `MANIFEST.in` enforces both.

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
SILICA_VERSION=0.9.3 sh install.sh   # upgrade or pin to a version
SILICA_VERSION=0.8.0 sh install.sh   # roll back
sh uninstall.sh                      # remove only what the installer created
```

The installer is idempotent: re-running it replaces the environment in place and
leaves `~/.local/bin/silica` pointing at the new version.

### From the source tree

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # development
pip install dist/silica_lang-0.9.3-py3-none-any.whl   # a built artifact
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
| `verify-release.yml` | Release workflow completes, or manual dispatch | downloads the **public** assets, checks checksums, installs, runs a script |

`release.yml` refuses to publish if the tag, `silica/__init__.py` and the
`install.sh` default disagree — that check is what stops a release whose version
numbers have drifted.

`verify-release.yml` exists because release assets are the distribution here. It
tests them the way a stranger would: over HTTPS from the public URL, with the
published checksums, into a clean environment. A missing asset or a wrong checksum
fails the workflow rather than going unnoticed.

It chains on the **Release workflow completing**, not on `release: [published]`.
A release created with `GITHUB_TOKEN` does not trigger other workflows, so a
`release` event trigger would silently never fire. It also has `workflow_dispatch`
for verifying an older tag by hand.

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
  or provenance attestation. Those are real improvements and none is in place;
  `docs/SUPPLY_CHAIN.md` plans them in priority order.
* Dependabot **alerts and security updates are disabled** on this repository — the
  API returns `403 Dependabot alerts are disabled for this repository`. Enabling
  them is a settings change in the GitHub UI, documented in
  `docs/SUPPLY_CHAIN.md`.
