"""The `silica` command-line interface.

Commands implemented in v0.8.0:

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
from .capabilities import (FS_LIST, FS_READ, FS_WRITE, GUI_RUN,
                           SPEECH_LISTEN, SPEECH_SPEAK, TUI_RUN,
                           CapabilitySet, grant_flag)
from .engine import (check_source, compile_ast, compile_file, compile_source,
                     default_output_path, is_bytecode, load_bytecode, run_chunk,
                     run_chunk_vm)
from .errors import CapabilityError, ParseError, SilicaError
from .natives import format_value, get_native

VERSION = "0.9.2"

USAGE = """silica %s — the Silica language toolchain

usage:
  silica <file.sc|file.sbc>       run a source file or bytecode directly
  silica                          start the interactive interpreter
  silica run <file.sc|file.sbc>   compile if needed, then execute
  silica check <file.sc>          parse and type-check only
  silica compile <file.sc> [-o out.sbc]
                                  compile to versioned bytecode
  silica repl                     interactive session
  silica fmt <file.sc> [--check]  rewrite in canonical style
  silica test [dir]               run *_test.sc files under dir
  silica ide [--root DIR] [--port N] [--host H]
                                  Script Mode IDE in your browser
  silica voice <subcommand>       speech: list, install, speak, transcribe
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

Not implemented in 0.8.0: new, add, remove, install, build (Milestone E).
""" % VERSION


# capability flags, parsed by every command that runs a program
ALLOW_FLAGS = {
    "--allow-fs-read": FS_READ,
    "--allow-fs-write": FS_WRITE,
    "--allow-fs-list": FS_LIST,
    "--allow-speech-speak": SPEECH_SPEAK,
    "--allow-speech-listen": SPEECH_LISTEN,
    "--allow-tui": TUI_RUN,
    "--allow-gui": GUI_RUN,
}

# these grant a facility, not a directory, so they take no value
UNSCOPED_FLAGS = {TUI_RUN, GUI_RUN}

DENY_FLAGS = {
    "--deny-fs-read": FS_READ,
    "--deny-fs-write": FS_WRITE,
    "--deny-fs-list": FS_LIST,
    "--deny-tui": TUI_RUN,
    "--deny-gui": GUI_RUN,
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
            if kind in UNSCOPED_FLAGS:
                grants.append((kind, "."))
                index += 1
                continue
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


# The interpreter prompt. U+00A2 CENT SIGN, followed by one space.
PROMPT = "\u00a2 "
CONTINUATION_PROMPT = PROMPT


def _write_prompt(stream, text):
    """Write the prompt, surviving a stdout that cannot encode it.

    A Cent sign needs a non-ASCII capable encoding. Termux and most Linux
    terminals are UTF-8, but a C/POSIX locale is not, and there `write` raises
    UnicodeEncodeError mid-session. Try to switch the stream to UTF-8, then fall
    back to a plain prompt rather than crashing the interpreter.
    """
    try:
        stream.write(text)
    except UnicodeEncodeError:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
                stream.write(text)
                return
            except (ValueError, OSError):  # pragma: no cover - exotic streams
                pass
        stream.write("> ")
    try:
        stream.flush()
    except Exception:  # pragma: no cover - a closed pipe on exit
        pass


def cmd_repl(args):
    caps, _rest = _parse_capabilities(args)
    stdin = sys.stdin
    stdout = sys.stdout
    stderr = sys.stderr
    repl = Repl(stdin, stdout, stderr, capabilities=caps)
    stdout.write("Silica Interpreter v%s\n" % VERSION)
    stdout.flush()
    buffer = []
    while True:
        prompt = PROMPT if not buffer else CONTINUATION_PROMPT
        _write_prompt(stdout, prompt)
        line = stdin.readline()
        if line == "":
            stdout.write("\n")
            return 0
        stripped = line.strip()
        if not buffer and stripped in (":quit", ":q", "exit", "quit"):
            stdout.write("\n")
            return 0
        if not buffer and stripped in (":help", "help", "?"):
            stdout.write("  help      this text (:help also works)\n"
                         "  exit      leave the interpreter (:quit also works)\n"
                         "  globals   list current globals (:globals also works)\n")
            continue
        if not buffer and stripped in (":globals", "globals"):
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


# --- voice -------------------------------------------------------------------
VOICE_USAGE = """usage: silica voice <subcommand>

  silica voice list                 voices available, and which are installed
  silica voice languages            what can be spoken and heard
  silica voice status               which engines are present
  silica voice install [name]       download a voice into the cache
  silica voice models               installed models: size, licence, checksum
  silica voice verify <name>        re-hash a model and compare
  silica voice remove <name>        delete an installed model
  silica voice use [name]           show or set the default voice
  silica voice speak "text" [opts]  synthesise and play
  silica voice transcribe <file>    transcribe a WAV
  silica voice info <file.wav>      duration, rate and level of a WAV

