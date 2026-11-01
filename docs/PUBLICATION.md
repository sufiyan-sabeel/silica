# Publication runbook

Everything needed to publish Silica to PyPI and to propose it to Termux, with the
current state of each step. Nothing in this document has been executed beyond what
the table says.

## State, precisely

| | PyPI | Termux |
|---|---|---|
| Artefacts **built** | yes — wheel, sdist, `SHA256SUMS.txt` | recipe written, never built |
| **Tested** on this platform (Linux x86_64) | yes — install, run, interop, capabilities | not applicable |
| **Tested** on the target platform (Android ARM64) | not applicable | **no** — no device |
| **Submitted** | no | **no** — no pull request opened |
| **Accepted** by the registry | no | no |
| **Published** / installable by the public command | **no** | **no** |

`pip install silica-lang` and `pkg install silica-lang` both fail today. The rest of
this document is what makes the first one work, and what a Termux maintainer would
need to accept the second.

---

## 1. PyPI

### What is already in place

- `pyproject.toml`: distribution `silica-lang`, entry point
  `silica = "silica.cli:main"`, `requires-python = ">=3.9"`, no runtime
  dependencies, classifiers for 3.9–3.13.
- `.github/workflows/publish.yml`: builds, verifies with `tools/package/verify.sc`,
  and uploads through **trusted publishing (OIDC)**. No token is stored anywhere —
  not in the repository, not in a secret, not in the workflow file.
- The v0.10.0 artefacts published as GitHub Release assets verify against their
  published `SHA256SUMS.txt`.

### The trusted publisher configuration — exact values

Create the publisher at <https://pypi.org/manage/account/publishing/> (or under the
project's *Publishing* settings once it exists) with these fields:

| Field | Value |
|---|---|
| PyPI Project Name | `silica-lang` |
| Owner | `sufiyan-sabeel` |
| Repository name | `silica` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

For a rehearsal on TestPyPI, register the same values at
<https://test.pypi.org/manage/account/publishing/> with environment `testpypi`.

Then, in the GitHub repository settings → *Environments*, create two environments:
`pypi` and `testpypi`. Optionally require a reviewer on `pypi`, so a publication
needs a human click.

### Publishing

1. **Rehearse** (recommended): Actions → *Publish to PyPI* → *Run workflow* →
   `repository: testpypi`. Then check:
   ```bash
   python3 -m venv /tmp/rehearsal && /tmp/rehearsal/bin/pip install \
       --index-url https://test.pypi.org/simple/ --no-deps silica-lang
   /tmp/rehearsal/bin/silica --version
   ```
   TestPyPI was **not reachable** from the environment this was written in, so this
   step is untested here.
2. **Publish**: Actions → *Publish to PyPI* → *Run workflow* → `repository: pypi`,
   or publish a GitHub release (the workflow also triggers on `release: published`).
3. **Verify** the real thing:
   ```bash
   python3 -m venv /tmp/verify && /tmp/verify/bin/pip install silica-lang
   /tmp/verify/bin/silica --version                       # silica 0.10.0
   printf 'sfn main() {\n    sprint("hello")\n}\n' > /tmp/h.sc
   /tmp/verify/bin/silica run /tmp/h.sc
   /tmp/verify/bin/silica run --allow-interop-python - <<'SC'
   use python
   sfn main() {
       let m: Any = python.import("math")
       sprint(python.call(m, "sqrt", [9]))
       python.stop()
   }
   SC
   ```

### Notes that matter

- **Build from `main`, not from the tag.** The v0.10.0 tag predates `MANIFEST.in`,
  so an sdist built from the tag would lack the examples and docs. Running the
  workflow from `main` (or cutting a `v0.10.0.post1` / `v0.10.1`) is what ships a
  complete source distribution.
- **A published version cannot be replaced.** Uploading `0.10.0` twice is rejected.
  If something is wrong after publishing, yank it and publish a new patch version;
  do not try to overwrite.
- **Never commit credentials.** The workflow uses OIDC precisely so that there is
  nothing to leak.

---

## 2. Termux

### What is already in place

- `packaging/termux/silica-lang/build.sh`, audited against
  `packages/httpie/build.sh` — the closest existing analogue (a Python CLI). It
  uses `TERMUX_PKG_SETUP_PYTHON=true`, `TERMUX_PKG_BUILD_IN_SRC=true`,
  `cross-pip install --no-deps --prefix="$TERMUX_PREFIX" "$TERMUX_PKG_SRCDIR"`,
  `TERMUX_PKG_DEPENDS="python, python-pip"` and
  `TERMUX_PKG_PLATFORM_INDEPENDENT=true`.
- `packaging/termux/PR.md`: the complete pull-request description, including what
  was verified and what was not.

### Why `cross-pip` and not `pip`

Termux builds Python packages inside a crossenv prepared by
`TERMUX_PKG_SETUP_PYTHON=true`. Plain `pip` would install for the build host; the
earlier draft of this recipe made exactly that mistake and was corrected after
reading `scripts/build/setup/termux_setup_python_pip.sh`.

### Submitting

```bash
git clone https://github.com/termux/termux-packages
cd termux-packages
mkdir -p packages/silica-lang
cp /path/to/silica/packaging/termux/silica-lang/build.sh packages/silica-lang/
./build-package.sh silica-lang          # must succeed before opening a PR
git checkout -b add-silica-lang
git add packages/silica-lang
git commit -m "new package: silica-lang"
```

Open the pull request with the text from `packaging/termux/PR.md`. Reviewers will
build it themselves; the recipe must build cleanly in their CI.

### What must be true before claiming support

1. `./build-package.sh silica-lang` succeeds on a Termux host or in the
   maintainers' Docker image.
2. `pkg install ./output/silica-lang_*.deb` works on a device.
3. `silica --version` reports `0.10.0`.
4. `silica run` executes an example from `$PREFIX/share/silica-lang/examples/`.
5. `use python` starts its worker on the device.

Until 1–5 have happened, Android support is **unverified**, and no document in this
repository may say otherwise.

---

## 3. Integrity

Every published artefact can be checked without trusting the download:

```bash
curl -sSLO https://github.com/sufiyan-sabeel/silica/releases/download/v0.10.0/SHA256SUMS.txt
curl -sSLO https://github.com/sufiyan-sabeel/silica/releases/download/v0.10.0/silica_lang-0.10.0-py3-none-any.whl
sha256sum -c SHA256SUMS.txt        # silica_lang-0.10.0-py3-none-any.whl: OK
```

The same policy is enforced automatically: `tools/package/verify.sc` (Silica)
refuses a release whose checksums, contents or version strings disagree, and it
runs in CI, in the release workflow and in the publish workflow.
