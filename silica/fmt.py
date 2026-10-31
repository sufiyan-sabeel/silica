"""Canonical source formatter for Silica (`silica fmt`).

The formatter reprints the AST with a single style: four-space indentation,
one statement per line, `name: Type` annotations kept, and parentheses only
where precedence requires them. Because it works from the AST, a file that
contains comments is refused rather than silently stripped — see
`format_source`.
"""

from . import ast
from .errors import SilicaError

INDENT = "    "

PREC = {
    "ou": 1,
    "und": 2,
    "==": 3, "!=": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}
UNARY_PREC = 7
POSTFIX_PREC = 8
PRIMARY_PREC = 9


class Printer:
    def __init__(self):
        self.lines = []
        self.depth = 0

    def write(self, text):
        self.lines.append(INDENT * self.depth + text)

    def block_lines(self, block, trailing_fin=False):
        self.write("{")
        self.depth += 1
        if not block.stmts:
            self.lines.append("")
        for stmt in block.stmts:
            self.stmt(stmt)
        self.depth -= 1
        self.write("}")

    # -- statements ----------------------------------------------------------
    def type_params(self, node):
        params = getattr(node, "type_params", None)
        if not params:
            return ""
        rendered = [name if constraint is None else "%s: %s" % (name, constraint)
                    for name, constraint, *_rest in params]
        return "<%s>" % ", ".join(rendered)

    def stmt(self, node):
        if isinstance(node, ast.LetStmt):
            keyword = "const" if node.is_const else "let"
            ann = ": %s" % node.type_ann if node.type_ann else ""
            self.write("%s %s%s = %s" % (keyword, node.name, ann,
                                         self.expr(node.init, 0)))
        elif isinstance(node, ast.AssignStmt):
            self.write("%s = %s" % (node.name, self.expr(node.value, 0)))
        elif isinstance(node, ast.ExprStmt):
            self.write(self.expr(node.expr, 0))
        elif isinstance(node, ast.IfStmt):
            self.write("si %s {" % self.expr(node.cond, 0))
            self.depth += 1
            for inner in node.then_block.stmts:
                self.stmt(inner)
            self.depth -= 1
            if node.else_block is not None:
                self.write("} sino {")
                self.depth += 1
                for inner in node.else_block.stmts:
                    self.stmt(inner)
                self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.WhileStmt):
            self.write("tant %s {" % self.expr(node.cond, 0))
            self.depth += 1
            for inner in node.body.stmts:
                self.stmt(inner)
            self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.ForStmt):
            self.write("per %s in %s {" % (node.var, self.expr(node.iterable, 0)))
            self.depth += 1
            for inner in node.body.stmts:
                self.stmt(inner)
            self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.BuilderStmt):
            self.write("%s {" % self.expr(node.call, 0))
            self.depth += 1
            for inner in node.block.stmts:
                self.stmt(inner)
            self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.FuncDecl):
            params = ", ".join(
                (name if ptype is None else "%s: %s" % (name, ptype))
                for name, ptype, _line, _col in node.params)
            ret = " -> %s" % node.ret_type if node.ret_type else ""
            self.write("sfn %s%s(%s)%s {" % (node.name, self.type_params(node),
                                             params, ret))
            self.depth += 1
            for inner in node.body.stmts:
                self.stmt(inner)
            self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.ReturnStmt):
            if node.value is None:
                self.write("ret")
            else:
                self.write("ret %s" % self.expr(node.value, 0))
        elif isinstance(node, ast.UseStmt):
            self.write("use %s" % node.module)
        elif isinstance(node, ast.HaltStmt):
            if node.code is None:
                self.write("halt")
            else:
                self.write("halt(%s)" % self.expr(node.code, 0))
        elif isinstance(node, ast.BreakStmt):
            self.write("break")
        elif isinstance(node, ast.ContinueStmt):
            self.write("continue")
        elif isinstance(node, ast.StructDecl):
            self.write("struct %s%s {" % (node.name, self.type_params(node)))
            self.depth += 1
            for name, ftype, _line, _col, is_private in node.fields:
                self.write("%s%s: %s" % ("private " if is_private else "", name, ftype))
            self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.ClassDecl):
            self.write("class %s%s {" % (node.name, self.type_params(node)))
            self.depth += 1
            for name, ftype, _line, _col, is_private in node.fields:
                self.write("%s%s: %s" % ("private " if is_private else "", name, ftype))
            for method in node.methods:
                self.method(method)
            self.depth -= 1
            self.write("}")
        elif isinstance(node, ast.MemberAssignStmt):
            self.write("%s.%s = %s"
                       % (node.target, ".".join(node.path),
                          self.expr(node.value, 0)))
        elif isinstance(node, ast.FinStmt):
            self.write("fin")
        else:  # pragma: no cover
            raise SilicaError("cannot format statement %r" % (node,))

    def method(self, node):
        prefix = ("private " if getattr(node, "is_private", False) else "") + \
                 ("static " if getattr(node, "is_static", False) else "")
        params = ", ".join(
            (name if ptype is None else "%s: %s" % (name, ptype))
            for name, ptype, _line, _col in node.params)
        ret = " -> %s" % node.ret_type if node.ret_type else ""
        self.write("%ssfn %s%s(%s)%s {" % (prefix, node.name,
                                           self.type_params(node), params, ret))
        self.depth += 1
        for inner in node.body.stmts:
            self.stmt(inner)
        self.depth -= 1
        self.write("}")

    # -- expressions ---------------------------------------------------------
    def expr(self, node, parent_prec, is_right=False):
        text, prec = self.expr_parts(node)
        if prec < parent_prec or (prec == parent_prec and is_right and prec in (5, 6)):
            return "(" + text + ")"
        return text

    def expr_parts(self, node):
        if isinstance(node, ast.IntLit):
            return str(node.value), PRIMARY_PREC
        if isinstance(node, ast.FloatLit):
            return repr(node.value), PRIMARY_PREC
        if isinstance(node, ast.StringLit):
            return '"' + _escape(node.value) + '"', PRIMARY_PREC
        if isinstance(node, ast.BoolLit):
            return ("oui" if node.value else "nein"), PRIMARY_PREC
        if isinstance(node, ast.Ident):
            return node.name, PRIMARY_PREC
        if isinstance(node, ast.Unary):
            operand = self.expr(node.operand, UNARY_PREC)
            if node.op == "-":
                return "-" + operand, UNARY_PREC
            return "non " + operand, UNARY_PREC
        if isinstance(node, ast.Binary):
            prec = PREC[node.op]
            left = self.expr(node.left, prec)
            right = self.expr(node.right, prec, is_right=True)
            return "%s %s %s" % (left, node.op, right), prec
        if isinstance(node, ast.StructLit):
            parts = []
            for name, value, _line, _col in node.args:
                if name is None:
                    parts.append(self.expr(value, 0))
                else:
                    parts.append("%s: %s" % (name, self.expr(value, 0)))
            return "%s(%s)" % (node.name, ", ".join(parts)), POSTFIX_PREC
        if isinstance(node, ast.Call):
            args = ", ".join(self.expr(a, 0) for a in node.args)
            return "%s(%s)" % (self.expr(node.callee, POSTFIX_PREC), args), POSTFIX_PREC
        if isinstance(node, ast.Member):
            return "%s.%s" % (self.expr(node.obj, POSTFIX_PREC), node.name), POSTFIX_PREC
        if isinstance(node, ast.Index):
            return "%s[%s]" % (self.expr(node.target, POSTFIX_PREC),
                               self.expr(node.index, 0)), POSTFIX_PREC
        if isinstance(node, ast.ListLit):
            return "[" + ", ".join(self.expr(i, 0) for i in node.items) + "]", PRIMARY_PREC
        if isinstance(node, ast.MapLit):
            parts = []
            for key, value in node.pairs:
                parts.append("%s: %s" % (self.expr(key, 0), self.expr(value, 0)))
            return "{" + ", ".join(parts) + "}", PRIMARY_PREC
        raise SilicaError("cannot format expression %r" % (node,))  # pragma: no cover


def _escape(text):
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\0":
            out.append("\\0")
        else:
            out.append(ch)
    return "".join(out)


def format_program(program):
    printer = Printer()
    first = True
    for stmt in program.stmts:
        if not first and isinstance(stmt, (ast.FuncDecl, ast.UseStmt, ast.LetStmt)):
            printer.lines.append("")
        printer.stmt(stmt)
        first = False
    text = "\n".join(printer.lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def format_source(source, filename="<source>"):
    """Format Silica source. Raises if the file contains comments."""
    from .lexer import tokenize
    from .parser import parse
    tokens, comments = tokenize(source, filename)
    if comments:
        raise SilicaError(
            "refusing to format a file that contains comments",
            0, 0, filename,
            "silica fmt works from the syntax tree and would delete them; "
            "remove the comments or format by hand")
    program = parse(tokens, filename)
    return format_program(program)
