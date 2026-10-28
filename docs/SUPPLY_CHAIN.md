# Supply-chain security: what is in place, and a plan for the rest

This is a plan, not a claim. Nothing in the "planned" sections exists today, and
none of it should be described as active until it has been implemented and
tested.

---

## What is in place today

| Control | Status | Evidence |
|---|---|---|
| No runtime dependencies | **active** | `pyproject.toml` has no `dependencies`; the language, CLI, stdlib, TUI and IDE are pure standard library |
| Least-privilege workflow permissions | **active** | `permissions: contents: read` in `ci.yml` and `verify-release.yml`; `contents: write` only in the release job |
| Checksummed release assets | **active** | `SHA256SUMS.txt` published beside every release; `install.sh` verifies before installing |
| Assets verified after publication | **active** | `verify-release.yml` downloads from the public URL and runs `sha256sum --check` |
| Packaging validated on every push | **active** | the `package` job in `ci.yml` builds, inspects the archives and installs into a clean venv |
| No credentials in the repository | **active** | secrets scan over the tree is clean; no token is written to a file or logged |
| Dependabot version updates | **active** | `.github/dependabot.yml`, `github-actions` and `pip`, weekly |
| Dependabot **alerts** | **NOT enabled** | the API returns `403 Dependabot alerts are disabled for this repository` |
| Dependabot **security updates** | **NOT enabled** | requires alerts first; see below |
| SHA-pinned actions | **not implemented** | workflows use floating major tags (`@v4`, `@v5`, `@v2`) |
| Signed releases | **not implemented** | no signature on tags, commits or assets |
| SBOM | **not implemented** | no SBOM is produced or attached |
| Provenance attestation | **not implemented** | no attestation is generated |

The strongest property here is the first row: there is no third-party code in the
path that executes Silica programs. Everything else is defence in depth around a
distribution channel.

---

## Enabling Dependabot alerts and security updates

These are repository settings, not file contents, so they cannot be set from this
repository's code and were **not** changed.

1. Open <https://github.com/sufiyan-sabeel/silica/settings/security_analysis>
2. Under **Dependabot**, enable **Dependabot alerts**.
3. In the same section, enable **Dependabot security updates**.

**The distinction matters:**

* **Alerts** tell you a dependency you declared has a known advisory. They are
  notifications.
* **Security updates** open a pull request that bumps the affected dependency.
  They only work once alerts are on.
* **Version updates** — what `.github/dependabot.yml` configures — are scheduled
  bumps to newer releases, unrelated to advisories.

Dependabot alerts cover only ecosystems GitHub's dependency graph can read. They
do not review a pull request, do not catch a malicious package, and do not
protect against a compromised release asset.

---

## Plan, in priority order

Each item states the trust model, what it costs to maintain, and how to verify it.

### 1. Pin GitHub Actions to full commit SHAs

**Why first.** A floating tag like `@v4` is mutable: whoever controls the action
repository can move it, and the next run executes new code with this repository's
token. Pinning to a 40-character SHA makes the executed code immutable.

**Trust model.** You trust the specific commit you pinned, once, at the moment you
pinned it. Updates become an explicit, reviewable diff rather than an invisible
one.

**How.** Replace `uses: actions/checkout@v4` with
`uses: actions/checkout@<40-char-sha> # v4.2.2`, keeping the version in a comment.
Dependabot's `github-actions` ecosystem already understands this format and will
open pull requests that update the SHA and the comment together.

**Maintenance.** Near zero once Dependabot is doing it, but every PR must be read:
a SHA bump is a code change you are approving.

**Verify.** `grep -rn "uses: " .github/workflows/ | grep -v "@[0-9a-f]\{40\}"` must
print nothing.

### 2. Generate an SBOM for each release

**Why.** An SBOM records exactly what went into the artifact, so a consumer can
answer "am I affected?" without trusting a blog post.

**Trust model.** It is a *claim* produced by the build. It is only as trustworthy
as the build environment, which is why it belongs with item 3.

**How.** In `release.yml`, after the build:
`python -m pip install cyclonedx-bom && cyclonedx-py environment -o dist/sbom.json`
(or `syft dist/ -o cyclonedx-json`), then add `dist/sbom.json` to the release
`files:` list.

**Maintenance.** Low — one step, one more asset. It must be regenerated per
release or it becomes misleading.

**Verify.** `python -c "import json;d=json.load(open('dist/sbom.json'));print(len(d['components']))"`
and confirm the wheel's own name and version appear.

Note the honest caveat: Silica has **no runtime dependencies**, so its SBOM will
be nearly empty. That is the correct answer, not a broken tool.

### 3. Provenance attestation

**Why.** Proves the artifact was produced by this repository's workflow at this
commit, rather than uploaded by hand.

**Trust model.** Shifts trust from "the maintainer's laptop" to "GitHub's build
platform, as recorded in a transparency log". It does not prove the code is safe,
only where it came from.

**How.** Requires `permissions: id-token: write` and `attestations: write` on the
release job, then
`uses: actions/attest-build-provenance@v2` with `subject-path: dist/*.whl`.
Verification is `gh attestation verify dist/silica_lang-*.whl --repo sufiyan-sabeel/silica`.

**Maintenance.** Low, but it only works on GitHub-hosted runners, and adding
`id-token: write` widens the job's permissions — which must be justified in
review.

**Verify.** The `gh attestation verify` command above, run by a consumer.

### 4. Signed releases

**Why.** Lets a consumer verify the artifact even if GitHub itself is not trusted.

**Trust model.** Depends entirely on key custody. If the private key lives in a
CI secret, the guarantee collapses to "trust GitHub", which item 3 already gives
more cheaply. A hardware-backed key held offline is stronger but is a real
operational burden for one maintainer.

**How (if adopted).** Sign the tag (`git tag -s`), or sign the checksum file with
a dedicated key and publish the public key in the repository.

**Maintenance.** High: key rotation, revocation, a documented verification path,
and a recovery plan for a lost key. This is why it is last.

**Verify.** `gpg --verify SHA256SUMS.txt.asc SHA256SUMS.txt`.

### Not on this list, deliberately

Container image publishing, reproducible-build attestation, and a private
vulnerability-reporting process are all worth having eventually, but none is
urgent for a project with no runtime dependencies and one maintainer.

---

## What to do if a release asset is wrong

The assets of a published release are immutable in practice: people have
downloaded them and the checksums are public. Do not replace them silently.

1. Publish a new patch version with the fix.
2. Leave the old release in place, and edit **only its notes** to point at the
   replacement.
3. Never move a tag. A moved tag invalidates every checksum that references it.