Options for `speak`: --voice NAME, --out PATH (write instead of play)
Options for `transcribe`: --model tiny|base|small|medium, --language CODE
"""


def cmd_voice(args):
    if not args:
        sys.stdout.write(VOICE_USAGE)
        return 0
    sub = args[0]
    rest = args[1:]
    from . import voice

    if sub in ("-h", "--help", "help"):
        sys.stdout.write(VOICE_USAGE)
        return 0

    if sub == "list":
        rows = voice.voices()
        if not rows:
            sys.stdout.write("no voices are known\n")
            return 0
        sys.stdout.write("%-26s %-7s %-10s %s\n" % ("voice", "lang", "installed", "label"))
        for row in rows:
            sys.stdout.write("%-26s %-7s %-10s %s\n" % (
                row["name"], row["language"],
                "yes" if row["installed"] else "-", row["label"]))
        return 0

    if sub == "languages":
        table = voice.languages()
        sys.stdout.write("speaking:\n")
        for code, names in table["speaking"].items():
            sys.stdout.write("  %-8s %s\n" % (code, ", ".join(names)))
        if table["speaking_missing"]:
            sys.stdout.write("\nno voice available (speech recognition still works):\n")
            for code, label in table["speaking_missing"].items():
                sys.stdout.write("  %-8s %s\n" % (code, label))
        sys.stdout.write("\nlistening: %s\n" % ", ".join(
            sorted(table["listening"])))
        return 0

    if sub == "status":
        info = voice.status()
        available = voice.available()
        sys.stdout.write("speaking : %s\n" % ("ready" if available["tts"] else "unavailable"))
        sys.stdout.write("listening: %s\n" % ("ready" if available["stt"] else "unavailable"))
        sys.stdout.write("espeak   : %s\n" % info["espeak"].get("detail", info["espeak"]))
        sys.stdout.write("onnxruntime: %s\n" % info["tts"].get("onnxruntime"))
        sys.stdout.write("whisper  : %s\n" % info["stt"].get("faster_whisper", "-"))
        sys.stdout.write("voices dir  : %s\n" % info["voices_dir"])
        sys.stdout.write("installed   : %s\n" % (", ".join(info["voices_installed"]) or "none"))
        sys.stdout.write("default     : %s\n" % info["default_voice"])
        return 0

    if sub == "models":
        rows = voice.models()
        if not rows:
            sys.stdout.write("no models installed\n")
            return 0
        sys.stdout.write("%-26s %-8s %-14s %8s  %s\n"
                         % ("voice", "lang", "licence", "size", "checksum"))
        for row in rows:
            sys.stdout.write("%-26s %-8s %-14s %7.1fM  %s\n" % (
                row["name"], row["language"], row["licence"],
                row["bytes"] / (1024.0 * 1024.0),
                (row["sha256"] or "not recorded")[:16]))
        storage = voice.storage()
        sys.stdout.write("\n%.1f MB of models in %s\n"
                         % (storage["model_megabytes"], storage["directory"]))
        return 0

    if sub == "verify":
        if not rest:
            sys.stderr.write("usage: silica voice verify <name>\n")
            return 2
        result = voice.verify(rest[0])
        sys.stdout.write("%s: %s\n" % (
            result["name"], "ok" if result["verified"] else "NOT VERIFIED"))
        if not result["verified"]:
            sys.stdout.write("  %s\n" % result.get("reason"))
            return 1
        return 0

    if sub in ("remove", "delete", "uninstall"):
        if not rest:
            sys.stderr.write("usage: silica voice remove <name>\n")
            return 2
        try:
            freed = voice.delete_model(rest[0])["freed_bytes"]
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("%s\n" % exc)
            return 1
        sys.stdout.write("removed %s, freed %.1f MB\n"
                         % (rest[0], freed / (1024.0 * 1024.0)))
        return 0

    if sub == "use":
        if not rest:
            sys.stdout.write("%s\n" % voice.current_voice())
            return 0
        try:
            voice.set_voice(rest[0] if rest[0] != "default" else None)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("%s\n" % exc)
            return 1
        sys.stdout.write("default voice: %s\n" % voice.current_voice())
        return 0

    if sub == "install":
        name = rest[0] if rest else None
        try:
            path = voice.install(name)
        except Exception as exc:
            return _fail("error: %s" % exc)
        sys.stdout.write("installed %s\n  at %s\n" % (
            name or "the default voice", path))
        return 0

    if sub == "speak":
        text_parts, options = [], {"voice": None, "out": None}
        index = 0
        while index < len(rest):
            item = rest[index]
            if item == "--voice" and index + 1 < len(rest):
                options["voice"] = rest[index + 1]
                index += 2
                continue
            if item == "--out" and index + 1 < len(rest):
                options["out"] = rest[index + 1]
                index += 2
                continue
            text_parts.append(item)
            index += 1
        text = " ".join(text_parts).strip()
        if not text:
            return _fail("usage: silica voice speak \"text\" [--voice NAME] [--out PATH]", 2)
        try:
            if options["out"]:
                path = voice.synthesize(text, out=options["out"], voice=options["voice"])
                from .voice import audio
                info = audio.describe(path)
                sys.stdout.write("wrote %s (%.2fs, %d Hz)\n"
                                 % (path, info["seconds"], info["rate"]))
            else:
                result = voice.speak(text, voice=options["voice"])
                sys.stdout.write("%s (%.2fs)\n" % (result["detail"], result["seconds"]))
        except Exception as exc:
            return _fail("error: %s" % exc)
        return 0

    if sub == "transcribe":
        paths, options = [], {"model": None, "language": None}
        index = 0
        while index < len(rest):
            item = rest[index]
            if item == "--model" and index + 1 < len(rest):
                options["model"] = rest[index + 1]
                index += 2
                continue
            if item == "--language" and index + 1 < len(rest):
                options["language"] = rest[index + 1]
                index += 2
                continue
            paths.append(item)
            index += 1
        if not paths:
            return _fail("usage: silica voice transcribe <file.wav>", 2)
        if not os.path.exists(paths[0]):
            return _fail("error: no such file: %s" % paths[0])
        try:
            result = voice.transcribe(paths[0], model=options["model"],
                                      language=options["language"])
        except Exception as exc:
            return _fail("error: %s" % exc)
        sys.stdout.write("%s\n" % result["text"])
        if result["language"]:
            sys.stdout.write("(%s, %.2f confidence, %.2fs of audio)\n" % (
                result["language"], result["language_probability"], result["seconds"]))
        return 0

    if sub == "info":
        if not rest:
            return _fail("usage: silica voice info <file.wav>", 2)
        from .voice import audio
        try:
            info = audio.describe(rest[0])
        except Exception as exc:
            return _fail("error: %s" % exc)
        for key in ("path", "seconds", "rate", "peak", "rms", "silent"):
            sys.stdout.write("%-8s %s\n" % (key, info[key]))
        return 0

    return _fail("error: unknown voice subcommand '%s'\n\n%s" % (sub, VOICE_USAGE), 2)



# --- Script Mode IDE ---------------------------------------------------------
IDE_USAGE = """usage: silica ide [options]

