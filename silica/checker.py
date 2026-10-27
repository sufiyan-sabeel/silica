"""Semantic analysis and static type checking for Silica.

The checker validates names, scopes, arities and types before any bytecode is
produced. Types are strings: "Int", "Float", "Bool", "String", "Unit", "List",
"Map", "Any". `List` and `Map` are containers of unknown element type in
v0.1.0 (no generics yet); their element type checks as "Any", which is
compatible with every type. That is a documented limitation, not an oversight.
"""

from . import ast
from .errors import SilicaTypeError
from .natives import (PLANNED_MODULES, get_constant, get_native, module_exists,
                      ui_reserved_modules)

NUMERIC = ("Int", "Float")
ANY = "Any"
I64_MIN = -(2 ** 63)
I64_MAX = 2 ** 63 - 1


class VarInfo:
    __slots__ = ("name", "type", "is_const", "line", "col")

    def __init__(self, name, type_, is_const, line=0, col=0):
        self.name = name
        self.type = type_
        self.is_const = is_const
        self.line = line
        self.col = col


class FuncInfo:
    __slots__ = ("name", "params", "ret", "node")

    def __init__(self, name, params, ret, node):
        self.name = name
        self.params = params      # list of (name, type)
        self.ret = ret
        self.node = node


class Checker:
    def __init__(self, program, filename="<source>", require_main=True,
                 pre_globals=None):
        self.program = program
        self.filename = filename
        self.require_main = require_main
        # globals carried in from an earlier compile (REPL session state)
        self.pre_globals = list(pre_globals or [])
        self.functions = {}
        self.globals = {}
        self.modules = set()
        self.scopes = []
        self.current_func = None
        # builder-block context: how deep we are inside `call { ... }` blocks and
        # inside an event body (`ui.on(...) { ... }`), both reset per function
        self.builder_depth = 0
        self.event_depth = 0

    # -- diagnostics ---------------------------------------------------------
    def error(self, message, node=None, hint=None):
        line = getattr(node, "line", 0)
        col = getattr(node, "col", 0)
        raise SilicaTypeError(message, line, col, self.filename, hint)

    # -- scope handling ------------------------------------------------------
    def push_scope(self):
        self.scopes.append({})

    def pop_scope(self):
        self.scopes.pop()

    def declare(self, info, node=None):
        scope = self.scopes[-1] if self.scopes else self.globals
        if info.name in scope:
            self.error("'%s' is already declared in this scope" % info.name, node)
        scope[info.name] = info

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return self.globals.get(name)

    # -- entry point ---------------------------------------------------------
    def check(self):
        # pass 1: module imports and function signatures
        for stmt in self.program.stmts:
            if isinstance(stmt, ast.UseStmt):
                self.check_use(stmt)
        for stmt in self.program.stmts:
            if isinstance(stmt, ast.FuncDecl):
                self.declare_function(stmt)

        # pass 2: globals, then bodies
        for name, type_name in self.pre_globals:
            self.globals.setdefault(name, VarInfo(name, type_name, False))
        for stmt in self.program.stmts:
            if isinstance(stmt, ast.LetStmt):
                self.check_let(stmt, top_level=True)
            elif isinstance(stmt, (ast.UseStmt, ast.FuncDecl)):
                continue
            elif isinstance(stmt, ast.FinStmt):
                self.error("'fin' is only allowed at the end of a block", stmt)
            else:
                self.error(
                    "statements are not allowed at the top level of a Silica file",
                    stmt, hint="put executable code inside 'sfn main() { ... }'")

        for stmt in self.program.stmts:
            if isinstance(stmt, ast.FuncDecl):
                self.check_function(stmt)

        if self.require_main:
            if "main" not in self.functions:
                self.error("program has no entry point",
                           hint="add 'sfn main() { ... }'")
            if self.functions["main"].params:
                self.error("'main' must not take parameters",
                           self.functions["main"].node)
        return self

    def is_imported(self, module):
        """True when `module` was imported, directly or as a submodule.

        `use ui` makes `ui.state.set` and `ui.lib.widgets.text` resolvable,
        because importing a module brings its submodules into scope. Importing
        only `ui.lib.widgets` does *not* bring `ui` into scope.
        """
        if module in self.modules:
            return True
        for imported in self.modules:
            if module.startswith(imported + "."):
                return True
        return False

    def resolve_member_path(self, expr):
        """G2: longest prefix that names an imported module, one member after it.

        Returns (module, member) or raises a located type error.
        """
        segments, tail = _flatten_member(expr)
        if not segments:
            self.error("only standard-library modules have members in Silica v0.2.0",
                       expr)
        whole = ".".join(segments)
        if module_exists(whole):
            self.error("`%s` is a module path, not a value" % whole, expr,
                       hint="call a member, e.g. %s.%s"
                            % (whole, native_names_hint(whole)))
        for split in range(len(segments) - 1, 0, -1):
            module = ".".join(segments[:split])
            if module_exists(module) or module in PLANNED_MODULES:
                if split != len(segments) - 1:
                    self.error(
                        "`%s` is a module and only one member may follow it"
                        % module, expr,
                        hint="did you mean to `use %s`?" % ".".join(segments[:-1]))
                if not self.is_imported(module):
                    self.error("module '%s' is not imported" % module, expr,
                               hint="add 'use %s' at the top of the file" % module)
                return module, segments[-1]
            reserved, adapters = ui_reserved_modules()
            if module in adapters:
                self.error(
                    "no adapter installed for %s; adapters are specified but not "
                    "implemented" % module, expr)
            if module in reserved:
                self.error("%s is planned but not implemented (%s)"
                           % (module, reserved[module]), expr)
        # nothing matched: report the longest plausible prefix
        prefix = ".".join(segments[:-1])
        if not self.is_imported(prefix) and not module_exists(prefix):
            self.error("unknown module '%s'" % prefix, expr,
                       hint="implemented modules: %s"
                            % ", ".join(sorted(module_names())))
        self.error("module '%s' has no member '%s'" % (prefix, segments[-1]), expr,
                   hint="available: %s" % _module_members(prefix))

    def check_use(self, stmt):
        mod = stmt.module
        reserved, adapters = ui_reserved_modules()
        if mod in adapters:
            self.error("no adapter installed for %s; adapters are specified but not "
                       "implemented" % mod, stmt,
                       hint="UI 0.1 ships no adapters; see docs/UI.md")
        if mod in reserved:
            self.error("%s is planned but not implemented (%s)"
                       % (mod, reserved[mod]), stmt,
                       hint="reserved names fail loudly instead of pretending")
        if module_exists(mod):
            self.modules.add(mod)
            return
        if mod in PLANNED_MODULES:
            self.error("module '%s' is planned but not implemented yet" % mod, stmt,
                       hint="implemented modules: core (always available), math, string, "
                       "collections, fs, json")
        self.error("unknown module '%s'" % mod, stmt,
                   hint="implemented modules: core (always available), math, string, "
                       "collections, fs, json")

    def declare_function(self, decl):
        if decl.name in self.functions:
            self.error("function '%s' is already declared" % decl.name, decl)
        if decl.name in ("sprint", "dit", "input"):
            self.error("'%s' is a reserved built-in name" % decl.name, decl)
        params = []
        seen = set()
        for entry in decl.params:
            name, ptype = entry[0], entry[1]
            if name in seen:
                self.error("duplicate parameter '%s' in function '%s'" % (name, decl.name), decl)
            seen.add(name)
            params.append((name, ptype or ANY))
        ret = decl.ret_type or "Unit"
        self.functions[decl.name] = FuncInfo(decl.name, params, ret, decl)

    def check_function(self, decl):
        info = self.functions[decl.name]
        outer = self.current_func
        outer_builder, outer_event = self.builder_depth, self.event_depth
        self.builder_depth = 0
        self.event_depth = 0
        self.current_func = info
        self.push_scope()
        for name, ptype, line, col in decl.params:
            self.declare(VarInfo(name, ptype or ANY, True, line, col), decl)
        self.check_block(decl.body, new_scope=False)
        if info.ret != "Unit" and not self.always_returns(decl.body):
            self.error(
                "function '%s' can finish without returning a value of type %s"
                % (decl.name, info.ret), decl,
                hint="every path must end in 'ret' (or 'halt'); add a 'ret' after the last block")
        self.pop_scope()
        self.current_func = outer
        self.builder_depth, self.event_depth = outer_builder, outer_event

    def always_returns(self, block):
        """True when control cannot reach the end of `block`."""
        for stmt in reversed(block.stmts):
            if isinstance(stmt, ast.FinStmt):
                continue
            if isinstance(stmt, (ast.ReturnStmt, ast.HaltStmt)):
                return True
            if isinstance(stmt, ast.IfStmt) and stmt.else_block is not None:
                return (self.always_returns(stmt.then_block)
                        and self.always_returns(stmt.else_block))
            if isinstance(stmt, ast.Block):
                return self.always_returns(stmt)
            return False
        return False

    # -- statements ----------------------------------------------------------
    def check_block(self, block, new_scope=True):
        if new_scope:
            self.push_scope()
        for stmt in block.stmts:
            self.check_stmt(stmt)
        if new_scope:
            self.pop_scope()

    def check_stmt(self, stmt):
        if self.event_depth > 0:
            self.check_event_statement(stmt)
        if isinstance(stmt, ast.BuilderStmt):
            self.check_builder(stmt)
        elif isinstance(stmt, ast.ReturnStmt) and self.builder_depth > 0:
            self.error("'ret' inside a builder block is not allowed; close the block "
                       "first", stmt,
                       hint="a widget tree is closed structurally, so leaving one "
                            "early is almost always a mistake")
        elif isinstance(stmt, ast.HaltStmt) and self.builder_depth > 0:
            self.error("'halt' inside a builder block is not allowed; close the block "
                       "first", stmt)
        elif isinstance(stmt, ast.LetStmt):
            self.check_let(stmt)
        elif isinstance(stmt, ast.AssignStmt):
            self.check_assign(stmt)
        elif isinstance(stmt, ast.ExprStmt):
            self.expr_type(stmt.expr)
        elif isinstance(stmt, ast.IfStmt):
            cond = self.expr_type(stmt.cond)
            if cond != "Bool" and cond != ANY:
                self.error("condition of 'si' must be Bool, found %s" % cond, stmt.cond,
                           hint="Silica has no truthiness: write a comparison, e.g. si x != 0")
            self.check_block(stmt.then_block)
            if stmt.else_block:
                self.check_block(stmt.else_block)
        elif isinstance(stmt, ast.WhileStmt):
            cond = self.expr_type(stmt.cond)
            if cond != "Bool" and cond != ANY:
                self.error("condition of 'tant' must be Bool, found %s" % cond, stmt.cond,
                           hint="Silica has no truthiness: write a comparison, e.g. tant i < 10")
            self.check_block(stmt.body)
        elif isinstance(stmt, ast.ForStmt):
            iterable = self.expr_type(stmt.iterable)
            if iterable == "List":
                var_type = ANY
            elif iterable == "String":
                var_type = "String"
            elif iterable == "Map":
                var_type = "String"
            elif iterable == ANY:
                var_type = ANY
            else:
                self.error("'per' needs a List, Map or String, found %s" % iterable,
                           stmt.iterable)
            self.push_scope()
            self.declare(VarInfo(stmt.var, var_type, True), stmt)
            self.check_block(stmt.body, new_scope=False)
            self.pop_scope()
        elif isinstance(stmt, ast.ReturnStmt):
            self.check_return(stmt)
        elif isinstance(stmt, ast.HaltStmt):
            if stmt.code is not None:
                t = self.expr_type(stmt.code)
                if t not in ("Int", ANY):
                    self.error("'halt' exit code must be Int, found %s" % t, stmt.code)
        elif isinstance(stmt, ast.FinStmt):
            pass
        elif isinstance(stmt, (ast.FuncDecl, ast.UseStmt)):
            self.error("'%s' is not allowed inside a block" % (
                "sfn" if isinstance(stmt, ast.FuncDecl) else "use"), stmt,
                hint="declare functions and imports at the top level")
        elif isinstance(stmt, ast.Block):
            self.check_block(stmt)
        else:  # pragma: no cover - defensive
            self.error("unsupported statement", stmt)

    def native_of_call(self, call):
        """The native a call resolves to, or None for user functions."""
        callee = getattr(call, "callee", None)
        if isinstance(callee, ast.Ident):
            return get_native("core", callee.name)
        if isinstance(callee, ast.Member):
            module, member = self.resolve_member_path(callee)
            return get_native(module, member)
        return None

    def check_builder(self, stmt):
        call = stmt.call
        ret = self.call_type(call)
        native = self.native_of_call(call)
        if native is None:
            self.error("a builder block must follow a call to a widget, e.g. "
                       "`ui.card() { ... }`", call)
        if not native.accepts_block:
            self.error("`%s` does not take a block; pass properties as a map "
                       "argument" % native.qualified, call,
                       hint='e.g. %s("text", {size: "lg"})' % native.qualified)
        is_event = native.qualified == "ui.on"
        self.builder_depth += 1
        if is_event:
            self.event_depth += 1
        self.push_scope()
        if native.name == "list":
            # ui.list(items) { ... } binds `item` for the block, like a `per` loop
            self.declare(VarInfo("item", ANY, True, call.line, call.col), call)
        for inner in stmt.block.stmts:
            self.check_stmt(inner)
        self.pop_scope()
        if is_event:
            self.event_depth -= 1
        self.builder_depth -= 1
        return ret

    def check_event_statement(self, stmt):
        """E7: an event body may contain only the documented actions."""
        from .ui.natives_ui import EVENT_ACTIONS
        if not isinstance(stmt, ast.ExprStmt) or not isinstance(stmt.expr, ast.Call):
            self.error(
                "event bodies run in the browser; only %s are allowed in UI 0.1"
                % ", ".join(EVENT_ACTIONS), stmt,
                hint="compute values before the ui.on block, then act on them")
        call = stmt.expr
        callee = call.callee
        name = None
        if isinstance(callee, ast.Ident):
            name = callee.name
        elif isinstance(callee, ast.Member):
            module, member = self.resolve_member_path(callee)
            name = "%s.%s" % (module, member)
        if name not in EVENT_ACTIONS:
            self.error(
                "event bodies run in the browser; only %s are allowed in UI 0.1"
                % ", ".join(EVENT_ACTIONS), call,
                hint="'%s' cannot run client-side; move it out of ui.on" % (name or "this"))

    def check_let(self, stmt, top_level=False):
        declared = stmt.type_ann
        actual = self.expr_type(stmt.init)
        if declared is None:
            if actual == "Unit":
                self.error("cannot infer a type from a Unit expression", stmt,
                           hint="add an explicit type: let x: Unit = ...")
            declared = actual
        elif not self.compatible(actual, declared):
            self.error("cannot initialise %s with a value of type %s" % (declared, actual),
                       stmt.init, hint=self.conversion_hint(actual, declared))
        info = VarInfo(stmt.name, declared, stmt.is_const, stmt.line, stmt.col)
        self.declare(info, stmt)

    def check_assign(self, stmt):
        info = self.lookup(stmt.name)
        if info is None:
            if stmt.name in self.functions:
                self.error("cannot assign to function '%s'" % stmt.name, stmt)
            self.error("unknown name '%s'" % stmt.name, stmt,
                       hint="declare it first with 'let %s = ...'" % stmt.name)
        if info.is_const:
            self.error("cannot assign to '%s': it is a constant" % stmt.name, stmt,
                       hint="declare it with 'let' instead of 'const'")
        actual = self.expr_type(stmt.value)
        if not self.compatible(actual, info.type):
            self.error("cannot assign %s to '%s' of type %s"
                       % (actual, stmt.name, info.type), stmt.value,
                       hint=self.conversion_hint(actual, info.type))

    def check_return(self, stmt):
        if self.current_func is None:
            self.error("'ret' outside a function", stmt)
        expected = self.current_func.ret
        if stmt.value is None:
            if expected != "Unit":
                self.error("function '%s' must return %s, but 'ret' has no value"
                           % (self.current_func.name, expected), stmt)
            return
        actual = self.expr_type(stmt.value)
        if expected == "Unit":
            self.error("function '%s' returns Unit but 'ret' has a value"
                       % self.current_func.name, stmt)
        if not self.compatible(actual, expected):
            self.error("function '%s' must return %s, found %s"
                       % (self.current_func.name, expected, actual), stmt.value)

    # -- expressions ---------------------------------------------------------
    def expr_type(self, expr):
        if isinstance(expr, ast.IntLit):
            if expr.value < I64_MIN or expr.value > I64_MAX:
                self.error("integer literal %d does not fit in Int (64-bit)"
                           % expr.value, expr,
                           hint="Int is signed 64-bit: %d to %d" % (I64_MIN, I64_MAX))
            return "Int"
        if isinstance(expr, ast.FloatLit):
            return "Float"
        if isinstance(expr, ast.StringLit):
            return "String"
        if isinstance(expr, ast.BoolLit):
            return "Bool"
        if isinstance(expr, ast.Ident):
            return self.ident_type(expr)
        if isinstance(expr, ast.Unary):
            return self.unary_type(expr)
        if isinstance(expr, ast.Binary):
            return self.binary_type(expr)
        if isinstance(expr, ast.Call):
            return self.call_type(expr)
        if isinstance(expr, ast.Member):
            return self.member_type(expr)
        if isinstance(expr, ast.ListLit):
            for item in expr.items:
                t = self.expr_type(item)
                if t == "Unit":
                    self.error("a list element cannot be Unit", item)
            return "List"
        if isinstance(expr, ast.MapLit):
            for key, value in expr.pairs:
                if self.expr_type(key) != "String":
                    self.error("map keys must be String", key)
                if self.expr_type(value) == "Unit":
                    self.error("a map value cannot be Unit", value)
            return "Map"
        if isinstance(expr, ast.Index):
            return self.index_type(expr)
        self.error("unsupported expression", expr)

    def ident_type(self, expr):
        info = self.lookup(expr.name)
        if info is not None:
            return info.type
        if expr.name in self.functions:
            self.error("function '%s' must be called with (...)" % expr.name, expr)
        native = get_native("core", expr.name)
        if native is not None:
            self.error("'%s' must be called with (...)" % expr.name, expr)
        if expr.name in self.modules:
            self.error("module '%s' needs a member, e.g. %s.%s" % (
                expr.name, expr.name, native_names_hint(expr.name)), expr)
        self.error("unknown name '%s'" % expr.name, expr,
                   hint="check spelling, or declare it with 'let'")

    def unary_type(self, expr):
        t = self.expr_type(expr.operand)
        if expr.op == "non":
            if t not in ("Bool", ANY):
                self.error("'non' expects Bool, found %s" % t, expr)
            return "Bool"
        if t not in NUMERIC + (ANY,):
            self.error("unary '-' expects a number, found %s" % t, expr)
        return t

    def binary_type(self, expr):
        op = expr.op
        lt = self.expr_type(expr.left)
        rt = self.expr_type(expr.right)

        if op in ("und", "ou"):
            for side, t in ((expr.left, lt), (expr.right, rt)):
                if t not in ("Bool", ANY):
                    self.error("'%s' expects Bool operands, found %s" % (op, t), side,
                               hint="compare values explicitly, e.g. a > 0 und b > 0")
            return "Bool"

        if op in ("==", "!="):
            if lt == ANY or rt == ANY:
                return "Bool"
            if lt == rt:
                return "Bool"
            if lt in NUMERIC and rt in NUMERIC:
                return "Bool"
            self.error("cannot compare %s with %s using '%s'" % (lt, rt, op), expr)
        if op in ("<", "<=", ">", ">="):
            if lt == ANY or rt == ANY:
                return "Bool"
            if lt in NUMERIC and rt in NUMERIC:
                return "Bool"
            if lt == rt == "String":
                return "Bool"
            self.error("cannot order %s and %s with '%s'" % (lt, rt, op), expr,
                       hint="ordering works on numbers and Strings")
        if op == "+":
            if lt == ANY or rt == ANY:
                return ANY
            if lt == "String" and rt == "String":
                return "String"
            if lt == "List" and rt == "List":
                return "List"
            if lt in NUMERIC and rt in NUMERIC:
                return "Float" if "Float" in (lt, rt) else "Int"
            self.error("cannot add %s and %s" % (lt, rt), expr,
                       hint="'+' works on numbers, Strings and Lists")
        if op in ("-", "*", "/", "%"):
            if lt == ANY or rt == ANY:
                return ANY
            if lt in NUMERIC and rt in NUMERIC:
                return "Float" if "Float" in (lt, rt) else "Int"
            self.error("'%s' expects numbers, found %s and %s" % (op, lt, rt), expr)
        self.error("unsupported operator '%s'" % op, expr)

    def index_type(self, expr):
        t = self.expr_type(expr.target)
        it = self.expr_type(expr.index)
        if t == "List":
            if it not in ("Int", ANY):
                self.error("list index must be Int, found %s" % it, expr.index)
            return ANY
        if t == "String":
            if it not in ("Int", ANY):
                self.error("string index must be Int, found %s" % it, expr.index)
            return "String"
        if t == "Map":
            if it not in ("String", ANY):
                self.error("map key must be String, found %s" % it, expr.index)
            return ANY
        if t == ANY:
            return ANY
        self.error("cannot index a value of type %s" % t, expr)

    def member_type(self, expr):
        module, member = self.resolve_member_path(expr)
        found, _value = get_constant(module, member)
        if found:
            return "Float"
        native = get_native(module, member)
        if native is not None:
            self.error("'%s' must be called with (...)" % native.qualified, expr)
        self.error("module '%s' has no member '%s'" % (module, member), expr,
                   hint="available: %s" % _module_members(module))

    def call_type(self, expr):
        callee = expr.callee
        if isinstance(callee, ast.Ident):
            name = callee.name
            info = self.functions.get(name)
            if info is not None:
                self.check_args(expr, name, [(p[1]) for p in info.params], len(info.params))
                return info.ret
            native = get_native("core", name)
            if native is not None:
                self.check_native_args(expr, native)
                return native.ret
            var = self.lookup(name)
            if var is not None:
                self.error("'%s' is a value of type %s, not a function" % (name, var.type),
                           callee, hint="Silica v0.2.0 has no first-class functions")
            if name in self.modules:
                self.error("module '%s' needs a member, e.g. %s.%s"
                           % (name, name, native_names_hint(name)), callee)
            self.error("unknown function '%s'" % name, callee,
                       hint="declare it with 'sfn %s(...)'" % name)
        if isinstance(callee, ast.Member):
            module, member = self.resolve_member_path(callee)
            if member.startswith("__"):
                self.error("'%s.%s' is internal and cannot be called from Silica "
                           "source" % (module, member), callee,
                           hint="the compiler emits it for builder blocks")
            native = get_native(module, member)
            if native is None:
                if get_constant(module, member)[0]:
                    self.error("'%s.%s' is a constant, not a function"
                               % (module, member), callee)
                self.error("module '%s' has no function '%s'" % (module, member),
                           callee, hint="available: %s" % _module_members(module))
            self.check_native_args(expr, native)
            return native.ret
        self.error("cannot call this expression", expr,
                   hint="call a function by name, e.g. square(3)")

    def check_native_args(self, expr, native):
        n = len(expr.args)
        if n < native.min_args or n > native.max_args:
            expected = (str(native.min_args) if native.min_args == native.max_args
                        else "%d to %d" % (native.min_args, native.max_args))
            self.error("%s expects %s argument(s) but got %d"
                       % (native.qualified, expected, n), expr)
        types = [self.expr_type(arg) for arg in expr.args]
        for i, actual in enumerate(types):
            if i < len(native.params):
                expected = native.params[i]
            else:
                expected = native.params[-1]
            if expected == ANY:
                continue
            if not self.compatible(actual, expected):
                self.error("%s argument %d must be %s, found %s"
                           % (native.qualified, i + 1, expected, actual), expr.args[i])

    def check_args(self, expr, name, param_types, arity):
        if len(expr.args) != arity:
            self.error("function '%s' expects %d argument(s) but got %d"
                       % (name, arity, len(expr.args)), expr)
        for i, arg in enumerate(expr.args):
            actual = self.expr_type(arg)
            expected = param_types[i]
            if not self.compatible(actual, expected):
                self.error("argument %d of '%s' must be %s, found %s"
                           % (i + 1, name, expected, actual), arg,
                           hint=self.conversion_hint(actual, expected))

    # -- type relations ------------------------------------------------------
    def compatible(self, actual, expected):
        if expected == ANY or actual == ANY:
            return True
        if actual == expected:
            return True
        if actual == "Int" and expected == "Float":
            return True
        return False

    def conversion_hint(self, actual, expected):
        if actual == "Float" and expected == "Int":
            return "convert explicitly with int(value)"
        if actual == "Int" and expected == "String":
            return "convert explicitly with str(value)"
        if actual == "String" and expected == "Int":
            return "convert explicitly with int(value)"
        if expected == "Bool" or actual == "Bool":
            return "Silica does not coerce numbers to Bool"
        return None


def _flatten_member(expr):
    """`ui.lib.widgets.text` -> ["ui", "lib", "widgets", "text"]."""
    parts = []
    node = expr
    while isinstance(node, ast.Member):
        parts.append(node.name)
        node = node.obj
    if not isinstance(node, ast.Ident):
        return [], None
    parts.append(node.name)
    parts.reverse()
    return parts, None


def module_names():
    from .natives import MODULES
    return sorted(MODULES)


def native_names_hint(module):
    from .natives import native_names
    names = native_names(module)
    return names[0] if names else "..."

def _module_members(module):
    from .natives import constant_names, native_names
    parts = list(native_names(module)) + list(constant_names(module))
    return ", ".join(parts) if parts else "(none)"


def check(program, filename="<source>"):
    return Checker(program, filename).check()
