"""The Silica engine pipeline: source -> tokens -> AST -> checked -> bytecode.

This module is the one place that wires the stages together, so the CLI, the
REPL and the test suite all exercise the same path.
"""

import os

from . import ast
from .bytecode import Chunk, deserialize, serialize, verify_chunk
from .capabilities import CapabilitySet
from .checker import Checker
from .compiler import Compiler
from .errors import SilicaError
from .lexer import tokenize
from .parser import parse
from .vm import VM

SOURCE_EXT = ".sc"
BYTECODE_EXT = ".sbc"


class CompileResult:
    __slots__ = ("chunk", "program", "comments", "checker")

    def __init__(self, chunk, program, comments, checker):
        self.chunk = chunk
        self.program = program
        self.comments = comments
        self.checker = checker


def check_source(source, filename="<source>", require_main=True):
    """Parse and type-check without producing bytecode. Returns the checker."""
    try:
        tokens, comments = tokenize(source, filename)
        program = parse(tokens, filename)
        checker = Checker(program, filename, require_main=require_main)
        checker.check()
    except RecursionError:
        raise _too_deep(filename)
    return program, comments, checker


def compile_ast(program, filename="<source>", require_main=True,
                pre_globals=None, pre_index=None, entry_name="main"):
    """Compile an already-parsed program through checking, codegen and verify."""
    checker = Checker(program, filename, require_main=require_main,
                      pre_globals=pre_globals)
    checker.check()
    compiler = Compiler(program, filename, checker.functions, checker.globals,
                        pre_globals=pre_globals, pre_index=pre_index)
    chunk = compiler.compile()
    if entry_name != "main":
        chunk.entry = compiler.func_index.get(entry_name)
    verify_chunk(chunk, filename)
    return CompileResult(chunk, program, [], checker)


def compile_source(source, filename="<source>", require_main=True,
                   pre_globals=None, pre_index=None, entry_name="main"):
    try:
        tokens, comments = tokenize(source, filename)
        program = parse(tokens, filename)
        result = compile_ast(program, filename, require_main, pre_globals,
                             pre_index, entry_name)
    except RecursionError:
        raise _too_deep(filename)
    result.comments = comments
    return result


def _too_deep(filename):
    return SilicaError("expression or block nesting is too deep to compile",
                       0, 0, filename,
                       "simplify the expression, or split it into several statements")


def run_source(source, filename="<source>", stdin=None, stdout=None, stderr=None,
               max_frames=4096, capabilities=None):
    result = compile_source(source, filename)
    vm = VM(result.chunk, stdin=stdin, stdout=stdout, stderr=stderr,
            max_frames=max_frames, filename=filename, capabilities=capabilities)
    return vm.run(verify=False)


def compile_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    return compile_source(source, path)


def load_bytecode(path):
    with open(path, "rb") as handle:
        data = handle.read()
    chunk = deserialize(data, path)
    verify_chunk(chunk, path)
    return chunk


def run_chunk(chunk, filename="<bytecode>", stdin=None, stdout=None, stderr=None,
              max_frames=4096, capabilities=None):
    vm = VM(chunk, stdin=stdin, stdout=stdout, stderr=stderr,
            max_frames=max_frames, filename=filename, capabilities=capabilities)
    return vm.run(verify=False)


def run_chunk_vm(chunk, filename="<bytecode>", stdin=None, stdout=None, stderr=None,
                 max_frames=4096, initial_globals=None, capabilities=None):
    """Run a chunk and hand back the VM, so callers can read final globals."""
    vm = VM(chunk, stdin=stdin, stdout=stdout, stderr=stderr,
            max_frames=max_frames, filename=filename, initial_globals=initial_globals,
            capabilities=capabilities)
    code = vm.run(verify=False)
    return code, vm


def default_output_path(source_path):
    """Bytecode goes next to the source: dir/main.sc -> dir/main.sbc."""
    root, ext = os.path.splitext(source_path)
    if ext == SOURCE_EXT:
        return root + BYTECODE_EXT
    return source_path + BYTECODE_EXT


def is_bytecode(path):
    return path.endswith(BYTECODE_EXT)


__all__ = [
    "CompileResult", "check_source", "compile_ast", "compile_source",
    "compile_file", "load_bytecode", "run_source", "run_chunk", "run_chunk_vm",
    "default_output_path", "is_bytecode", "Chunk", "serialize", "ast",
    "SilicaError", "CapabilitySet",
]
