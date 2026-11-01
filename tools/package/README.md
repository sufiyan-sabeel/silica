# Packaging tooling

The packaging check is written in **Silica**. This file explains exactly where
Silica ends and Python begins, because the boundary matters.

## The split

| Step | Language | File |
|---|---|---|
| Collect facts: build, list archive members, hash the artefacts | Python | `facts.py` |
| Write `dist/SHA256SUMS.txt` from the facts | **Silica** | `sums.sc` |
| Decide whether the release is acceptable | **Silica** | `verify.sc` |

Silica has no zip reader, no tar reader, no SHA-256 (its `crypto` module is still
planned) and cannot start a process. Those four operations are the entire reason
`facts.py` exists. Everything that constitutes a *policy* — is the version
consistent across five files, does the wheel contain the worker, has a source file
leaked into the wheel, does the sdist carry the examples, do the checksums match
the artefacts — is Silica source.

`facts.py` decides nothing. It runs one fixed command (`python -m build`) when
asked, lists archive members, hashes files and writes JSON. No network, no shell,
no arbitrary execution, no credentials.

## Running it

```bash
python3 -m build                                                   # or use --build below
python3 tools/package/facts.py --dist-dir dist --out build/packaging/facts.json
python3 -m silica run --allow-fs-read . --allow-fs-write . tools/package/sums.sc
python3 -m silica run --allow-fs-read . --allow-fs-write . tools/package/verify.sc
```

`verify.sc` exits non-zero when anything is wrong and writes
`build/packaging/report.json`:

```json
{
  "distribution": "silica-lang",
  "version": "0.10.0",
  "ok": true,
  "problems": [],
  "wheel": "silica_lang-0.10.0-py3-none-any.whl",
  "wheel_sha256": "8e49d32c…",
  "sdist": "silica_lang-0.10.0.tar.gz",
  "sdist_sha256": "d53f1110…"
}
```

The capability flags are not decoration: without `--allow-fs-read` the checker
cannot read a single file, and a test asserts that it fails rather than silently
passing.

## What it checks

1. **Version consistency** — `pyproject.toml`, `silica/__init__.py`,
   `silica/cli.py`, `install.sh` and `CHANGELOG.md` all carry the intended
   version. This is the check that would have caught the stale installer pin at
   release time.
2. **Identity** — distribution name `silica-lang` and entry point
   `silica = "silica.cli:main"`.
3. **Wheel contents** — every runtime module present (including the interop
   worker and the three new stdlib modules), no `tests/`, `examples/`, `docs/`,
   `benchmarks/`, `editors/` or `packaging/` files, and a `dist-info` with both
   `METADATA` and `entry_points.txt`.
4. **Sdist contents** — the examples, docs, tests, `MANIFEST.in` and the
   installers.
5. **Checksums** — `dist/SHA256SUMS.txt` lists both artefacts and both digests
   match the files.
6. **Artefact names** — the wheel and sdist filenames carry the version.

## Tests

`tests/test_packaging_silica.py` runs the real repository end to end, then breaks
a synthetic repository fifteen different ways and asserts each breakage is named
specifically. It also asserts the boundary: `verify.sc` imports only `fs`, `json`
and `string`, contains no process or network call, and `facts.py` has exactly one
`subprocess.run` with a fixed argument list.
