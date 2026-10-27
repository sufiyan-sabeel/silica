"""The `silica` command-line interface.

Commands implemented in v0.1.1:

    silica run <file.sc|file.sbc>   compile (if needed), verify, execute
    silica check <file.sc>          parse + type-check only
    silica compile <file.sc>        write <name>.sbc
    silica repl                     interactive session with persistent globals
    silica fmt <file.sc>            rewrite the file in canonical style
    silica test [dir]               run every *_test.sc under dir (default: tests)
    silica --version

Anything the spec calls "planned" is reported as not implemented rather than
stubbed out with a fake success.
"""

import io
import os
import sys

from . import ast
from .bytecode import serialize
from .capabilities import FS_LIST, FS_READ, FS_WRITE, CapabilitySet
from .engine import (check_source, compile_ast, compile_file, compile_source,
                     default_output_path, is_bytecode, load_bytecode, run_chunk,
                     run_chunk_vm)
from .errors import CapabilityError, ParseError, SilicaError
from .natives import format_value, get_native

VERSION = "0.1.1"

USAGE = """silica %s — the Silica language toolchain

usage:
  silica run <file.sc|file.sbc>   compile if needed, then execute
  silica check <file.sc>          parse and type-check only
  silica compile <file.sc> [-o out.sbc]
                                  compile to versioned bytecode
  silica repl                     interactive session
  silica fmt <file.sc> [--check]  rewrite in canonical style
  silica test [dir]               run *_test.sc files under dir
  silica capabilities [flags]     print the effective capability set
  silica --version                print the version
  silica --help                   print this message

Capabilities (nothing is granted by default):
  --allow-fs-read DIR    allow reading files under DIR
  --allow-fs-write DIR   allow writing files under DIR
  --allow-fs-list DIR    allow listing directories under DIR
  --deny-fs-read|write|list
                         remove a capability a config file granted
  --capabilities FILE    read grants from a TOML [capabilities] table

Not implemented in 0.1.1: new, add, remove, install, build (Milestone E).
""" % VERSION


# capability flags, parsed by every command that runs a program
ALLOW_FLAGS = {
    "--allow-fs-read": FS_READ,
    "--allow-fs-write": FS_WRITE,
    "--allow-fs-list": FS_LIST,
}

DENY_FLAGS = {
    "--deny-fs-read": FS_READ,
    "--deny-fs-write": FS_WRITE,
    "--deny-fs-list": FS_LIST,
}


def _parse_capabilities(args, base=None):
    """Split capability flags out of `args`.

    Returns (capability_set, remaining_args). The config file is applied first
    and the command-line flags on top, so a caller can narrow a config file
    without editing it.
    """
    config_path = None
    grants = []
    denies = []
    rest = []
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--capabilities" or item.startswith("--capabilities="):
            if item == "--capabilities":
                if index + 1 >= len(args):
                    raise CapabilityError("--capabilities needs a TOML file")
                config_path = args[index + 1]
                index += 2
            else:
                config_path = item.split("=", 1)[1]
                index += 1
            continue
        kind = ALLOW_FLAGS.get(item)
        if kind is not None:
            if index + 1 >= len(args):
                raise CapabilityError("%s needs a directory" % item)
            grants.append((kind, args[index + 1]))
            index += 2
            continue
        if item.startswith("--allow-fs-") and "=" in item:
            flag, value = item.split("=", 1)
            kind = ALLOW_FLAGS.get(flag)
            if kind is not None:
                grants.append((kind, value))
                index += 1
                continue
        kind = DENY_FLAGS.get(item)
        if kind is not None:
            denies.append(kind)
            index += 1
            continue
        rest.append(item)
        index += 1

    if config_path is not None:
        caps = CapabilitySet.from_file(config_path, base=base)
    else:
        caps = CapabilitySet.empty(base)
    for kind, root in grants:
        caps = caps.grant(kind, root)
    for kind in denies:
        caps = caps.deny(kind)
    return caps, rest


