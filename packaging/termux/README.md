# Termux packaging

`silica-lang/build.sh` is a Termux package recipe for Silica 0.10.0, written to
the conventions of the official `termux-packages` tree.

## Status, stated precisely

| Path | Status |
|---|---|
| The recipe itself | **Written and reviewed against Termux conventions** |
| Built and installed on a device | **Not done.** No Termux/ARM64 environment was available, so nothing here has been executed on Android |
| Available via `pkg install silica-lang` from the default repositories | **No.** The package is not in `termux-packages`; that requires a pull request to that repository and its maintainers' review |

Do not tell anyone that `pkg install silica-lang` works. It does not, yet.

## What the recipe does

- **Source**: the v0.10.0 tag tarball, pinned by SHA-256
  (`0b416fdf5a9c929553d93bfa7d44611daffb1e4d406979a30365e8107726eeba`, computed
  from the published tag).
- **Dependency**: `python` only. Silica has no runtime dependencies of its own —
  no compiled extensions, no `numpy`, no native libraries. `onnxruntime` and
  `espeak-ng` are needed only by the speech module, which is optional.
- **Platform independent**: the engine is pure Python, so one package serves
  aarch64 and arm.
- **Install layout**: the wheel is built and installed into `$PREFIX`, the
  `silica` launcher is forced to mode 755, and the docs and examples land in
  `$PREFIX/share/`.
- **No root**: nothing outside `$PREFIX` is touched.

## The Python worker

The `python` interop module starts a child process (`python -m
silica.interop.worker_main`). In Termux that child is the same `python` package
the recipe depends on, so it should work — **but it has not been run on Android**,
and `docs/SECURITY_MODEL.md` already says the worker is a separate process with
the privileges of the interpreter, not a sandbox.

## To try it (on a Termux device)

```bash
pkg install git python
git clone https://github.com/termux/termux-packages
cp -r packaging/termux/silica-lang termux-packages/packages/
cd termux-packages
./build-package.sh silica-lang        # builds the .deb in output/
pkg install ./output/silica-lang_*.deb
silica --version                       # expect: silica 0.10.0
```

Then, to verify the parts that matter:

```bash
silica run $PREFIX/share/silica-lang/examples/hello.sc
silica run $PREFIX/share/silica-lang/examples/calculator_app.sc   # type 6 * 7, then quit
silica --allow-interop-python run - <<<'use python
sfn main() {
    let m: Any = python.import("math")
    sprint(python.call(m, "sqrt", [2]))
    python.stop()
}'
```

If any of that fails, the recipe needs fixing before it is proposed upstream.

## Publishing options

**A. Official `termux-packages`.** Preferred. It needs a pull request adding this
recipe; maintainers review it, and only then does `pkg install silica-lang` work
from the default repositories.

**B. A Silica-maintained repository.** If official inclusion is not available, a
separate signed `apt` repository can host the `.deb`. That requires a signing key,
repository metadata (`Packages.gz`), and documented setup steps — none of which
exists yet, so nothing is claimed about it.
