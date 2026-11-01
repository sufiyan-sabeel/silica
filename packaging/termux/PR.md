# Pull request: add `silica-lang` (Silica programming language)

Ready-to-submit description for
[termux/termux-packages](https://github.com/termux/termux-packages). Nothing here
has been submitted; this is the text and the evidence, for the maintainers.

---

## What this adds

A package for **Silica**, a small, statically typed, bytecode-compiled programming
language implemented in pure Python. The package installs the compiler, checker,
VM, standard library and CLI, and provides the `silica` executable.

- Upstream: https://github.com/sufiyan-sabeel/silica
- Release: https://github.com/sufiyan-sabeel/silica/releases/tag/v0.10.0
- License: MIT
- Version packaged: 0.10.0

## Recipe

`packages/silica-lang/build.sh`:

```bash
TERMUX_PKG_HOMEPAGE=https://github.com/sufiyan-sabeel/silica
TERMUX_PKG_DESCRIPTION="A small, statically typed, bytecode-compiled programming language"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@sufiyan-sabeel"
TERMUX_PKG_VERSION="0.10.0"
TERMUX_PKG_REVISION=1
TERMUX_PKG_SRCURL="https://github.com/sufiyan-sabeel/silica/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz"
TERMUX_PKG_SHA256=0b416fdf5a9c929553d93bfa7d44611daffb1e4d406979a30365e8107726eeba
TERMUX_PKG_AUTO_UPDATE=true
TERMUX_PKG_UPDATE_VERSION_REGEXP='\d+(?:\.\d+){1,2}'
TERMUX_PKG_DEPENDS="python, python-pip"
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_SETUP_PYTHON=true
```

with `termux_step_make` empty and `termux_step_make_install` running
`cross-pip install --no-deps --prefix="$TERMUX_PREFIX" "$TERMUX_PKG_SRCDIR"`,
followed by `chmod 755` on the launcher and installation of the docs and examples
into `$TERMUX_PREFIX/share/`.

The recipe follows `packages/httpie/build.sh`, the closest existing analogue (a
Python CLI installed with `cross-pip`).

## Why `TERMUX_PKG_PLATFORM_INDEPENDENT=true`

The engine is pure Python: no C extensions, no native libraries, no
architecture-specific data. The same package installs on aarch64, arm, i686 and
x86_64, as `python-pip` does.

## Dependencies

`python` and `python-pip` — the same pair `httpie` declares. Silica has **no
runtime dependencies of its own**: the language, CLI, standard library, TUI and
IDE use only the Python standard library.

Two optional features pull in more, and neither is a hard dependency:

| Feature | Needs |
|---|---|
| `use speech` (text-to-speech) | `onnxruntime`, `espeak-ng` — the module reports clearly when they are missing |
| `use python` (interop) | nothing extra; it starts a child process using the same `python` |

## Verification performed

Built and tested on **Linux x86_64, Python 3.12.13** — not on Android:

- 1265 tests pass (`pytest tests`), 7 skipped.
- The v0.10.0 wheel and sdist both verify against the published
  `SHA256SUMS.txt`.
- `pip install` of the published wheel into a clean virtualenv: `silica --version`
  reports `silica 0.10.0`; `silica run` executes a program; `use path`, `use time`
  and `use random` work; `use python` starts its worker and calls
  `math.sqrt`.
- Filesystem capabilities are enforced: reading outside the granted root is
  refused.

## Verification **not** performed

**Nothing has been built or run on a Termux device or on Android.** The recipe has
been checked against the conventions of existing Python packages in this repository
and `bash -n` parses it, but a crossenv build and an on-device install have not
happened. That is why this PR asks for review rather than claiming the package
works.

## What to check on a device

```bash
./build-package.sh silica-lang
pkg install ./output/silica-lang_*.deb

silica --version                     # expect: silica 0.10.0
silica run $PREFIX/share/silica-lang/examples/hello.sc
silica run $PREFIX/share/silica-lang/examples/calculator_app.sc   # 6 * 7, then quit
```

And the parts most likely to differ from desktop Linux:

1. **The interop worker** — `python -m silica.interop.worker_main` must start as a
   child process inside Termux.
2. **`time.monotonic`** and `random`'s CSPRNG — both go through CPython, but worth
   confirming on Android.
3. **`espeak-ng` / `onnxruntime`** — the speech module should report a missing
   backend rather than crash.

If any of those fail, the fix belongs upstream first; ping me and I will address it
in a patch release rather than patching it in this repository.
