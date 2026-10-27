"""Silica — a small, statically typed, bytecode-compiled language.

Reference implementation (Milestone A–C of the Silica plan): lexer, parser,
type checker, bytecode compiler, verifier, stack VM, CLI and a small standard
library. See docs/LANGUAGE_SPEC.md for the language and docs/BYTECODE.md for
the `.sbc` format.
"""

__version__ = "0.4.0"
__all__ = ["__version__", "run_source", "compile_source", "check_source"]


def run_source(*args, **kwargs):
    from .engine import run_source as _run
    return _run(*args, **kwargs)


def compile_source(*args, **kwargs):
    from .engine import compile_source as _compile
    return _compile(*args, **kwargs)


def check_source(*args, **kwargs):
    from .engine import check_source as _check
    return _check(*args, **kwargs)
