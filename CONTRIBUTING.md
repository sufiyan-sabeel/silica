# Contributing to Silica

Thanks for taking a look. Silica is a small language with a small engine; the
goal is a correct, readable, well-tested core rather than a wide feature surface.

## Before you start

* Read `docs/LANGUAGE_SPEC.md` and `docs/BYTECODE.md`. Behaviour that contradicts
  the spec is a bug; behaviour the spec does not describe needs a spec change
  first.
* Check `docs/ROADMAP.md` for what is in scope right now. Please do not add a
  module or a keyword that the roadmap has not scheduled — stubs and
  half-features are worse than absence.

## Development setup

```bash
git clone https://github.com/sufiyan-sabeel/silica.git silica
cd silica
python3 -m unittest discover -s tests -t .   # must be green before and after
```

No third-party runtime dependencies; the engine uses only the Python standard
library.

## What a good change looks like

1. **One concern per change.** A parser fix and a VM optimisation in one commit
   are two commits.
2. **Tests first or alongside.** New language behaviour needs a test in
   `tests/test_*.py`; new CLI behaviour needs a `tests/test_cli.py` case; a new
   example needs an entry in `tests/test_examples.py` so its documented output
   stays true.
3. **Error messages are part of the product.** Every new diagnostic should name
   the problem and, where it helps, the fix — `SilicaError` takes a `hint`.
4. **Update the docs in the same change**: `docs/LANGUAGE_SPEC.md` for semantics,
   `docs/GRAMMAR.md` for syntax, `docs/STANDARD_LIBRARY.md` for a new native,
   `CHANGELOG.md` for anything a user would notice.
5. **Do not weaken the verifier** to make a test pass. If the verifier rejects
   something the compiler emits, the compiler is wrong.

## Style

* Python: 4-space indent, ~90 column soft limit, `snake_case`, no external
  dependencies, no bare `except`.
* Silica sources (examples, tests): run `python3 -m silica fmt <file>` before
  committing; the suite checks canonical formatting.
* Comments explain *why*, not *what*.

## Reporting bugs

Include the source file (or a minimal reproduction), the exact command, the
output you got and the output you expected. If it involves bytecode, say whether
the file came from `silica compile` and include `silica --version`.

## Security issues

Do not open a public issue for a verifier bypass or a crash on hostile bytecode;
see `SECURITY.md`.
