"""Shared helpers for the Silica test suite."""

import io

from silica.bytecode import (Chunk, Function, deserialize, encode, serialize,
                             verify_chunk)
from silica.engine import check_source, compile_source, run_source
from silica.errors import SilicaError


def run(source, stdin="", filename="<test>"):
    """Run Silica source; returns (exit_code, stdout_text)."""
    out = io.StringIO()
    code = run_source(source, filename, stdin=io.StringIO(stdin), stdout=out,
                      stderr=io.StringIO())
    return code, out.getvalue()


def compile_chunk(source, filename="<test>"):
    return compile_source(source, filename).chunk


def expect_error(testcase, source, kind, fragment=None, stdin=""):
    """Assert that running `source` raises SilicaError of `kind`."""
    with testcase.assertRaises(kind) as ctx:
        run(source, stdin=stdin)
    if fragment is not None:
        testcase.assertIn(fragment, str(ctx.exception))
    return ctx.exception


def make_chunk(code, constants=None, globals_=None, functions=None, entry=0,
               n_locals=4, max_stack=16, name="main", arity=0):
    fn = Function(name, arity, n_locals, max_stack, "Unit", code, [])
    funcs = functions if functions is not None else [fn]
    return Chunk(constants or [], globals_ or [], funcs, entry=entry)


def bytecode_roundtrip(chunk):
    data = serialize(chunk)
    return deserialize(data), data


__all__ = ["run", "compile_chunk", "expect_error", "make_chunk",
           "bytecode_roundtrip", "encode", "verify_chunk", "serialize",
           "deserialize", "Chunk", "Function", "SilicaError", "check_source",
           "io"]
