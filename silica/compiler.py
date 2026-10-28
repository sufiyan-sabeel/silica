"""Bytecode compiler: checked AST -> Chunk (.sbc payload).

Locals live in numbered slots per function (parameters first), globals in a
program-wide slot array, and every call is resolved to a function index or to
a (module, name) pair of string constants for a native. Jump targets are
patched to absolute code offsets during assembly, so the emitted code is what
the verifier and VM see — nothing is re-parsed at run time.
"""

import os

from . import ast
from . import optimizer
from .bytecode import (Chunk, Function, MAX_STACK, OPS, OPERANDS, constant_key,
                       encode, verify_function, write_varint)
from .errors import CompileError
from .natives import get_constant, get_native, module_exists

VARINT_MAX = (1 << 63) - 1


def varint_len(value):
    if value < 0:
        raise ValueError("negative varint")
    n = 1
    while value >= 0x80:
        value >>= 7
        n += 1
    return n


class Scope:
    __slots__ = ("vars", "is_block")

    def __init__(self, is_block=True):
        self.vars = {}
        self.is_block = is_block


class Emitter:
    def __init__(self, compiler, fn_name, ret_type):
        self.compiler = compiler
        self.fn_name = fn_name
        self.ret_type = ret_type
        self.instrs = []      # list of [op_name, [operands], line]
        self.scopes = [Scope(is_block=False)]
        self.n_locals = 0
        self.loop_depth = 0
        # one frame per enclosing loop; `break`/`continue` read the innermost
        self.loops = []

    # -- emission ------------------------------------------------------------
    def emit(self, op, *operands, line=0):
        self.instrs.append([op, list(operands), line])
        return len(self.instrs) - 1

    def emit_jump(self, op, line=0):
        return self.emit(op, 0, line=line)

    def patch(self, index, target):
        self.instrs[index][1][0] = target

    @property
    def here(self):
        return len(self.instrs)

    # -- loops ---------------------------------------------------------------
    def enter_loop(self, continue_to, has_iterator=False):
        """Open a loop frame.

        `continue_to` is the instruction index that begins the next iteration:
        the condition for `tant`, and the ITER_NEXT instruction for `per`.
        `has_iterator` records that a `per` loop keeps its iterator on the
        value stack, so a `break` must pop it before jumping out.
        """
        self.loop_depth += 1
        frame = {"continue_to": continue_to, "has_iterator": has_iterator,
                 "breaks": []}
        self.loops.append(frame)
        return frame

    def exit_loop(self, frame):
        self.loops.pop()
        self.loop_depth -= 1
        return frame

    def emit_loop_jump(self, keyword, line):
        """Emit `break`/`continue` for the innermost enclosing loop."""
        if not self.loops:
            raise CompileError("'%s' outside a loop" % keyword, line, 0,
                               self.compiler.filename)
        frame = self.loops[-1]
        if keyword == "continue":
            self.emit("JUMP", frame["continue_to"], line=line)
            return
        # leaving a `per` loop abandons its iterator, which lives on the stack
        if frame["has_iterator"]:
            self.emit("POP", line=line)
        frame["breaks"].append(self.emit_jump("JUMP", line=line))

    # -- constants -----------------------------------------------------------
    def const(self, value):
        return self.compiler.intern(value)

    # -- scopes --------------------------------------------------------------
    def push_scope(self):
        self.scopes.append(Scope())

    def pop_scope(self):
        self.scopes.pop()

    def declare(self, name, line, col):
        slot = self.n_locals
        self.n_locals += 1
        self.scopes[-1].vars[name] = slot
        return slot

    def resolve(self, name):
        for scope in reversed(self.scopes):
            if name in scope.vars:
                return ("local", scope.vars[name])
        if name in self.compiler.global_index:
            return ("global", self.compiler.global_index[name])
        return None

    # -- assembly ------------------------------------------------------------
    def assemble(self):
        offsets = []
        pos = 0
        for op, operands, _line in self.instrs:
            offsets.append(pos)
            pos += 1
            kinds = OPERANDS.get(op, ())
            for kind, value in zip(kinds, operands):
                if kind == "u":
                    if value < 0 or value > VARINT_MAX:
                        raise CompileError("operand out of range in '%s'" % self.fn_name)
                    pos += varint_len(value)
                else:
                    pos += 4
        code = bytearray()
        lines = []
        last_line = None
        for i, (op, operands, line) in enumerate(self.instrs):
            if line != last_line:
                lines.append((offsets[i], line))
                last_line = line
            resolved = []
            kinds = OPERANDS.get(op, ())
            for kind, value in zip(kinds, operands):
                if kind == "j":
                    if value >= len(offsets) and value != len(self.instrs):
                        raise CompileError("internal: bad jump label in '%s'" % self.fn_name)
                    resolved.append(offsets[value] if value < len(offsets) else pos)
                else:
                    resolved.append(value)
            code.extend(encode(op, *resolved))
        return bytes(code), lines


