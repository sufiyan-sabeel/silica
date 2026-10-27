"""Error types for the Silica toolchain.

Every stage of the pipeline raises a subclass of SilicaError so the CLI can
print a uniform, location-aware diagnostic:

    main.sc:3:11: type error: cannot assign Float to Int
      hint: add a conversion with int(...)
"""


class SilicaError(Exception):
    kind = "error"

    def __init__(self, message, line=0, col=0, filename=None, hint=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.filename = filename
        self.hint = hint

    def with_file(self, filename):
        if self.filename is None:
            self.filename = filename
        return self

    def format(self):
        loc = ""
        if self.filename:
            loc = str(self.filename)
        if self.line:
            if self.col:
                loc += ":%d:%d" % (self.line, self.col)
            else:
                loc += ":%d" % self.line
        if loc:
            loc += ": "
        out = "%s%s: %s" % (loc, self.kind, self.message)
        if self.hint:
            out += "\n  hint: %s" % self.hint
        return out


class LexError(SilicaError):
    kind = "lex error"


class ParseError(SilicaError):
    kind = "parse error"


class SilicaTypeError(SilicaError):
    kind = "type error"


class CompileError(SilicaError):
    kind = "compile error"


class VerifyError(SilicaError):
    kind = "bytecode error"


class SilicaRuntimeError(SilicaError):
    kind = "runtime error"
