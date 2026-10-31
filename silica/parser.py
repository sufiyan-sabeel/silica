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
            if kw == "struct":
                return self.parse_struct()
            if kw == "class":
                return self.parse_class()
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
            if kw == "fin":
                self.advance()
                return ast.FinStmt(line=tok.line, col=tok.col)
            if kw == "sino":
                self.error("'sino' without a matching 'si'",
                           hint="'sino' must directly follow an 'si' block")
        if tok.kind == "op" and tok.value == "{":
            self.error("unexpected block")
        # assignment: `name = expr` or `obj.field = expr`. The target is parsed
        # as an ordinary postfix expression, so the same rule covers both.
        if tok.kind == "ident" and self.peek().kind == "op" and self.peek().value == "=":
            self.advance()
            self.advance()
            value = self.parse_expression()
            self.end_statement()
            return ast.AssignStmt(tok.value, value, line=tok.line, col=tok.col)
        expr = self.parse_expression()
        if self.at_op("="):
            self.advance()
            value = self.parse_expression()
            self.end_statement()
            if isinstance(expr, ast.Ident):
                return ast.AssignStmt(expr.name, value, line=tok.line, col=tok.col)
            if isinstance(expr, ast.Member):
                return ast.AssignStmt("", value, target=expr,
                                      line=tok.line, col=tok.col)
            self.error("cannot assign to this expression", tok,
                       hint="only a variable or a field can be assigned")
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

    def parse_function(self):
        tok = self.advance()  # sfn
        name_tok = self.expect_ident("function name")
        type_params = self.parse_type_params()
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
                            type_params=type_params, line=tok.line, col=tok.col)

    def parse_struct(self):
        tok = self.advance()                     # struct
        name = self.expect_ident("struct name")
        type_params = self.parse_type_params()
        self.expect_op("{", "a struct body needs braces")
        fields = []
        self.skip_newlines()
        while not self.at_op("}"):
            if self.cur.kind == "eof":
                self.error("unexpected end of file: missing '}'",
                           hint="struct %s is never closed" % name.value)
            if self.at_kw("private"):
                self.error("a struct field cannot be private", self.peek(),
                           hint="structs have no methods, so nothing could read it; "
                                "use a class")
            if self.at_kw("sfn") or self.at_kw("static"):
                self.error("struct %s cannot declare methods" % name.value,
                           hint="use a class if you need behaviour")
            fields.append(self.parse_field())
            self.skip_newlines()
        self.advance()                           # }
        return ast.StructDecl(name.value, fields, type_params=type_params,
                              line=tok.line, col=tok.col)

    def parse_class(self):
        tok = self.advance()                     # class
        name = self.expect_ident("class name")
        type_params = self.parse_type_params()
        self.expect_op("{", "a class body needs braces")
        fields, methods = [], []
        self.skip_newlines()
        while not self.at_op("}"):
            if self.cur.kind == "eof":
                self.error("unexpected end of file: missing '}'",
                           hint="class %s is never closed" % name.value)
            private = False
            if self.at_kw("private"):
                private = True
                self.advance()
            if self.at_kw("sfn") or self.at_kw("static"):
                methods.append(self.parse_method(private))
            else:
                fields.append(self.parse_field(private))
            self.skip_newlines()
        self.advance()                           # }
        return ast.ClassDecl(name.value, fields, methods, type_params=type_params,
                             line=tok.line, col=tok.col)

    def parse_field(self, is_private=False):
        """`name: Type` — a field declaration, not a binding."""
        tok = self.cur
        name = self.expect_ident("field name")
        if not self.at_op(":"):
            self.error("expected ':' after field name '%s'" % name.value,
                       hint="a field is declared as `name: Type`")
        self.advance()
        type_ann = self.parse_type()
        self.end_statement()
        return ast.FieldDecl(name.value, type_ann, is_private,
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

    def parse_type_params(self):
        """`<T>`, `<T: Orderable>`, `<K, V>` — type parameters of a declaration."""
        params = []
        if not self.at_op("<"):
            return params
        self.advance()
        while True:
            tok = self.expect_ident("type parameter")
            constraint = None
            if self.at_op(":"):
                self.advance()
                constraint = self.expect_ident("constraint name").value
            params.append((tok.value, constraint, tok.line, tok.col))
            if self.at_op(","):
                self.advance()
                continue
            break
        self.expect_op(">", "unbalanced type parameter list")
        return params

    def parse_type(self):
        """Any identifier is accepted here; the checker resolves it.

        The parser cannot know the program's struct and class names yet (they may
        be declared later in the file), so an unknown type is a *type* error with
        a suggestion, not a syntax error.
        """
        tok = self.cur
        if tok.kind != "ident":
            self.error("expected a type name but found %s" % tok.describe())
        self.advance()
        name = tok.value
        if not self.at_op("<"):
            return name
        self.advance()
        arguments = [self.parse_type()]
        while self.at_op(","):
            self.advance()
            arguments.append(self.parse_type())
        self.expect_op(">", "unbalanced type arguments")
        return "%s<%s>" % (name, ", ".join(arguments))

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
