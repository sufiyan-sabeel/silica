# Release integrity audit — do the GitHub v0.10.0 assets match a build of `main`?

Performed before any PyPI publication, because the same version number must not
mean two different sets of bytes on two registries.

**Current `main` at the time of the audit:** `8b497af15e63781083671654900ad98337cc9027`

**Verdict: they do not match.** Publishing `0.10.0` from `main` would put
different bytes on PyPI than the ones attached to the GitHub release of the same
version. The recommendation is at the end.

## 1. Hashes

| Artefact | GitHub v0.10.0 asset | Rebuilt from `main` | Same? |
|---|---|---|---|
| wheel | `cf08d36187b819f68ff8690a6ffd8ee4a216f3e190322e10e200e398767e546c` | `82d1472dfcdb853ffc1c319f13ed0b772b7477b2a1f1cbdba6819e78237ee632` | **no** |
| sdist | `dcd7845a14003889ace504d93fc8020aa0faf45be7b3421290f77fca6237fc1e` | `24e2a4a138b72214de9a9e087c57cc47aae9382c3ddccb45bb65a1029b8a55d4` | **no** |

The published assets still verify against their published `SHA256SUMS.txt` — they
are intact, not corrupted. They simply differ from a fresh build.

## 2. What actually differs

### The wheel: same code, different metadata

Both wheels contain **71 files with identical contents** except two:

| File | Why it differs |
|---|---|
| `silica_lang-0.10.0.dist-info/METADATA` | `pyproject.toml` gained classifiers (3.9–3.13, console, OS independent) and `Documentation`/`Changelog` URLs **after** the tag was cut |
| `silica_lang-0.10.0.dist-info/RECORD` | it hashes `METADATA`, so it changed with it |

No `.py` file, no `app.html`, no asset differs. The wheel is functionally the same
package.

### The sdist: 88 more files

| | published | rebuilt |
|---|---|---|
| files | 118 | 206 |

88 files are new: `MANIFEST.in` (added after the tag) pulls in the examples, docs,
tests, benchmarks, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md` and the
installers. Five files changed content, all metadata or prose:
`PKG-INFO`, `README.md`, `pyproject.toml`, `silica_lang.egg-info/PKG-INFO`,
`silica_lang.egg-info/SOURCES.txt`.

Again, no source file differs.

## 2b. The 206-versus-207-file sdist question, answered

An earlier note in this audit said the sdist had 206 files locally and 207 in CI,
which suggested the build was environment-dependent. It was not. Investigating it
properly produced one non-finding and one real defect.

### The count difference was two different commits

| Build | Commit | Files |
|---|---|---|
| local | `8b497af` | 206 |
| CI | `3acace0` | 207 |
| local, rebuilt from `3acace0` | `3acace0` | **207** |

Building `3acace0` locally produces **the same 207 files as CI, byte for byte in
every member**. The one added file is `docs/RELEASE_INTEGRITY.md`, which this audit
itself added between those two commits. The comparison had been mixing commits;
there is no environment difference.

### The real defect: untracked files leak into the sdist

`setuptools` builds the sdist from the **working tree**, not from git, so any
untracked file that matches a `MANIFEST.in` pattern is packaged. Verified by
dropping two scratch files into a clean clone:

```bash
echo probe > examples/untracked_probe.sc
echo probe > docs/untracked_probe.md
python3 -m build          # both files land in the sdist
```

The sdist then reported **209 files**, including both probes. A release built from a
developer's tree could ship scratch files, notes or secrets that were never
committed. That is the environment dependence worth fixing.

### The fix

The packaging check now refuses an sdist that carries a file git does not track:

- `tools/package/facts.py` records `tracked` from `git ls-files` — one read-only
  call, no shell, no network. When there is no repository (an unpacked sdist), it
  reports `null` instead of guessing.
- `tools/package/verify.sc` (Silica) fails with
  `sdist carries an untracked file: <path>` for any sdist member that is neither
  tracked nor a known generated file (`PKG-INFO`, `setup.cfg`, `pyproject.toml`,
  anything under `*.egg-info/`). More than ten are summarised rather than listed.
- With no git index the check prints `untracked-file detection is skipped` and does
  not fail, so an unpacked sdist can still be verified.

Six tests cover it: a clean tree passes, one untracked file and one untracked doc
are caught, generated metadata is allowed, a missing git index skips rather than
fails, and more than ten untracked files are summarised.

### What this does not change

No project file was removed. `MANIFEST.in` still includes the examples, docs,
tests, benchmarks and installers — those are all tracked, and they belong in a
source distribution.

## 3. Why even a rebuild of the *tag* does not reproduce the published bytes

Built from tag `v0.10.0` (`2153329`) — the exact commit the release was cut from:

| | published | rebuilt from the tag |
|---|---|---|
| wheel | `cf08d361…` | `59552f03…` |
| sdist | `dcd7845a…` | `45f1f758…` |

**Every one of the 71 wheel files and 118 sdist files is byte-identical** — zero
content differences. The archives differ only in their **member timestamps**
(`2026-11-01 13:18:50` published, `14:38:38` rebuilt), which changes the archive
hash.

So this project is **content-reproducible but not byte-reproducible** as it stands.

## 4. Reproducibility with `SOURCE_DATE_EPOCH`

Two builds of the same commit with `SOURCE_DATE_EPOCH=1793537939`:

| Artefact | Identical? |
|---|---|
| wheel | **yes** — `cfcee61bb93ac747…` both times |
| sdist | no — 8 files (`PKG-INFO`, `setup.cfg`, `silica_lang.egg-info/*`) carry build-time mtimes |

The wheel becomes byte-reproducible. The sdist is only content-reproducible,
because setuptools stamps those generated metadata files with the build time and
ignores `SOURCE_DATE_EPOCH` for them.

## 5. Recommendation

**Do not publish `0.10.0` to PyPI from `main`. Publish a new patch version
(`0.10.1`) built from the commit that ships.**

Why not reuse `0.10.0`:

- PyPI would hold an sdist with 88 more files and a wheel with different metadata
  than the GitHub assets of the same version. Two registries, one version number,
  two different artefacts — the exact silent divergence this audit exists to
  prevent.
- Publishing `0.10.0` *from the tag* would keep the content identical to the
  GitHub assets, but it would ship the sdist **without** the examples and docs and
  the wheel without the current metadata, and the byte hashes would still differ
  because of timestamps. It buys nothing.

The operational rule that makes identity unambiguous:

1. **Build once, publish the same bytes everywhere.** One CI job builds the wheel
   and sdist, attaches those files to the GitHub release, and uploads *those same
   files* to PyPI. Never rebuild for the second destination.
2. **Set `SOURCE_DATE_EPOCH`** from the commit timestamp in the build workflow, so
   the wheel is byte-reproducible and a rebuild can be proven identical.
3. **Publish a new version** whenever the artefacts change. `0.10.1` carries the
   packaging improvements; `v0.10.0` assets stay exactly as they are.
4. **Do not overwrite, replace or re-upload** the existing `v0.10.0` assets. They
   are intact and verified; leaving them alone preserves every historical
   checksum.

## 6. State after this audit

- `v0.10.0` GitHub assets: **untouched**, still verify against their published
  `SHA256SUMS.txt`.
- Nothing published to PyPI. Nothing submitted to Termux.
- `pip install silica-lang` and `pkg install silica-lang` still do not work, and no
  document claims otherwise.
