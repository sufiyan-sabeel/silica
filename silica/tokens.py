"""Token definitions and the Silica keyword table."""

# --- Silica keyword vocabulary -------------------------------------------------
# These are the only reserved words in Silica v0.7.0. They may not be used as
# identifiers. See docs/LANGUAGE_SPEC.md for the meaning of each one.
KEYWORDS = {
    # core I/O
    "sprint",   # print a value followed by a newline
    "dit",      # write a value to stdout with no trailing newline
    "input",    # read one line of stdin as String
    # booleans
    "oui",      # true
    "nein",     # false
    # logic
    "und",      # logical AND (short-circuit)
    "ou",       # logical OR  (short-circuit)
    "non",      # logical NOT
    # control flow
    "si",       # if
    "sino",     # else
    "tant",     # while
    "per",      # for ... in ...
    "in",       # part of `per name in expr`
    "fin",      # optional explicit end-of-block marker
    "halt",     # terminate the program
    # declarations
    "sfn",      # function declaration
    "ret",      # return
    "use",      # import a standard-library module
    "let",      # mutable binding
    "const",    # immutable binding
}

# Keywords that introduce a statement at the start of a line.
STATEMENT_KEYWORDS = {
    "sprint", "dit", "input", "si", "sino", "tant", "per", "sfn", "ret",
    "use", "let", "const", "halt", "fin",
}

BUILTIN_TYPES = {"Int", "Float", "Bool", "String", "Unit", "List", "Map", "Any"}

# Multi-character operators must be tested before single-character ones.
OPERATORS_2 = ["==", "!=", "<=", ">=", "->"]
OPERATORS_1 = list("+-*/%=<>(){}[],:.;")

TOKEN_KINDS = ("int", "float", "string", "ident", "kw", "op", "newline", "eof")


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return "Token(%s, %r, %d:%d)" % (self.kind, self.value, self.line, self.col)

    def is_op(self, value):
        return self.kind == "op" and self.value == value

    def is_kw(self, value):
        return self.kind == "kw" and self.value == value

    def describe(self):
        if self.kind == "newline":
            return "end of line"
        if self.kind == "eof":
            return "end of file"
        if self.kind == "string":
            return "string literal"
        return "%r" % (self.value,)
