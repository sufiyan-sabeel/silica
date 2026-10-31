"""Silica abstract syntax tree.

Nodes are plain dataclasses carrying `line`/`col` so every later stage can
produce a located diagnostic. Expressions and statements are kept separate.
"""

from dataclasses import dataclass, field
from typing import List, Optional


class Node:
    line = 0
    col = 0


# --- expressions -------------------------------------------------------------
@dataclass
class IntLit(Node):
    value: int
    line: int = 0
    col: int = 0


@dataclass
class FloatLit(Node):
    value: float
    line: int = 0
    col: int = 0


@dataclass
class StringLit(Node):
    value: str
    line: int = 0
    col: int = 0


@dataclass
class BoolLit(Node):
    value: bool
    line: int = 0
    col: int = 0


@dataclass
class Ident(Node):
    name: str
    line: int = 0
    col: int = 0


@dataclass
class Unary(Node):
    op: str
    operand: Node
    line: int = 0
    col: int = 0


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node
    line: int = 0
    col: int = 0


@dataclass
class StructDecl(Node):
    """`struct Point { x: Int ... }` — a named record with typed fields."""
    name: str
    fields: list
    line: int = 0
    col: int = 0


@dataclass
class StructLit(Node):
    """`Point(x: 1, y: 2)` — construction. Args are (field name or None, value)."""
    name: str
    args: list
    line: int = 0
    col: int = 0


@dataclass
class MemberAssignStmt(Node):
    """`p.x = 5` — assigning to a struct field."""
    target: str
    field: str
    value: Node
    line: int = 0
    col: int = 0


@dataclass
class Call(Node):
    callee: Node          # Ident or Member
    args: List[Node]
    named: list = field(default_factory=list)   # [(name, expr, line, col)]
    line: int = 0
    col: int = 0


@dataclass
class Member(Node):
    """`module.name` — only standard-library modules have members in v0.1."""
    obj: Node
    name: str
    line: int = 0
    col: int = 0


@dataclass
class ListLit(Node):
    items: List[Node]
    line: int = 0
    col: int = 0


@dataclass
class MapLit(Node):
    pairs: List[tuple]    # list of (key_expr, value_expr)
    line: int = 0
    col: int = 0


@dataclass
class Index(Node):
    target: Node
    index: Node
    line: int = 0
    col: int = 0


# --- statements --------------------------------------------------------------
@dataclass
class LetStmt(Node):
    name: str
    type_ann: Optional[str]
    init: Node
    is_const: bool = False
    line: int = 0
    col: int = 0


@dataclass
class AssignStmt(Node):
    name: str
    value: Node
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt(Node):
    expr: Node
    line: int = 0
    col: int = 0


@dataclass
class Block(Node):
    stmts: List[Node] = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class IfStmt(Node):
    cond: Node
    then_block: Block
    else_block: Optional[Block] = None
    line: int = 0
    col: int = 0


@dataclass
class WhileStmt(Node):
    cond: Node
    body: Block
    line: int = 0
    col: int = 0


@dataclass
class ForStmt(Node):
    var: str
    iterable: Node
    body: Block
    line: int = 0
    col: int = 0


@dataclass
class FuncDecl(Node):
    name: str
    params: List[tuple]   # list of (name, type_or_None)
    ret_type: Optional[str]
    body: Block
    line: int = 0
    col: int = 0


@dataclass
class ReturnStmt(Node):
    value: Optional[Node]
    line: int = 0
    col: int = 0


@dataclass
class UseStmt(Node):
    module: str
    line: int = 0
    col: int = 0


@dataclass
class HaltStmt(Node):
    code: Optional[Node]
    line: int = 0
    col: int = 0


@dataclass
class BreakStmt(Node):
    """`break` — leave the innermost enclosing loop (0.9.0)."""
    line: int = 0
    col: int = 0


@dataclass
class ContinueStmt(Node):
    """`continue` — start the next iteration of the innermost loop (0.9.0)."""
    line: int = 0
    col: int = 0


@dataclass
class BuilderStmt(Node):
    """`call { ... }` in statement position: a UI builder block.

    The head must be a call; the block has no value and cannot appear inside an
    expression. Added in 0.2.0 — it was a parse error before, so it is additive.
    """
    call: Node
    block: Block
    line: int = 0
    col: int = 0


@dataclass
class FinStmt(Node):
    """Explicit end-of-block marker. Accepted, never required."""
    line: int = 0
    col: int = 0


@dataclass
class Program(Node):
    stmts: List[Node] = field(default_factory=list)
    line: int = 0
    col: int = 0