class Compiler:
    def __init__(self, program, filename="<source>", functions=None, globals_=None,
                 pre_globals=None, pre_index=None):
        self.program = program
        self.filename = filename
        self.func_infos = functions or {}
        self.global_infos = globals_ or {}
        self.chunk = Chunk()
        self.const_index = {}
        self.global_index = dict(pre_index or {})
        self.func_index = {}
        # globals carried in from an earlier compile (the REPL keeps state)
        self.pre_globals = list(pre_globals or [])
        # constant folding; SILICA_NO_OPT=1 turns it off, which is how the
        # differential test proves folded and unfolded programs behave the same
        self.optimize = os.environ.get("SILICA_NO_OPT") != "1"
        self.optimize_stats = {"folded": 0}

    # -- constants pool ------------------------------------------------------
    def intern(self, value):
        key = constant_key(value)
        idx = self.const_index.get(key)
        if idx is None:
            idx = len(self.chunk.constants)
            self.chunk.constants.append(value)
            self.const_index[key] = idx
        return idx

    def intern_string(self, text):
        return self.intern(str(text))

    # -- driver --------------------------------------------------------------
    def compile(self):
        stmts = self.program.stmts

        # 1. function indices (forward references are allowed)
        for stmt in stmts:
            if isinstance(stmt, ast.FuncDecl):
                self.func_index[stmt.name] = len(self.func_index)
                self.chunk.functions.append(Function(stmt.name))

        # 2. globals (any carried in from a previous REPL entry come first, so
        #    slot numbers stay stable across entries)
        if self.pre_globals:
            self.chunk.globals.extend(self.pre_globals)
        for stmt in stmts:
            if isinstance(stmt, ast.LetStmt):
                if stmt.name in self.global_index:
                    continue  # rebound in the REPL: same slot, new value
                info = self.global_infos.get(stmt.name)
                type_name = info.type if info else "Any"
                self.global_index[stmt.name] = len(self.chunk.globals)
                self.chunk.globals.append((stmt.name, type_name))

        # 3. global initialiser
        globals_stmts = [s for s in stmts if isinstance(s, ast.LetStmt)]
        if globals_stmts:
            self.chunk.init = len(self.chunk.functions)
            self.chunk.functions.append(self.compile_init(globals_stmts))

        # 4. function bodies
        for stmt in stmts:
            if isinstance(stmt, ast.FuncDecl):
                index = self.func_index[stmt.name]
                self.chunk.functions[index] = self.compile_function(stmt)

        # 5. declare max_stack from the emitted code (verifier analysis), so the
        #    header never under-declares the stack the code needs
        for index, fn in enumerate(self.chunk.functions):
            fn.max_stack = verify_function(self.chunk, fn, index, self.filename)

        # 6. entry point
        self.chunk.entry = self.func_index.get("main")
        return self.chunk

    def compile_init(self, globals_stmts):
        emitter = Emitter(self, "__init__", "Unit")
        for stmt in globals_stmts:
            self.compile_expr(emitter, stmt.init)
            emitter.emit("STORE_GLOBAL", self.global_index[stmt.name], line=stmt.line)
        emitter.emit("UNIT", line=0)
        emitter.emit("RET", line=0)
        return self.finish(emitter, "__init__", 0, "Unit")

    def compile_function(self, decl):
        info = self.func_infos.get(decl.name)
        ret_type = info.ret if info else (decl.ret_type or "Unit")
        emitter = Emitter(self, decl.name, ret_type)
        for entry in decl.params:
            emitter.declare(entry[0], entry[2], entry[3])
        self.compile_block(emitter, decl.body, new_scope=False)
        # implicit unit return for Unit functions; the checker guarantees a
        # trailing 'ret' for every other return type
        if ret_type == "Unit":
            emitter.emit("UNIT", line=decl.line)
            emitter.emit("RET", line=decl.line)
        else:
            emitter.emit("UNIT", line=decl.line)
            emitter.emit("RET", line=decl.line)
        return self.finish(emitter, decl.name, len(decl.params), ret_type)

    def finish(self, emitter, name, arity, ret_type):
        code, lines = emitter.assemble()
        # max_stack is filled in by the post-pass in compile(): the analysis
        # that proves the code safe is the same one that sizes the stack
        return Function(name, arity, max(emitter.n_locals, arity), MAX_STACK,
                        ret_type, code, lines)

    # -- statements ----------------------------------------------------------
    def compile_block(self, emitter, block, new_scope=True):
        if new_scope:
            emitter.push_scope()
        for stmt in block.stmts:
            self.compile_stmt(emitter, stmt)
        if new_scope:
            emitter.pop_scope()

    def compile_stmt(self, emitter, stmt):
        line = getattr(stmt, "line", 0)
        if isinstance(stmt, ast.LetStmt):
            self.compile_expr(emitter, stmt.init)
            slot = emitter.declare(stmt.name, stmt.line, stmt.col)
            emitter.emit("STORE_LOCAL", slot, line=line)
        elif isinstance(stmt, ast.AssignStmt):
            self.compile_expr(emitter, stmt.value)
            target = emitter.resolve(stmt.name)
            if target is None:
                raise CompileError("unknown name '%s'" % stmt.name, line, stmt.col,
                                   self.filename)
            kind, idx = target
            emitter.emit("STORE_LOCAL" if kind == "local" else "STORE_GLOBAL",
                         idx, line=line)
        elif isinstance(stmt, ast.ExprStmt):
            self.compile_expr_stmt(emitter, stmt)
        elif isinstance(stmt, ast.BuilderStmt):
            self.compile_builder(emitter, stmt)
        elif isinstance(stmt, ast.IfStmt):
            self.compile_expr(emitter, stmt.cond)
            jump_else = emitter.emit_jump("JUMP_IF_FALSE", line=line)
            self.compile_block(emitter, stmt.then_block)
            if stmt.else_block is not None:
                jump_end = emitter.emit_jump("JUMP", line=line)
                emitter.patch(jump_else, emitter.here)
                self.compile_block(emitter, stmt.else_block)
                emitter.patch(jump_end, emitter.here)
            else:
                emitter.patch(jump_else, emitter.here)
        elif isinstance(stmt, ast.WhileStmt):
            start = emitter.here
            self.compile_expr(emitter, stmt.cond)
            jump_end = emitter.emit_jump("JUMP_IF_FALSE", line=line)
            frame = emitter.enter_loop(continue_to=start)
            self.compile_block(emitter, stmt.body)
            emitter.exit_loop(frame)
            emitter.emit("JUMP", start, line=line)
            end = emitter.here
            emitter.patch(jump_end, end)
            for index in frame["breaks"]:
                emitter.patch(index, end)
        elif isinstance(stmt, ast.ForStmt):
            self.compile_expr(emitter, stmt.iterable)
            emitter.emit("ITER_START", line=line)
            start = emitter.here
            jump_end = emitter.emit_jump("ITER_NEXT", line=line)
            emitter.push_scope()
            slot = emitter.declare(stmt.var, stmt.line, stmt.col)
            emitter.emit("STORE_LOCAL", slot, line=line)
            frame = emitter.enter_loop(continue_to=start, has_iterator=True)
            self.compile_block(emitter, stmt.body, new_scope=False)
            emitter.exit_loop(frame)
            emitter.pop_scope()
            emitter.emit("JUMP", start, line=line)
            end = emitter.here
            emitter.patch(jump_end, end)
            for index in frame["breaks"]:
                emitter.patch(index, end)
        elif isinstance(stmt, ast.ReturnStmt):
            if stmt.value is None:
                emitter.emit("UNIT", line=line)
            else:
                self.compile_expr(emitter, stmt.value)
            emitter.emit("RET", line=line)
        elif isinstance(stmt, ast.HaltStmt):
            if stmt.code is None:
                emitter.emit("HALT_OK", line=line)
            else:
                self.compile_expr(emitter, stmt.code)
                emitter.emit("HALT_POP", line=line)
        elif isinstance(stmt, ast.BreakStmt):
            emitter.emit_loop_jump("break", line)
        elif isinstance(stmt, ast.ContinueStmt):
            emitter.emit_loop_jump("continue", line)
        elif isinstance(stmt, ast.FinStmt):
            pass
        elif isinstance(stmt, ast.UseStmt):
            pass
        elif isinstance(stmt, ast.FuncDecl):
            raise CompileError("nested function '%s' is not supported" % stmt.name,
                               stmt.line, stmt.col, self.filename)
        elif isinstance(stmt, ast.Block):
            self.compile_block(emitter, stmt)
        else:  # pragma: no cover
            raise CompileError("cannot compile statement", line, 0, self.filename)

    def compile_expr_stmt(self, emitter, stmt):
        expr = stmt.expr
        line = stmt.line
        # fast path: sprint(x) / dit(x) as a statement becomes a single opcode
        if isinstance(expr, ast.Call) and isinstance(expr.callee, ast.Ident) \
                and len(expr.args) == 1 \
                and expr.callee.name in ("sprint", "dit"):
            self.compile_expr(emitter, expr.args[0])
            emitter.emit("PRINT" if expr.callee.name == "sprint" else "DIT", line=line)
            return
        self.compile_expr(emitter, expr)
        emitter.emit("POP", line=line)
        if self.accepts_block(expr):
            # a widget called without a block still opened a scope at run time
            self.emit_end_block(emitter, line)

    # -- builder blocks -------------------------------------------------------
    def resolve_native(self, call):
        """(module, member) for a call, or (None, None) when it is not a native."""
        callee = getattr(call, "callee", None)
        if isinstance(callee, ast.Ident):
            if callee.name in self.func_index:
                return None, None
            return "core", callee.name
        if isinstance(callee, ast.Member):
            parts = []
            node = callee
            while isinstance(node, ast.Member):
                parts.append(node.name)
                node = node.obj
            if not isinstance(node, ast.Ident):
                return None, None
            parts.append(node.name)
            parts.reverse()
            for split in range(len(parts) - 1, 0, -1):
                module = ".".join(parts[:split])
                if module_exists(module):
                    return module, parts[-1]
        return None, None

    def accepts_block(self, expr):
        if not isinstance(expr, ast.Call):
            return False
        module, member = self.resolve_native(expr)
        if module is None:
            return False
        native = get_native(module, member)
        return bool(native is not None and native.accepts_block)

    def emit_end_block(self, emitter, line):
        """Pop the builder scope: an existing CALL_NATIVE, no new opcode."""
        emitter.emit("CALL_NATIVE", self.intern_string("ui"),
                     self.intern_string("__end_block"), 0, line=line)
        emitter.emit("POP", line=line)

    def compile_builder(self, emitter, stmt):
        line = stmt.line
        self.compile_call(emitter, stmt.call)
        emitter.emit("POP", line=line)
        module, member = self.resolve_native(stmt.call)
        if member == "list" and stmt.call.args:
            # ui.list(items) { ... } runs its block once per item, with `item`
            # bound — the same iteration the `per` loop compiles to.
            self.compile_expr(emitter, stmt.call.args[0])
            emitter.emit("ITER_START", line=line)
            start = emitter.here
            jump_end = emitter.emit_jump("ITER_NEXT", line=line)
            emitter.push_scope()
            slot = emitter.declare("item", line, 0)
            emitter.emit("STORE_LOCAL", slot, line=line)
            self.compile_block(emitter, stmt.block, new_scope=False)
            emitter.pop_scope()
            emitter.emit("JUMP", start, line=line)
            emitter.patch(jump_end, emitter.here)
        else:
            self.compile_block(emitter, stmt.block)
        self.emit_end_block(emitter, line)

    # -- expressions ---------------------------------------------------------
    def compile_expr(self, emitter, expr):
        line = getattr(expr, "line", 0)
        if self.optimize and isinstance(expr, (ast.Binary, ast.Unary)):
            folded = optimizer.constant_node(expr)
            if folded is not None:
                # one CONST instead of a sub-tree and its opcodes
                self.optimize_stats["folded"] += 1
                self.compile_expr(emitter, folded)
                return
        if isinstance(expr, ast.IntLit):
            emitter.emit("CONST", self.intern(expr.value), line=line)
        elif isinstance(expr, ast.FloatLit):
            emitter.emit("CONST", self.intern(expr.value), line=line)
        elif isinstance(expr, ast.StringLit):
            emitter.emit("CONST", self.intern(expr.value), line=line)
        elif isinstance(expr, ast.BoolLit):
            emitter.emit("TRUE" if expr.value else "FALSE", line=line)
        elif isinstance(expr, ast.Ident):
            target = emitter.resolve(expr.name)
            if target is None:
                raise CompileError("unknown name '%s'" % expr.name, line, expr.col,
                                   self.filename)
            kind, idx = target
            emitter.emit("LOAD_LOCAL" if kind == "local" else "LOAD_GLOBAL", idx, line=line)
        elif isinstance(expr, ast.Unary):
            self.compile_expr(emitter, expr.operand)
            emitter.emit("NEG" if expr.op == "-" else "NOT", line=line)
        elif isinstance(expr, ast.Binary):
            self.compile_binary(emitter, expr)
        elif isinstance(expr, ast.Call):
            self.compile_call(emitter, expr)
        elif isinstance(expr, ast.Member):
            self.compile_member(emitter, expr)
        elif isinstance(expr, ast.ListLit):
            for item in expr.items:
                self.compile_expr(emitter, item)
            emitter.emit("MAKE_LIST", len(expr.items), line=line)
        elif isinstance(expr, ast.MapLit):
            for key, value in expr.pairs:
                self.compile_expr(emitter, key)
                self.compile_expr(emitter, value)
            emitter.emit("MAKE_MAP", len(expr.pairs), line=line)
        elif isinstance(expr, ast.Index):
            self.compile_expr(emitter, expr.target)
            self.compile_expr(emitter, expr.index)
            emitter.emit("INDEX_GET", line=line)
        else:  # pragma: no cover
            raise CompileError("cannot compile expression", line, 0, self.filename)

    def compile_binary(self, emitter, expr):
        line = expr.line
        op = expr.op
        if op == "und":
            self.compile_expr(emitter, expr.left)
            jump_false = emitter.emit_jump("JUMP_IF_FALSE", line=line)
            self.compile_expr(emitter, expr.right)
            jump_end = emitter.emit_jump("JUMP", line=line)
            emitter.patch(jump_false, emitter.here)
            emitter.emit("FALSE", line=line)
            emitter.patch(jump_end, emitter.here)
            return
        if op == "ou":
            self.compile_expr(emitter, expr.left)
            jump_right = emitter.emit_jump("JUMP_IF_FALSE", line=line)
            emitter.emit("TRUE", line=line)
            jump_end = emitter.emit_jump("JUMP", line=line)
            emitter.patch(jump_right, emitter.here)
            self.compile_expr(emitter, expr.right)
            emitter.patch(jump_end, emitter.here)
            return
        self.compile_expr(emitter, expr.left)
        self.compile_expr(emitter, expr.right)
        opcode = {
            "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
            "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
        }[op]
        emitter.emit(opcode, line=line)

    def compile_call(self, emitter, expr):
        line = expr.line
        callee = expr.callee
        if isinstance(callee, ast.Ident):
            name = callee.name
            if name in self.func_index:
                for arg in expr.args:
                    self.compile_expr(emitter, arg)
                emitter.emit("CALL", self.func_index[name], len(expr.args), line=line)
                return
            native = get_native("core", name)
            if native is not None:
                for arg in expr.args:
                    self.compile_expr(emitter, arg)
                mod_idx = self.intern_string("core")
                fn_idx = self.intern_string(name)
                emitter.emit("CALL_NATIVE", mod_idx, fn_idx, len(expr.args), line=line)
                return
            raise CompileError("unknown function '%s'" % name, line, callee.col,
                               self.filename)
        if isinstance(callee, ast.Member):
            module, member = self.resolve_native(expr)
            if module is None:
                raise CompileError("cannot compile call", line, expr.col,
                                   self.filename)
            native = get_native(module, member)
            if native is None:
                raise CompileError("unknown native '%s.%s'" % (module, member),
                                   line, callee.col, self.filename)
            for arg in expr.args:
                self.compile_expr(emitter, arg)
            mod_idx = self.intern_string(module)
            fn_idx = self.intern_string(member)
            emitter.emit("CALL_NATIVE", mod_idx, fn_idx, len(expr.args), line=line)
            return
        raise CompileError("cannot compile call", line, expr.col, self.filename)

    def compile_member(self, emitter, expr):
        if not isinstance(expr.obj, ast.Ident):
            raise CompileError("only module members are supported",
                               expr.line, expr.col, self.filename)
        module = expr.obj.name
        found, value = get_constant(module, expr.name)
        if not found:
            raise CompileError("unknown constant '%s.%s'" % (module, expr.name),
                               expr.line, expr.col, self.filename)
        emitter.emit("CONST", self.intern(float(value)), line=expr.line)


def compile_program(program, filename="<source>", functions=None, globals_=None):
    return Compiler(program, filename, functions, globals_).compile()