Starts the Script Mode IDE and prints its URL. The editor runs in a browser; the
runner stays here, on this machine.

  --root DIR    workspace to edit (default: the current directory)
  --port N      port to listen on (default: a free one)
  --host HOST   interface to bind (default: 127.0.0.1)
  --no-open     do not launch a browser
  --quiet       do not log requests

The URL carries a session token. Anyone with the URL can edit and run files in
the workspace, so do not share it, and do not bind to 0.0.0.0 on a network you do
not control.
"""


def cmd_ide(args):
    from .ide import IDEError, serve

    root = "."
    port = 0
    host = "127.0.0.1"
    open_browser = True
    quiet = True
    index = 0
    while index < len(args):
        item = args[index]
        if item in ("-h", "--help", "help"):
            sys.stdout.write(IDE_USAGE)
            return 0
        if item == "--root" and index + 1 < len(args):
            root = args[index + 1]; index += 2; continue
        if item == "--port" and index + 1 < len(args):
            try:
                port = int(args[index + 1])
            except ValueError:
                return _fail("error: --port needs a number", 2)
            index += 2; continue
        if item == "--host" and index + 1 < len(args):
            host = args[index + 1]; index += 2; continue
        if item == "--no-open":
            open_browser = False; index += 1; continue
        if item == "--verbose":
            quiet = False; index += 1; continue
        return _fail("error: unexpected argument '%s'\n\n%s" % (item, IDE_USAGE), 2)

    try:
        server, url = serve(root, port=port, host=host, open_browser=open_browser,
                            quiet=quiet)
    except IDEError as exc:
        return _fail("error: %s" % exc.message)
    except OSError as exc:
        return _fail("error: cannot start the IDE: %s" % exc)

    sys.stdout.write("Silica Script Mode\n\n")
    sys.stdout.write("  workspace : %s\n" % os.path.abspath(root))
    sys.stdout.write("  listening : %s:%d\n" % (host, server.server_address[1]))
    sys.stdout.write("  open      : %s\n\n" % url)
    if host not in ("127.0.0.1", "localhost"):
        sys.stdout.write("  warning: bound to %s — anyone who can reach this port\n"
                         "           and has the URL can edit and run files.\n\n" % host)
    sys.stdout.write("Press Ctrl+C to stop.\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stdout.write("\nstopped\n")
    finally:
        server.server_close()
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
    "voice": cmd_voice,
    "ide": cmd_ide,
}

PLANNED = {
    "new": "project scaffolding (Milestone E)",
    "add": "dependency management (Milestone E)",
    "remove": "dependency management (Milestone E)",
    "install": "dependency management (Milestone E)",
    "build": "project builds with silica.toml (Milestone E)",
}


SOURCE_SUFFIXES = (".sc", ".sbc")


def is_source_path(text):
    """True when an argument names a Silica source or bytecode file.

    Only the two Silica extensions are treated as files, so a mistyped command
    still reports as an unknown command rather than a missing file.
    """
    lowered = text.lower()
    return any(lowered.endswith(suffix) for suffix in SOURCE_SUFFIXES)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        # no arguments: start the interactive interpreter
        return cmd_repl([])
    first = argv[0]
    if first in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    if first in ("-V", "--version", "version"):
        sys.stdout.write("silica %s\n" % VERSION)
        return 0
    if is_source_path(first):
        # `silica file.sc` is the same as `silica run file.sc`, capability flags
        # and all, so there is one implementation of "run a file".
        return cmd_run(argv)
    if first in PLANNED:
        return _fail("error: 'silica %s' is not implemented in 0.8.0 (%s)"
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
