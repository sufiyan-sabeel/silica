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

## 2a. The CI-built artefacts, compared directly (authoritative)

The comparison above was made with a local build. This one uses the artefacts CI
produced for commit `3acace06` — downloaded from the workflow run, not rebuilt by
hand — with `SOURCE_DATE_EPOCH` set from the commit timestamp.

| Artefact | Published v0.10.0 | CI-built from `main` | Identical |
|---|---|---|---|
| wheel | `cf08d36187b819f68ff8690a6ffd8ee4a216f3e190322e10e200e398767e546c` | `c8a34578ec03c343ab26b0c79863ba67983c1ecc681f594de6803b6abbf75641` | **no** |
| sdist | `dcd7845a14003889ace504d93fc8020aa0faf45be7b3421290f77fca6237fc1e` | `efdc9b8c617190d30452ed69b3aaf4ca7c8d08a38673e4934d9310df29dcb317` | **no** |

Neither artefact matches, and the differences are **content**, not timestamps:

- **wheel**: 71 files in both, none added or removed, and exactly **2 differ** —
  `dist-info/METADATA` and `dist-info/RECORD` (classifiers and Documentation/
  Changelog URLs were added to `pyproject.toml` after the tag).
- **sdist**: 118 files published, **207** in CI. **89 files are new** — `MANIFEST.in`,
  which came after the tag, brings in the examples, docs, tests, benchmarks,
  `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md` and the installers. **5 files
  differ** in content: `PKG-INFO`, `README.md`, `pyproject.toml`,
  `silica_lang.egg-info/PKG-INFO`, `silica_lang.egg-info/SOURCES.txt`.

No source file differs in either artefact. The published assets are therefore
correct for the code they shipped; they are simply not what `main` builds today.

**Verdict: neither artefact may be published as `0.10.0`.** The next release must
carry a new version number.

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

**Do not publish `0.10.0` to PyPI from `main`. Publish `0.10.1` built from the
commit that ships** — confirmed by the CI-built comparison in §2a, where neither
artefact matches the published ones.

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
