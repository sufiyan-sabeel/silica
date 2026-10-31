"""Recursive-descent parser for Silica.

Grammar summary (full EBNF in docs/GRAMMAR.md):

    program    := { NEWLINE | use | func | let | const }
    func       := 'sfn' IDENT '(' params ')' [ '->' type ] block
    block      := '{' { stmt } [ 'fin' ] '}'
    stmt       := let | const | if | while | for | ret | halt | break
                | continue | expr_stmt
    if         := 'si' expr block [ 'sino' block ]
    while      := 'tant' expr block
    for        := 'per' IDENT 'in' expr block
    ret        := 'ret' [ expr ]
    halt       := 'halt' [ '(' expr ')' ]
    break      := 'break'                       (innermost loop only)
    continue   := 'continue'                    (innermost loop only)

Newlines terminate statements and are skipped inside `(` / `[`.
"""

from . import ast
from .errors import ParseError
from .tokens import BUILTIN_TYPES, Token

_IO_KEYWORDS = {"sprint", "dit", "input"}


def _callee_text(expr):
    """A readable rendering of a call's callee, for diagnostics."""
    callee = getattr(expr, "callee", None)
    if callee is None:
        return "call"
    if isinstance(callee, ast.Ident):
        return callee.name
    if isinstance(callee, ast.Member):
        parts = [callee.name]
        obj = callee.obj
        while isinstance(obj, ast.Member):
            parts.append(obj.name)
            obj = obj.obj
        if isinstance(obj, ast.Ident):
            parts.append(obj.name)
        return ".".join(reversed(parts))
    return "call"

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
        # Type names, collected before parsing so that a type annotation may
        # name a struct or class declared later in the file (including a method
        # naming its own class). A typo like `Integer` is still rejected at parse
        # time, which is what the tests pin down.
        self.struct_names = set()
        for index, token in enumerate(tokens[:-1]):
            if token.kind == "kw" and token.value in ("struct", "class"):
                following = tokens[index + 1]
                if following.kind == "ident":
                    self.struct_names.add(following.value)

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
            result = self.parse_statement()
            if isinstance(result, list):
                stmts.extend(result)
            else:
                stmts.append(result)
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
            if kw == "break":
                return self.parse_break()
            if kw == "continue":
                return self.parse_continue()
            if kw == "struct":
                return self.parse_struct()
            if kw == "class":
                return self.parse_class()
            if kw == "fin":
                self.advance()
                return ast.FinStmt(line=tok.line, col=tok.col)
            if kw == "sino":
                self.error("'sino' without a matching 'si'",
                           hint="'sino' must directly follow an 'si' block")
        if tok.kind == "op" and tok.value == "{":
            self.error("unexpected block")
        # member assignment: `name.field = expr`, at any depth
        if tok.kind == "ident":
            path, offset = [tok.value], 1
            while (self.peek(offset).kind == "op"
                   and self.peek(offset).value == "."
                   and self.peek(offset + 1).kind == "ident"):
                path.append(self.peek(offset + 1).value)
                offset += 2
            if (len(path) > 1 and self.peek(offset).kind == "op"
                    and self.peek(offset).value == "="):
                for _ in range(offset):
                    self.advance()               # name . field ...
                self.advance()                   # =
                value = self.parse_expression()
                self.end_statement()
                return ast.MemberAssignStmt(tok.value, path[1:], value,
                                            line=tok.line, col=tok.col)
        # assignment: `name = expr` (a bare identifier followed by '=')
        if tok.kind == "ident" and self.peek().kind == "op" and self.peek().value == "=":
            self.advance()
            self.advance()
            value = self.parse_expression()
            self.end_statement()
            return ast.AssignStmt(tok.value, value, line=tok.line, col=tok.col)
        expr = self.parse_expression()
        if self.at_op("{"):
            return self.parse_builder(expr, tok)
        if isinstance(expr, ast.Call) and self.cur.kind == "newline":
            save = self.pos
            self.skip_newlines()
            if self.at_op("{"):
                self.error(
                    "the block of a builder must open on the same line as the call",
                    hint="write `%s() { ... }`, not `%s()` followed by a newline"
                         % (_callee_text(expr), _callee_text(expr)))
            self.pos = save
        stmt = ast.ExprStmt(expr, line=tok.line, col=tok.col)
        self.end_statement()
        return stmt

    def parse_builder(self, expr, tok):
        """`call { ... }` — statement position only, head must be a call."""
        if not isinstance(expr, ast.Call):
            self.error("a builder block must follow a call, e.g. `ui.card() { ... }`",
                       hint="only a call can take a block; this expression has no "
                            "widget to attach the block to")
        block = self.parse_block()
        return ast.BuilderStmt(expr, block, line=tok.line, col=tok.col)

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

    def parse_struct(self):
        tok = self.advance()  # struct
        name_tok = self.expect_ident("struct name")
        self.skip_newlines()
        self.expect_op("{", "a struct body is required")
        fields = []
        seen = set()
        self.skip_newlines()
        while not self.at_op("}"):
            field_tok = self.expect_ident("field name")
            if field_tok.value in seen:
                self.error("duplicate field '%s' in struct '%s'"
                           % (field_tok.value, name_tok.value),
                           hint="each field name may appear once")
            seen.add(field_tok.value)
            self.expect_op(":", "a struct field needs a type, e.g. 'x: Int'")
            ftype = self.parse_type()
            fields.append((field_tok.value, ftype, field_tok.line, field_tok.col,
                           False))
            self.end_statement()
        self.expect_op("}")
        if not fields:
            self.error("struct '%s' has no fields" % name_tok.value,
                       hint="an empty struct cannot hold anything; add a field")
        self.struct_names.add(name_tok.value)
        return ast.StructDecl(name_tok.value, fields,
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

    def parse_class(self):
        """`class Name { fields... [private] [static] sfn methods... }`."""
        tok = self.advance()                      # class
        name_tok = self.expect_ident("class name")
        self.struct_names.add(name_tok.value)
        self.skip_newlines()
        self.expect_op("{", "a class body is required")
        fields, methods = [], []
        seen = set()
        self.skip_newlines()
        while not self.at_op("}"):
            if self.cur.kind == "eof":
                self.error("unexpected end of file: missing '}'",
                           hint="class %s is never closed" % name_tok.value)
            is_private = False
            if self.at_kw("private"):
                is_private = True
                self.advance()
            if self.at_kw("sfn") or self.at_kw("static"):
                methods.append(self.parse_method(is_private))
                self.skip_newlines()
                continue
            field_tok = self.expect_ident("field name")
            if field_tok.value in seen:
                self.error("duplicate field '%s' in class '%s'"
                           % (field_tok.value, name_tok.value),
                           hint="each field name may appear once")
            seen.add(field_tok.value)
            self.expect_op(":", "a class field needs a type, e.g. 'value: Int'")
            ftype = self.parse_type()
            fields.append((field_tok.value, ftype, field_tok.line, field_tok.col,
                           is_private))
            self.end_statement()
            self.skip_newlines()
        self.expect_op("}")
        return ast.ClassDecl(name_tok.value, fields, methods,
                             line=tok.line, col=tok.col)

    def parse_method(self, is_private=False):
        tok = self.cur
        is_static = False
        if self.at_kw("static"):
            is_static = True
            self.advance()
        decl = self.parse_function()
        decl.is_static = is_static
        decl.is_private = is_private
        decl.line = tok.line
        decl.col = tok.col
        return decl

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

    def parse_break(self):
        tok = self.advance()  # break
        self.end_statement()
        return ast.BreakStmt(line=tok.line, col=tok.col)

    def parse_continue(self):
        tok = self.advance()  # continue
        self.end_statement()
        return ast.ContinueStmt(line=tok.line, col=tok.col)

    def parse_use(self):
        tok = self.advance()  # use
        mod = self.expect_ident("module name")
        parts = [mod.value]
        while self.at_op("."):
            self.advance()
            parts.append(self.expect_ident("module name").value)
        self.end_statement()
        return ast.UseStmt(".".join(parts), line=tok.line, col=tok.col)

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
            result = self.parse_statement()
            if isinstance(result, list):
                stmts.extend(result)
            else:
                stmts.append(result)
            self.skip_newlines()
        self.advance()  # }
        return ast.Block(stmts, line=start.line, col=start.col)

    def parse_type(self):
        tok = self.cur
        if tok.kind != "ident":
            self.error("expected a type name but found %s" % tok.describe())
        if tok.value not in BUILTIN_TYPES and tok.value not in self.struct_names:
            self.error("unknown type '%s'" % tok.value, tok,
                       hint="available types: %s"
                            % ", ".join(sorted(set(BUILTIN_TYPES)
                                               | self.struct_names)))
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
                named = []
                if not self.at_op(")"):
                    while True:
                        # `name: value` inside an argument list is a named field
                        if (self.cur.kind == "ident"
                                and self.peek().kind == "op"
                                and self.peek().value == ":"):
                            field = self.advance()
                            self.advance()  # :
                            named.append((field.value, self.parse_expression(),
                                          field.line, field.col))
                        else:
                            if named:
                                self.error(
                                    "positional arguments cannot follow named ones",
                                    hint="put every positional argument first")
                            args.append(self.parse_expression())
                        if self.at_op(","):
                            self.advance()
                            continue
                        break
                self.expect_op(")", "unbalanced argument list")
                is_struct = (isinstance(expr, ast.Ident)
                             and (expr.name in self.struct_names or named))
                if is_struct:
                    positional = [(None, a, getattr(a, "line", tok.line),
                                   getattr(a, "col", tok.col)) for a in args]
                    expr = ast.StructLit(expr.name, positional + named,
                                         line=tok.line, col=tok.col)
                else:
                    expr = ast.Call(expr, args, named=named,
                                    line=tok.line, col=tok.col)
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