def _fail(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    return code


def _read_source(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        raise SilicaError("no such file: %s" % path)
    except IsADirectoryError:
        raise SilicaError("%s is a directory, not a Silica source file" % path)


# --- commands ----------------------------------------------------------------
def cmd_run(args):
    caps, args = _parse_capabilities(args)
    if not args:
        return _fail("usage: silica run <file.sc|file.sbc> [capability flags]", 2)
    path = args[0]
    if not os.path.exists(path):
        return _fail("error: no such file: %s" % path)
    try:
        if is_bytecode(path):
            chunk = load_bytecode(path)
            code = run_chunk(chunk, path, capabilities=caps)
        else:
            result = compile_file(path)
            code = run_chunk(result.chunk, path, capabilities=caps)
    except SilicaError as err:
        err.with_file(path)
        return _fail(err.format())
    return code & 0xFF


def cmd_capabilities(args):
    caps, rest = _parse_capabilities(args)
    if rest:
        return _fail("error: unexpected argument '%s'" % rest[0], 2)
    sys.stdout.write("Silica capability set — least privilege: nothing is granted "
                     "unless named\n")
    for line in caps.report():
        sys.stdout.write("  %s\n" % line)
    sys.stdout.write("  %-9s %-16s %s\n" % ("base", "paths", caps.base))
    if caps.is_empty():
        sys.stdout.write("  (empty: this program cannot touch the filesystem)\n")
    return 0


def cmd_check(args):
    if not args:
        return _fail("usage: silica check <file.sc>", 2)
    path = args[0]
    try:
        source = _read_source(path)
        check_source(source, path)
    except SilicaError as err:
        err.with_file(path)
        return _fail(err.format())
    return 0


def cmd_compile(args):
    if not args:
        return _fail("usage: silica compile <file.sc> [-o out.sbc]", 2)
    path = args[0]
    out = None
    if "-o" in args:
        idx = args.index("-o")
        if idx + 1 >= len(args):
            return _fail("error: -o needs a path", 2)
        out = args[idx + 1]
    try:
        result = compile_file(path)
        data = serialize(result.chunk)
    except SilicaError as err:
        err.with_file(path)
        return _fail(err.format())
    if out is None:
        out = default_output_path(path)
    try:
        with open(out, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        return _fail("error: cannot write %s: %s" % (out, exc))
    sys.stdout.write("wrote %s (%d bytes)\n" % (out, len(data)))
    return 0


def cmd_fmt(args):
    if not args:
        return _fail("usage: silica fmt <file.sc> [--check]", 2)
    check_only = "--check" in args
    paths = [a for a in args if not a.startswith("-")]
    if not paths:
        return _fail("error: no file given", 2)
    from .fmt import format_source

    status = 0
    for path in paths:
        try:
            source = _read_source(path)
            formatted = format_source(source, path)
        except SilicaError as err:
            err.with_file(path)
            _fail(err.format())
            status = 1
            continue
        if formatted == source:
            if not check_only:
                sys.stdout.write("%s is already formatted\n" % path)
            continue
        if check_only:
            sys.stdout.write("%s would be reformatted\n" % path)
            status = 1
            continue
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(formatted)
        except OSError as exc:
            _fail("error: cannot write %s: %s" % (path, exc))
            status = 1
            continue
        sys.stdout.write("formatted %s\n" % path)
    return status


def _discover_tests(root):
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith("_test.sc"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def cmd_test(args):
    root = args[0] if args else "tests"
    if not os.path.isdir(root):
        return _fail("error: no test directory at %s" % root, 2)
    files = _discover_tests(root)
    if not files:
        return _fail("error: no *_test.sc files under %s" % root, 2)
    passed = 0
    failures = []
    for path in files:
        try:
            source = _read_source(path)
            compiled = compile_source(source, path)
            out = io.StringIO()
            run_chunk(compiled.chunk, path, stdin=io.StringIO(""), stdout=out)
            passed += 1
        except SilicaError as err:
            err.with_file(path)
            failures.append((path, err.format()))
        except Exception as exc:  # pragma: no cover - unexpected engine bug
            failures.append((path, "internal error: %s" % exc))
    for path, message in failures:
        sys.stderr.write("FAIL %s\n%s\n" % (path, message))
    total = len(files)
    sys.stdout.write("%d/%d test files passed\n" % (passed, total))
    if failures:
        sys.stdout.write("failed: %s\n" % ", ".join(os.path.basename(p) for p, _ in failures))
        return 1
    return 0


# --- REPL --------------------------------------------------------------------
class Repl:
    """Line-oriented REPL with persistent globals and functions.

    Each entry is compiled together with the declarations entered earlier, so
    functions and globals stay available. Only the new statements run, which
    is why earlier input is not re-executed.
    """

    def __init__(self, stdin, stdout, stderr, capabilities=None):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.capabilities = (capabilities if capabilities is not None
                             else CapabilitySet.empty())
        self.decls = []
        self.globals = []
        self.index = {}
        self.values = []
        self.func_infos = {}

    def _returns_unit(self, expr):
        if not isinstance(expr, ast.Call):
            return False
        callee = expr.callee
        if isinstance(callee, ast.Ident):
            native = get_native("core", callee.name)
            if native is not None:
                return native.ret == "Unit"
            info = self.func_infos.get(callee.name)
            if info is not None:
                return info.ret == "Unit"
        elif isinstance(callee, ast.Member) and isinstance(callee.obj, ast.Ident):
            native = get_native(callee.obj.name, callee.name)
            if native is not None:
                return native.ret == "Unit"
        return False

    def _wrap(self, stmt):
        if isinstance(stmt, ast.ExprStmt) and not self._returns_unit(stmt.expr):
            call = ast.Call(ast.Ident("sprint", line=stmt.line, col=stmt.col),
                            [stmt.expr], line=stmt.line, col=stmt.col)
            return ast.ExprStmt(call, line=stmt.line, col=stmt.col)
        return stmt

    def submit(self, text):
        """Run one complete entry. Returns True if the entry was accepted."""
        from .lexer import tokenize
        from .parser import parse

        tokens, _comments = tokenize(text, "<repl>")
        program = parse(tokens, "<repl>")

        decls = [s for s in program.stmts if isinstance(s, (ast.UseStmt, ast.FuncDecl))]
        lets = [s for s in program.stmts if isinstance(s, ast.LetStmt)]
        rest = [s for s in program.stmts
                if not isinstance(s, (ast.UseStmt, ast.FuncDecl, ast.LetStmt))]

        if not lets and not rest:
            self.decls.extend(decls)
            for decl in decls:
                if isinstance(decl, ast.FuncDecl):
                    self.stdout.write("defined %s\n" % decl.name)
                else:
                    self.stdout.write("using %s\n" % decl.module)
            return True

        body = [self._wrap(s) for s in rest]
        synthetic = ast.FuncDecl("__repl_main", [], None,
                                 ast.Block(body, line=1, col=1), line=1, col=1)
        stmts = list(self.decls) + decls + lets + [synthetic]
        repl_program = ast.Program(stmts, line=1, col=1)

        compiled = compile_ast(repl_program, "<repl>", require_main=False,
                               pre_globals=self.globals, pre_index=self.index,
                               entry_name="__repl_main")
        out = io.StringIO()
        _code, vm = run_chunk_vm(compiled.chunk, "<repl>", stdin=self.stdin,
                                 stdout=out, initial_globals=self.values,
                                 capabilities=self.capabilities)
        self.stdout.write(out.getvalue())

        self.decls.extend(decls)
        self.globals = list(compiled.chunk.globals)
        self.index = {name: i for i, (name, _t) in enumerate(self.globals)}
        self.values = vm.global_values()
        self.func_infos.update(compiled.checker.functions)
        for stmt in lets:
            slot = self.index.get(stmt.name)
            if slot is not None and slot < len(self.values):
                type_name = self.globals[slot][1]
                self.stdout.write("%s: %s = %s\n" % (
                    stmt.name, type_name, format_value(self.values[slot])))
        return True


def cmd_repl(args):
    caps, _rest = _parse_capabilities(args)
    stdin = sys.stdin
    stdout = sys.stdout
    stderr = sys.stderr
    repl = Repl(stdin, stdout, stderr, capabilities=caps)
    stdout.write("Silica %s REPL — :help for commands, :quit to exit\n" % VERSION)
    buffer = []
    while True:
        prompt = "silica> " if not buffer else "   ...> "
        stdout.write(prompt)
        stdout.flush()
        line = stdin.readline()
        if line == "":
            stdout.write("\n")
            return 0
        stripped = line.strip()
        if not buffer and stripped in (":quit", ":q", "exit", "quit"):
            return 0
        if not buffer and stripped == ":help":
            stdout.write("  :help    this text\n  :quit    leave the REPL\n"
                         "  :globals list current globals\n")
            continue
        if not buffer and stripped == ":globals":
            if not repl.globals:
                stdout.write("(no globals)\n")
            for i, (name, type_name) in enumerate(repl.globals):
                value = repl.values[i] if i < len(repl.values) else None
                stdout.write("  %s: %s = %s\n" % (name, type_name, format_value(value)))
            continue
        if not stripped and not buffer:
            continue
        buffer.append(line)
        source = "".join(buffer)
        try:
            repl.submit(source)
            buffer = []
        except ParseError as err:
            if "unexpected end of file" in err.message:
                continue  # keep buffering a multi-line block
            sys.stderr.write(err.format() + "\n")
            buffer = []
        except SilicaError as err:
            sys.stderr.write(err.format() + "\n")
            buffer = []
    return 0


# --- entry point -------------------------------------------------------------
COMMANDS = {
    "run": cmd_run,
    "check": cmd_check,
    "compile": cmd_compile,
    "fmt": cmd_fmt,
    "test": cmd_test,
    "repl": cmd_repl,
    "capabilities": cmd_capabilities,
}

PLANNED = {
    "new": "project scaffolding (Milestone E)",
    "add": "dependency management (Milestone E)",
    "remove": "dependency management (Milestone E)",
    "install": "dependency management (Milestone E)",
    "build": "project builds with silica.toml (Milestone E)",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stdout.write(USAGE)
        return 0
    first = argv[0]
    if first in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    if first in ("-V", "--version", "version"):
        sys.stdout.write("silica %s\n" % VERSION)
        return 0
    if first in PLANNED:
        return _fail("error: 'silica %s' is not implemented in 0.1.1 (%s)"
                     % (first, PLANNED[first]))
    handler = COMMANDS.get(first)
    if handler is None:
        return _fail("error: unknown command '%s'\n\n%s" % (first, USAGE), 2)
    try:
        return handler(argv[1:])
    except SilicaError as err:
        return _fail(err.format())
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
