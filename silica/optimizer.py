"""Compile-time constant folding.

Silica had no optimizer at all: `2 + 3 * 4` compiled to five CONST instructions
and four arithmetic opcodes, then computed the same answer on every run. This
folds literal expressions at compile time so the VM never sees them.

Correctness rule
----------------
A folded value must be **exactly** what the VM would have produced. The VM's
arithmetic is not Python's: `Int` wraps at 64 bits (`i64`), `Bool` is not a
number, integer division truncates toward zero, and mixed Int/Float promotes to
Float. All of that is mirrored here.

Where there is any doubt, folding declines and the expression is compiled
normally — the result is still correct, just not faster. Specifically:

* division or modulo by a literal zero is left alone, so the runtime error keeps
  its source location and hint;
* non-finite float results are left alone;
* any type combination the VM would reject is left alone, so the error still
  comes from the VM with its own message.

`tests/test_optimizer.py` checks this by compiling each expression twice, with
folding on and off, and requiring identical output — a differential test rather
than a table of expected values.
"""

import math

from . import ast

I64_MIN = -(2 ** 63)
I64_MAX = 2 ** 63 - 1


def _i64(value):
    """Mirror natives.i64: wrap into signed 64-bit."""
    value &= (2 ** 64 - 1)
    if value >= 2 ** 63:
        value -= 2 ** 64
    return value


class _Unknown(object):
    """Sentinel: this expression cannot be folded safely."""


UNKNOWN = _Unknown()

_ARITHMETIC = ("+", "-", "*", "/")


def fold(expr):
    """Return (value, type_name) for a literal expression, or UNKNOWN."""
    if isinstance(expr, ast.IntLit):
        return expr.value, "Int"
    if isinstance(expr, ast.FloatLit):
        return expr.value, "Float"
    if isinstance(expr, ast.StringLit):
        return expr.value, "String"
    if isinstance(expr, ast.BoolLit):
        return expr.value, "Bool"
    if isinstance(expr, ast.Unary):
        return _fold_unary(expr)
    if isinstance(expr, ast.Binary):
        return _fold_binary(expr)
    return UNKNOWN


def _fold_unary(expr):
    inner = fold(expr.operand)
    if inner is UNKNOWN:
        return UNKNOWN
    value, kind = inner
    if expr.op == "-":
        if kind == "Int":
            return _i64(-value), "Int"
        if kind == "Float":
            return -value, "Float"
        return UNKNOWN
    if expr.op == "non":
        if kind == "Bool":
            return (not value), "Bool"
        return UNKNOWN
    return UNKNOWN


def _fold_binary(expr):
    left = fold(expr.left)
    right = fold(expr.right)
    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN
    a, a_kind = left
    b, b_kind = right
    op = expr.op

    if op not in _ARITHMETIC:
        return UNKNOWN

    # String concatenation, exactly as _add does it.
    if op == "+" and a_kind == "String" and b_kind == "String":
        return a + b, "String"

    if a_kind not in ("Int", "Float") or b_kind not in ("Int", "Float"):
        return UNKNOWN

    both_int = a_kind == "Int" and b_kind == "Int"

    if op == "/":
        if b == 0:
            return UNKNOWN          # leave the runtime error where it is
        if both_int:
            quotient = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                quotient = -quotient
            return _i64(quotient), "Int"
        result = float(a) / float(b)
        return (result, "Float") if math.isfinite(result) else UNKNOWN

    if both_int:
        if op == "+":
            return _i64(a + b), "Int"
        if op == "-":
            return _i64(a - b), "Int"
        return _i64(a * b), "Int"

    # mixed or float: the VM promotes both to float
    left_f, right_f = float(a), float(b)
    if op == "+":
        result = left_f + right_f
    elif op == "-":
        result = left_f - right_f
    else:
        result = left_f * right_f
    return (result, "Float") if math.isfinite(result) else UNKNOWN


def constant_node(expr):
    """The AST literal a folded expression becomes, or None."""
    folded = fold(expr)
    if folded is UNKNOWN:
        return None
    value, kind = folded
    line = getattr(expr, "line", 0)
    col = getattr(expr, "col", 0)
    if kind == "Int":
        return ast.IntLit(value, line=line, col=col)
    if kind == "Float":
        return ast.FloatLit(value, line=line, col=col)
    if kind == "String":
        return ast.StringLit(value, line=line, col=col)
    if kind == "Bool":
        return ast.BoolLit(value, line=line, col=col)
    return None


def count_folded(source_ast):
    """How many expressions in a program can be folded. Used by tests and reports."""
    total = 0
    for node in _walk(source_ast):
        if isinstance(node, (ast.Binary, ast.Unary)) and fold(node) is not UNKNOWN:
            total += 1
    return total


def _walk(node):
    yield node
    for name in ("body", "block", "then_block", "else_block", "expr", "value",
                 "init", "cond", "left", "right", "operand", "iterable", "call"):
        child = getattr(node, name, None)
        if isinstance(child, ast.Node):
            for inner in _walk(child):
                yield inner
    for attribute in ("stmts", "args", "items"):
        children = getattr(node, attribute, None)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, ast.Node):
                    for inner in _walk(child):
                        yield inner
