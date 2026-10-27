"""Recursive-descent parser for Silica.

Grammar summary (full EBNF in docs/GRAMMAR.md):

    program    := { NEWLINE | use | func | let | const }
    func       := 'sfn' IDENT '(' params ')' [ '->' type ] block
    block      := '{' { stmt } [ 'fin' ] '}'
    stmt       := let | const | if | while | for | ret | halt | expr_stmt
    if         := 'si' expr block [ 'sino' block ]
    while      := 'tant' expr block
    for        := 'per' IDENT 'in' expr block
    ret        := 'ret' [ expr ]
    halt       := 'halt' [ '(' expr ')' ]

Newlines terminate statements and are skipped inside `(` / `[`.
"""

from . import ast
from .errors import ParseError
from .tokens import BUILTIN_TYPES, Token

_IO_KEYWORDS = {"sprint", "dit", "input"}

# binary operator precedence, lowest first
_BINARY_LEVELS = [
    {"ou"},
    {"und"},
    {"==", "!="},
    {"<", "<=", ">", ">="},
    {"+", "-"},
    {"*", "/", "%"},
]


class Parser:
    def __init__(self, tokens, filename="<source>"):
        self.tokens = tokens
        self.filename = filename
        self.pos = 0

    # -- token helpers -------------------------------------------------------
    @property
    def cur(self):
        return self.tokens[self.pos]

    def peek(self, k=1):
        j = self.pos + k
        return self.tokens[j] if j < len(self.tokens) else self.tokens[-1]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def error(self, message, tok=None, hint=None):
        tok = tok or self.cur
        raise ParseError(message, tok.line, tok.col, self.filename, hint)

    def at_op(self, value):
        return self.cur.kind == "op" and self.cur.value == value

    def at_kw(self, value):
        return self.cur.kind == "kw" and self.cur.value == value

    def expect_op(self, value, hint=None):
        if not self.at_op(value):
            self.error("expected '%s' but found %s" % (value, self.cur.describe()), hint=hint)
        return self.advance()

    def expect_kw(self, value, hint=None):
        if not self.at_kw(value):
            self.error("expected '%s' but found %s" % (value, self.cur.describe()), hint=hint)
        return self.advance()

    def expect_ident(self, what="identifier"):
        if self.cur.kind != "ident":
            hint = None
            if self.cur.kind == "kw":
                hint = "'%s' is a reserved Silica keyword" % self.cur.value
            self.error("expected %s but found %s" % (what, self.cur.describe()), hint=hint)
        return self.advance()

    def skip_newlines(self):
        while self.cur.kind == "newline":
            self.advance()

    def end_statement(self):
        if self.cur.kind == "newline":
            self.skip_newlines()
            return
        if self.at_op("}"):
            return
        if self.at_op(";"):
            self.advance()
            self.skip_newlines()
            return
        if self.cur.kind == "eof":
            return
        self.error("unexpected %s after statement" % self.cur.describe(),
                   hint="each statement must be on its own line")

    # -- program -------------------------------------------------------------
    def parse_program(self):
        stmts = []
        self.skip_newlines()
        while self.cur.kind != "eof":
            stmts.append(self.parse_statement())
            self.skip_newlines()
        return ast.Program(stmts, line=1, col=1)

    # -- statements ----------------------------------------------------------
    def parse_statement(self):
        tok = self.cur
        if tok.kind == "kw":
            kw = tok.value
            if kw in ("let", "const"):
                return self.parse_let()
            if kw == "sfn":
                return self.parse_function()
            if kw == "si":
                return self.parse_if()
            if kw == "tant":
                return self.parse_while()
            if kw == "per":
                return self.parse_for()
            if kw == "ret":
                return self.parse_return()
            if kw == "use":
                return self.parse_use()
            if kw == "halt":
                return self.parse_halt()
            if kw == "fin":
                self.advance()
                return ast.FinStmt(line=tok.line, col=tok.col)
            if kw == "sino":
                self.error("'sino' without a matching 'si'",
                           hint="'sino' must directly follow an 'si' block")
        if tok.kind == "op" and tok.value == "{":
            self.error("unexpected block")
        # assignment: `name = expr` (a bare identifier followed by '=')
        if tok.kind == "ident" and self.peek().kind == "op" and self.peek().value == "=":
            self.advance()
            self.advance()
            value = self.parse_expression()
            self.end_statement()
            return ast.AssignStmt(tok.value, value, line=tok.line, col=tok.col)
        expr = self.parse_expression()
        stmt = ast.ExprStmt(expr, line=tok.line, col=tok.col)
        self.end_statement()
        return stmt

    def parse_let(self):
        tok = self.advance()  # let / const
        is_const = tok.value == "const"
        name_tok = self.expect_ident("variable name")
        type_ann = None
        if self.at_op(":"):
            self.advance()
            type_ann = self.parse_type()
        if not self.at_op("="):
            self.error("expected '=' after variable name",
                       hint="Silica has no uninitialised bindings")
        self.advance()
        init = self.parse_expression()
        self.end_statement()
        return ast.LetStmt(name_tok.value, type_ann, init, is_const,
                           line=tok.line, col=tok.col)

    def parse_function(self):
        tok = self.advance()  # sfn
        name_tok = self.expect_ident("function name")
        self.expect_op("(", "function parameters are required, use '()' for none")
        params = []
        if not self.at_op(")"):
            while True:
                p = self.expect_ident("parameter name")
                ptype = None
                if self.at_op(":"):
                    self.advance()
                    ptype = self.parse_type()
                params.append((p.value, ptype, p.line, p.col))
                if self.at_op(","):
                    self.advance()
                    continue
                break
        self.expect_op(")")
        ret_type = None
        if self.at_op("->"):
            self.advance()
            ret_type = self.parse_type()
        self.skip_newlines()
        body = self.parse_block()
        return ast.FuncDecl(name_tok.value, params, ret_type, body,
                            line=tok.line, col=tok.col)

    def parse_if(self):
        tok = self.advance()  # si
        cond = self.parse_expression()
        self.skip_newlines()
        then_block = self.parse_block()
        else_block = None
        save = self.pos
        self.skip_newlines()
        if self.at_kw("sino"):
            self.advance()
            self.skip_newlines()
            else_block = self.parse_block()
        else:
            self.pos = save
        return ast.IfStmt(cond, then_block, else_block, line=tok.line, col=tok.col)

    def parse_while(self):
        tok = self.advance()  # tant
        cond = self.parse_expression()
        self.skip_newlines()
        body = self.parse_block()
        return ast.WhileStmt(cond, body, line=tok.line, col=tok.col)

    def parse_for(self):
        tok = self.advance()  # per
        var_tok = self.expect_ident("loop variable name")
        if not self.at_kw("in"):
            self.error("expected 'in' after loop variable",
                       hint="the form is: per item in collection { ... }")
        self.advance()
        iterable = self.parse_expression()
        self.skip_newlines()
        body = self.parse_block()
        return ast.ForStmt(var_tok.value, iterable, body, line=tok.line, col=tok.col)

    def parse_return(self):
        tok = self.advance()  # ret
        value = None
        if self.cur.kind not in ("newline", "eof") and not self.at_op("}"):
            value = self.parse_expression()
        self.end_statement()
        return ast.ReturnStmt(value, line=tok.line, col=tok.col)

    def parse_use(self):
        tok = self.advance()  # use
        mod = self.expect_ident("module name")
        self.end_statement()
        return ast.UseStmt(mod.value, line=tok.line, col=tok.col)

    def parse_halt(self):
        tok = self.advance()  # halt
        code = None
        if self.at_op("("):
            self.advance()
            code = self.parse_expression()
            self.expect_op(")")
        self.end_statement()
        return ast.HaltStmt(code, line=tok.line, col=tok.col)

    def parse_block(self):
        start = self.expect_op("{")
        stmts = []
        self.skip_newlines()
        while not self.at_op("}"):
            if self.cur.kind == "eof":
                self.error("unexpected end of file: missing '}'",
                           hint="a block opened at line %d is never closed" % start.line)
            if self.at_kw("fin"):
                fin = self.advance()
                stmts.append(ast.FinStmt(line=fin.line, col=fin.col))
                self.skip_newlines()
                if not self.at_op("}"):
                    self.error("'fin' must be the last element of a block",
                               fin, hint="put 'fin' immediately before the closing '}'")
                continue
            stmts.append(self.parse_statement())
            self.skip_newlines()
        self.advance()  # }
        return ast.Block(stmts, line=start.line, col=start.col)

    def parse_type(self):
        tok = self.cur
        if tok.kind != "ident":
            self.error("expected a type name but found %s" % tok.describe())
        if tok.value not in BUILTIN_TYPES:
            self.error("unknown type '%s'" % tok.value, tok,
                       hint="available types: Int, Float, Bool, String, Unit, List, Map, Any")
        self.advance()
        return tok.value

    # -- expressions ---------------------------------------------------------
    def parse_expression(self):
        return self._parse_binary(0)

    def _parse_binary(self, level):
        if level >= len(_BINARY_LEVELS):
            return self.parse_unary()
        ops = _BINARY_LEVELS[level]
        left = self._parse_binary(level + 1)
        while True:
            tok = self.cur
            op = tok.value if tok.kind in ("op", "kw") else None
            if op not in ops:
                return left
            self.advance()
            right = self._parse_binary(level + 1)
            left = ast.Binary(op, left, right, line=tok.line, col=tok.col)

    def parse_unary(self):
        tok = self.cur
        if tok.kind == "kw" and tok.value == "non":
            self.advance()
            return ast.Unary("non", self.parse_unary(), line=tok.line, col=tok.col)
        if tok.kind == "op" and tok.value == "-":
            self.advance()
            return ast.Unary("-", self.parse_unary(), line=tok.line, col=tok.col)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            tok = self.cur
            if tok.kind == "op" and tok.value == "(":
                self.advance()
                args = []
                if not self.at_op(")"):
                    while True:
                        args.append(self.parse_expression())
                        if self.at_op(","):
                            self.advance()
                            continue
                        break
                self.expect_op(")", "unbalanced argument list")
                expr = ast.Call(expr, args, line=tok.line, col=tok.col)
            elif tok.kind == "op" and tok.value == "[":
                self.advance()
                index = self.parse_expression()
                self.expect_op("]")
                expr = ast.Index(expr, index, line=tok.line, col=tok.col)
            elif tok.kind == "op" and tok.value == ".":
                self.advance()
                name = self.expect_ident("member name")
                expr = ast.Member(expr, name.value, line=tok.line, col=tok.col)
            else:
                return expr

    def parse_primary(self):
        tok = self.cur
        if tok.kind == "int":
            self.advance()
            return ast.IntLit(tok.value, line=tok.line, col=tok.col)
        if tok.kind == "float":
            self.advance()
            return ast.FloatLit(tok.value, line=tok.line, col=tok.col)
        if tok.kind == "string":
            self.advance()
            return ast.StringLit(tok.value, line=tok.line, col=tok.col)
        if tok.kind == "kw" and tok.value in ("oui", "nein"):
            self.advance()
            return ast.BoolLit(tok.value == "oui", line=tok.line, col=tok.col)
        if tok.kind == "kw" and tok.value in _IO_KEYWORDS:
            self.advance()
            return ast.Ident(tok.value, line=tok.line, col=tok.col)
        if tok.kind == "ident":
            self.advance()
            return ast.Ident(tok.value, line=tok.line, col=tok.col)
        if tok.kind == "op" and tok.value == "(":
            self.advance()
            inner = self.parse_expression()
            self.expect_op(")", "unbalanced parenthesis")
            return inner
        if tok.kind == "op" and tok.value == "[":
            self.advance()
            items = []
            if not self.at_op("]"):
                while True:
                    items.append(self.parse_expression())
                    if self.at_op(","):
                        self.advance()
                        continue
                    break
            self.expect_op("]", "unbalanced list literal")
            return ast.ListLit(items, line=tok.line, col=tok.col)
        if tok.kind == "op" and tok.value == "{":
            self.advance()
            pairs = []
            if not self.at_op("}"):
                while True:
                    key_tok = self.cur
                    if key_tok.kind == "string":
                        self.advance()
                        key = ast.StringLit(key_tok.value, line=key_tok.line, col=key_tok.col)
                    elif key_tok.kind == "ident":
                        self.advance()
                        key = ast.StringLit(key_tok.value, line=key_tok.line, col=key_tok.col)
                    else:
                        self.error("map keys must be strings or bare identifiers")
                    self.expect_op(":", "map entries use 'key: value'")
                    value = self.parse_expression()
                    pairs.append((key, value))
                    if self.at_op(","):
                        self.advance()
                        continue
                    break
            self.expect_op("}", "unbalanced map literal")
            return ast.MapLit(pairs, line=tok.line, col=tok.col)
        if tok.kind == "newline":
            self.error("unexpected end of line in expression",
                       hint="wrap long expressions in parentheses")
        self.error("unexpected %s in expression" % tok.describe())


def parse(tokens, filename="<source>"):
    return Parser(tokens, filename).parse_program()


def parse_source(source, filename="<source>"):
    """Convenience: tokenize + parse in one step."""
    from .lexer import tokenize
    tokens, comments = tokenize(source, filename)
    return parse(tokens, filename), comments
