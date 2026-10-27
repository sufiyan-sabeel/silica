"""The Silica lexer: source text -> tokens with line/column locations.

Newlines are significant: they terminate statements (like Go). Newlines inside
`(` or `[` are ignored so multi-line argument lists and literals are allowed.
Comments (`#` or `//`) run to the end of the line and are recorded so that
`silica fmt` can refuse to rewrite a file it would strip comments from.
"""

from .errors import LexError
from .tokens import KEYWORDS, OPERATORS_1, OPERATORS_2, Token

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
}


class Lexer:
    def __init__(self, source, filename="<source>"):
        self.src = source
        self.filename = filename
        self.i = 0
        self.line = 1
        self.col = 1
        self.tokens = []
        self.comments = []
        self.depth = 0  # nesting of ( and [ ; newlines are suppressed inside

    # -- character helpers ---------------------------------------------------
    def _peek(self, k=0):
        j = self.i + k
        return self.src[j] if j < len(self.src) else ""

    def _advance(self):
        ch = self.src[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _error(self, message, line=None, col=None, hint=None):
        raise LexError(message, line if line is not None else self.line,
                       col if col is not None else self.col,
                       self.filename, hint)

    def _emit(self, kind, value, line, col):
        self.tokens.append(Token(kind, value, line, col))

    # -- main loop -----------------------------------------------------------
    def tokenize(self):
        while self.i < len(self.src):
            ch = self._peek()

            if ch in " \t\r":
                self._advance()
                continue

            # comments
            if ch == "#" or (ch == "/" and self._peek(1) == "/"):
                start = self.i
                while self.i < len(self.src) and self._peek() != "\n":
                    self._advance()
                self.comments.append(self.src[start:self.i])
                continue

            if ch == "\n":
                line, col = self.line, self.col
                self._advance()
                if self.depth == 0:
                    self._emit("newline", "\n", line, col)
                continue

            line, col = self.line, self.col

            if ch.isdigit():
                self._number(line, col)
                continue

            if ch == '"':
                self._string(line, col)
                continue

            if ch.isalpha() or ch == "_":
                self._identifier(line, col)
                continue

            two = self.src[self.i:self.i + 2]
            if two in OPERATORS_2:
                self._advance()
                self._advance()
                self._emit("op", two, line, col)
                continue

            if ch in OPERATORS_1:
                self._advance()
                if ch in "([":
                    self.depth += 1
                elif ch in ")]":
                    self.depth = max(0, self.depth - 1)
                self._emit("op", ch, line, col)
                continue

            if ch == "'":
                self._error("single quotes are not string delimiters in Silica",
                            line, col, 'use double quotes, e.g. sprint("hi")')

            self._error("unexpected character %r" % ch, line, col)

        self.tokens.append(Token("eof", "", self.line, self.col))
        return self.tokens

    # -- literal scanners ----------------------------------------------------
    def _number(self, line, col):
        start = self.i
        is_float = False
        while self._peek().isdigit():
            self._advance()
        if self._peek() == "." and self._peek(1).isdigit():
            is_float = True
            self._advance()
            while self._peek().isdigit():
                self._advance()
        if self._peek() in ("e", "E"):
            save = self.i
            is_float = True
            self._advance()
            if self._peek() in ("+", "-"):
                self._advance()
            if not self._peek().isdigit():
                self.i = save
                self._error("malformed exponent in number literal", line, col)
            while self._peek().isdigit():
                self._advance()
        text = self.src[start:self.i]
        if self._peek().isalpha() or self._peek() == "_":
            self._error("malformed number literal %r" % (text + self._peek()), line, col)
        if is_float:
            self._emit("float", float(text), line, col)
        else:
            self._emit("int", int(text), line, col)

    def _string(self, line, col):
        self._advance()  # opening quote
        out = []
        while True:
            if self.i >= len(self.src):
                self._error("unterminated string literal", line, col)
            ch = self._peek()
            if ch == "\n":
                self._error("unterminated string literal (newline in string)", line, col,
                            'use \\n inside the string for a line break')
            if ch == '"':
                self._advance()
                break
            if ch == "\\":
                self._advance()
                esc = self._peek()
                if esc in _ESCAPES:
                    out.append(_ESCAPES[esc])
                    self._advance()
                    continue
                if esc == "u":
                    self._advance()
                    hexdigits = self.src[self.i:self.i + 4]
                    if len(hexdigits) != 4 or any(c not in "0123456789abcdefABCDEF" for c in hexdigits):
                        self._error("invalid \\u escape: expected 4 hex digits", self.line, self.col)
                    out.append(chr(int(hexdigits, 16)))
                    for _ in range(4):
                        self._advance()
                    continue
                self._error("unknown escape sequence \\%s" % esc, self.line, self.col,
                            "valid escapes: \\n \\t \\r \\0 \\\\ \\\" \\uXXXX")
            out.append(ch)
            self._advance()
        self._emit("string", "".join(out), line, col)

    def _identifier(self, line, col):
        start = self.i
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()
        text = self.src[start:self.i]
        if text in KEYWORDS:
            self._emit("kw", text, line, col)
        else:
            self._emit("ident", text, line, col)


def tokenize(source, filename="<source>"):
    """Tokenize `source`; returns (tokens, comments)."""
    lexer = Lexer(source, filename)
    tokens = lexer.tokenize()
    return tokens, lexer.comments
