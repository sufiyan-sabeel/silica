"""Semantic analysis and static type checking for Silica.

The checker validates names, scopes, arities and types before any bytecode is
produced. Types are strings: "Int", "Float", "Bool", "String", "Unit", "List",
"Map", "Any". `List` and `Map` are containers of unknown element type in
v0.1.0 (no generics yet); their element type checks as "Any", which is
compatible with every type. That is a documented limitation, not an oversight.
"""

from . import ast
from .errors import SilicaTypeError
from . import types as T
from .tokens import BUILTIN_TYPES
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


def _type_names(text):
    """Every name in a type expression: 'List<T>' -> ['List', 'T']."""
    names = []
    try:
        base, arguments = T.parse(text)
    except T.TypeError_:
        return [text]
    names.append(base)
    for item in arguments:
        names.extend(_type_names(T.render(item)))
    return names


class TypeInfo:
    """A declared struct or class, as the checker sees it."""

    __slots__ = ("name", "is_struct", "field_order", "fields", "methods", "node",
                 "type_params")

    def __init__(self, name, is_struct, node=None):
        self.name = name
        self.is_struct = is_struct
        self.field_order = []          # declaration order, used by construction
        self.fields = {}               # name -> (type, is_private)
        self.methods = {}              # name -> FuncInfo (params exclude self)
        self.node = node
        self.type_params = []          # list of (name, constraint)

    def field_names(self):
        return ", ".join("%s: %s" % (name, self.fields[name][0])
                         for name in self.field_order)


class FuncInfo:
    __slots__ = ("name", "params", "ret", "node", "is_static", "is_private",
                 "type_params")

    def __init__(self, name, params, ret, node):
        self.name = name
        self.params = params      # list of (name, type)
        self.ret = ret
        self.node = node
        self.is_static = False
        self.is_private = False
        self.type_params = []      # list of (name, constraint)


class Checker:
    def __init__(self, program, filename="<source>", require_main=True,
                 pre_globals=None):
        self.program = program
        self.filename = filename
        self.require_main = require_main
        # globals carried in from an earlier compile (REPL session state)
        self.pre_globals = list(pre_globals or [])
        self.functions = {}
        self.types = {}
        self.globals = {}
        self.modules = set()
        self.scopes = []
        self.current_func = None
        self.current_type = None       # the class whose method body is being checked
        self.type_vars = {}            # type parameter -> constraint, in scope
        self.pending_annotation = None  # declared type of the binding being checked
        # builder-block context: how deep we are inside `call { ... }` blocks and
        # inside an event body (`ui.on(...) { ... }`), both reset per function
        self.builder_depth = 0
        self.event_depth = 0
        # how many loops enclose the statement being checked; `break` and
        # `continue` are only legal when this is at least 1
        self.loop_depth = 0

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
        # pass 0a: register every type *name* first, so a type may be used by a
        # type declared above it (Node { next: Point } with Point below Node).
        for stmt in self.program.stmts:
            if isinstance(stmt, (ast.StructDecl, ast.ClassDecl)):
                self.declare_type_name(stmt)
        # pass 0b: then fill in fields and methods
        for stmt in self.program.stmts:
            if isinstance(stmt, (ast.StructDecl, ast.ClassDecl)):
                self.fill_type(stmt)
        for stmt in self.program.stmts:
            if isinstance(stmt, ast.FuncDecl):
                self.declare_function(stmt)

        # pass 2: globals, then bodies
        for name, type_name in self.pre_globals:
            self.globals.setdefault(name, VarInfo(name, type_name, False))
        for stmt in self.program.stmts:
            if isinstance(stmt, ast.LetStmt):
                self.check_let(stmt, top_level=True)
            elif isinstance(stmt, (ast.UseStmt, ast.FuncDecl, ast.StructDecl,
                                   ast.ClassDecl)):
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
            elif isinstance(stmt, ast.ClassDecl):
                for method in stmt.methods:
                    self.check_method(method, self.types[stmt.name])

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
            self.error("only standard-library modules have members in Silica v0.8.0",
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
        if decl.name in self.types:
            self.error("'%s' is already declared as a type" % decl.name, decl,
                       hint="a type and a function cannot share a name")
        if decl.name in self.functions:
            self.error("function '%s' is already declared" % decl.name, decl)
        if decl.name in ("sprint", "dit", "input"):
            self.error("'%s' is a reserved built-in name" % decl.name, decl)
        type_params = self.declare_type_params(decl)
        outer_vars = self.type_vars
        self.type_vars = {name: constraint for name, constraint in type_params}
        params = []
        seen = set()
        for entry in decl.params:
            name, ptype = entry[0], entry[1]
            if name in seen:
                self.error("duplicate parameter '%s' in function '%s'" % (name, decl.name), decl)
            seen.add(name)
            if ptype is not None:
                self.validate_type(ptype, decl)
            params.append((name, ptype or ANY))
        if decl.ret_type is not None:
            self.validate_type(decl.ret_type, decl)
        ret = decl.ret_type or "Unit"
        self.type_vars = outer_vars
        info = FuncInfo(decl.name, params, ret, decl)
        info.type_params = type_params
        self.functions[decl.name] = info

    ARITY = {"List": (0, 1), "Map": (0, 2)}   # allowed counts, checked below

    def validate_type(self, name, node):
        """A type annotation must be well formed and declared (E20, E30, E31)."""
        try:
            base, arguments = T.parse(name)
        except T.TypeError_ as exc:
            self.error("malformed type %r: %s" % (name, exc), node)
        arguments = [T.render(item) for item in arguments]
        if base in self.type_vars and not arguments:
            return name
        if base in BUILTIN_TYPES:
            low, high = self.ARITY.get(base, (0, 0))
            allowed = {low, high} if low != high else {low}
            if len(arguments) not in allowed:
                expected = ("%d" % low if low == high else "%d or %d" % (low, high))
                self.error("%s expects %s type argument(s), got %d"
                           % (base, expected, len(arguments)), node,
                           hint="write %s%s" % (base, "<...>" if high else ""))
            for item in arguments:
                self.validate_type(item, node)
            return name
        info = self.types.get(base)
        if info is None:
            import difflib
            known = sorted(BUILTIN_TYPES) + sorted(self.types)
            suggestion = difflib.get_close_matches(base, known, 1)
            hint = ("did you mean '%s'?" % suggestion[0]) if suggestion else \
                "available types: %s" % ", ".join(known)
            self.error("unknown type '%s'" % base, node, hint=hint)
        declared = len(info.type_params)
        if len(arguments) != declared:
            self.error("%s expects %d type argument(s), got %d"
                       % (base, declared, len(arguments)), node,
                       hint="declare it as %s%s" % (
                           base, "<%s>" % ", ".join(p[0] for p in info.type_params)
                           if declared else ""))
        for item in arguments:
            self.validate_type(item, node)
        return name

    def declare_type_name(self, decl):
        if decl.name in self.types:
            self.error("type '%s' is already declared" % decl.name, decl)
        if decl.name in BUILTIN_TYPES:
            self.error("'%s' is a built-in type and cannot be redeclared" % decl.name,
                       decl)
        if decl.name in self.functions:
            self.error("'%s' is already declared as a function" % decl.name, decl,
                       hint="a type and a function cannot share a name")
        info = TypeInfo(decl.name, isinstance(decl, ast.StructDecl), decl)
        info.type_params = self.declare_type_params(decl)
        self.types[decl.name] = info

    def fill_type(self, decl):
        info = self.types[decl.name]
        outer_vars = self.type_vars
        self.type_vars = {name: constraint for name, constraint in info.type_params}
        seen = set()
        for field in decl.fields:
            if field.name in seen:
                self.error("'%s' is declared twice in %s" % (field.name, decl.name),
                           field)
            seen.add(field.name)
            self.validate_type(field.type_ann, field)
            info.field_order.append(field.name)
            info.fields[field.name] = (field.type_ann, field.is_private)
        for method in getattr(decl, "methods", []):
            if method.name in info.methods:
                self.error("method '%s' is declared twice in %s"
                           % (method.name, decl.name), method)
            if method.name in info.fields:
                self.error("'%s' is both a field and a method in %s"
                           % (method.name, decl.name), method)
            params = []
            names = set()
            for entry in method.params:
                name, ptype = entry[0], entry[1]
                if name in names:
                    self.error("duplicate parameter '%s' in %s.%s"
                               % (name, decl.name, method.name), method)
                names.add(name)
                if ptype is not None:
                    self.validate_type(ptype, method)
                params.append((name, ptype or ANY))
            if method.ret_type is not None:
                self.validate_type(method.ret_type, method)
            info.methods[method.name] = FuncInfo(method.name, params,
                                                 method.ret_type or "Unit", method)
            info.methods[method.name].is_static = method.is_static
            info.methods[method.name].is_private = method.is_private
            if method.is_static and info.type_params:
                names = {name for name, _c in info.type_params}
                signature = [p[1] for p in params] + ([method.ret_type]
                                                      if method.ret_type else [])
                for entry in signature:
                    if entry is None:
                        continue
                    if any(part in names for part in _type_names(entry)):
                        self.error(
                            "%s.%s is static and cannot use the type parameter(s) %s"
                            % (decl.name, method.name, ", ".join(sorted(names))),
                            method,
                            hint="make it an instance method, or give it its own "
                                 "type parameters")
        self.type_vars = outer_vars
        self.types[decl.name] = info

    def check_method(self, decl, type_info):
        """Check one method body: `self` is bound unless the method is static."""
        info = type_info.methods[decl.name]
        outer_func, outer_type = self.current_func, self.current_type
        outer_builder, outer_event = self.builder_depth, self.event_depth
        outer_loop = self.loop_depth
        self.builder_depth = 0
        self.event_depth = 0
        self.loop_depth = 0
        self.current_func = info
        self.current_type = type_info
        outer_vars = self.type_vars
        self.type_vars = {name: constraint for name, constraint in type_info.type_params}
        self.push_scope()
        if not decl.is_static:
            self.declare(VarInfo("self", type_info.name, True, decl.line, decl.col), decl)
        for name, ptype, line, col in decl.params:
            self.declare(VarInfo(name, ptype or ANY, True, line, col), decl)
        self.check_block(decl.body, new_scope=False)
        if info.ret != "Unit" and not self.always_returns(decl.body):
            self.error(
                "%s.%s can finish without returning a value of type %s"
                % (type_info.name, decl.name, info.ret), decl,
                hint="every path must end in 'ret' (or 'halt')")
        self.pop_scope()
        self.type_vars = outer_vars
        self.current_func, self.current_type = outer_func, outer_type
        self.builder_depth, self.event_depth = outer_builder, outer_event
        self.loop_depth = outer_loop

    def declare_type_params(self, decl):
        """Validate and record a declaration's type parameters."""
        declared = []
        seen = set()
        for name, constraint, line, col in getattr(decl, "type_params", []) or []:
            if name in seen:
                self.error("duplicate type parameter '%s'" % name, decl)
            seen.add(name)
            if name in BUILTIN_TYPES or name in self.types:
                self.error("type parameter '%s' shadows a declared type" % name, decl,
                           hint="use a name that is not a type, e.g. T")
            if constraint is not None and constraint not in T.KINDS:
                self.error("unknown constraint '%s'" % constraint, decl,
                           hint="available constraints: %s" % ", ".join(sorted(T.KINDS)))
            declared.append((name, constraint))
        return declared

    def check_function(self, decl):
        info = self.functions[decl.name]
        outer = self.current_func
        outer_builder, outer_event = self.builder_depth, self.event_depth
        outer_loop = self.loop_depth
        self.builder_depth = 0
        self.event_depth = 0
        self.loop_depth = 0
        self.current_func = info
        outer_vars = self.type_vars
        self.type_vars = {name: constraint for name, constraint in info.type_params}
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
        self.type_vars = outer_vars
        self.current_func = outer
        self.builder_depth, self.event_depth = outer_builder, outer_event
        self.loop_depth = outer_loop

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
            self.loop_depth += 1
            self.check_block(stmt.body)
            self.loop_depth -= 1
        elif isinstance(stmt, ast.ForStmt):
            iterable = self.expr_type(stmt.iterable)
            if T.base(iterable) == "List":
                elements = T.args(iterable)
                var_type = elements[0] if elements else ANY
            elif iterable == "String":
                var_type = "String"
            elif T.base(iterable) == "Map":
                keys = T.args(iterable)
                var_type = keys[0] if keys else "String"
            elif iterable == ANY:
                var_type = ANY
            else:
                self.error("'per' needs a List, Map or String, found %s" % iterable,
                           stmt.iterable)
            self.push_scope()
            self.declare(VarInfo(stmt.var, var_type, True), stmt)
            self.loop_depth += 1
            self.check_block(stmt.body, new_scope=False)
            self.loop_depth -= 1
            self.pop_scope()
        elif isinstance(stmt, ast.ReturnStmt):
            self.check_return(stmt)
        elif isinstance(stmt, ast.HaltStmt):
            if stmt.code is not None:
                t = self.expr_type(stmt.code)
                if t not in ("Int", ANY):
                    self.error("'halt' exit code must be Int, found %s" % t, stmt.code)
        elif isinstance(stmt, ast.BreakStmt):
            self.check_loop_jump(stmt, "break")
        elif isinstance(stmt, ast.ContinueStmt):
            self.check_loop_jump(stmt, "continue")
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

    def check_loop_jump(self, stmt, keyword):
        """`break` and `continue` need an enclosing loop, and may not escape a
        builder block: a widget tree is closed structurally."""
        if self.builder_depth > 0:
            self.error("'%s' inside a builder block is not allowed; close the block "
                       "first" % keyword, stmt,
                       hint="a widget tree is closed structurally, so leaving a loop "
                            "from inside one is almost always a mistake")
        if self.loop_depth == 0:
            self.error("'%s' is only allowed inside a loop" % keyword, stmt,
                       hint="put it inside the body of a 'tant' or 'per' loop")

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
        if declared is not None:
            self.validate_type(declared, stmt)
        outer_pending = self.pending_annotation
        self.pending_annotation = declared
        actual = self.expr_type(stmt.init)
        self.pending_annotation = outer_pending
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
        if stmt.target is not None:
            member = stmt.target
            obj_type = self.expr_type(member.obj)
            if obj_type == ANY:
                self.expr_type(stmt.value)
                return
            info = self.user_type(obj_type)
            if info is None:
                self.error("cannot assign to a field of %s" % obj_type, member)
            if member.name not in info.fields:
                self.error("%s has no field '%s'" % (info.name, member.name), member,
                           hint=self._suggest(member.name, list(info.fields)))
            field_type, is_private = info.fields[member.name]
            if is_private and self.current_type is not info:
                self.error("'%s' is private to %s" % (member.name, info.name), member)
            actual = self.expr_type(stmt.value)
            if not self.compatible(actual, field_type):
                self.error("cannot assign %s to field '%s' of type %s"
                           % (actual, member.name, field_type), stmt.value,
                           hint=self.conversion_hint(actual, field_type))
            return
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
            element_types = [self.expr_type(item) for item in expr.items]
            if not element_types:
                return "List"
            first = element_types[0]
            if all(t == first for t in element_types) and first != ANY:
                return T.make("List", [first])
            # a heterogeneous literal keeps the unparameterised type
            return "List"
        if isinstance(expr, ast.MapLit):
            value_types = [self.expr_type(value) for _key, value in expr.pairs]
            if not value_types:
                return "Map"
            first = value_types[0]
            if all(t == first for t in value_types) and first != ANY:
                return T.make("Map", ["String", first])
            return "Map"
        if isinstance(expr, ast.Index):
            return self.index_type(expr)
        self.error("unsupported expression", expr)

    def ident_type(self, expr):
        if expr.name == "self":
            if self.current_type is None:
                self.error("'self' is only available inside a method", expr)
            if self.current_func is not None and self.current_func.is_static:
                self.error("a static method cannot use 'self'", expr,
                           hint="remove 'static', or pass the value in as a parameter")
        if expr.name in self.types:
            self.error("'%s' is a type, not a value" % expr.name, expr,
                       hint="construct it with %s(...)" % expr.name)
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

    def require_kind(self, type_name, kind, node, what):
        """Gate an operation on a type parameter behind its constraint (E34)."""
        if type_name not in self.type_vars:
            return                       # a concrete type: checked normally
        constraint = self.type_vars[type_name]
        if constraint is not None and (constraint == kind or T.satisfies(kind, constraint)):
            return
        if constraint is None:
            self.error("'%s' cannot be used with a %s value: type parameter %s is "
                       "unconstrained" % (what, type_name, type_name), node,
                       hint="declare it as <%s: %s>" % (type_name, kind))
        self.error("'%s' needs a %s value, but %s is only constrained to %s"
                   % (what, kind, type_name, constraint), node,
                   hint="declare it as <%s: %s>" % (type_name, kind))

    def binary_type(self, expr):
        op = expr.op
        lt = self.expr_type(expr.left)
        rt = self.expr_type(expr.right)
        if lt in self.type_vars or rt in self.type_vars:
            parameter = lt if lt in self.type_vars else rt
            if op in ("+", "-", "*", "/", "%"):
                self.require_kind(parameter, "Numeric", expr, op)
            elif op in ("<", "<=", ">", ">="):
                self.require_kind(parameter, "Orderable", expr, op)
            if op in ("+", "-", "*", "/", "%", "<", "<=", ">", ">="):
                return "Bool" if op in ("<", "<=", ">", ">=") else parameter

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
            # a bare container compares with any parameterisation of itself
            if T.base(lt) == T.base(rt):
                return "Bool"
            self.error("cannot compare %s with %s using '%s'" % (lt, rt, op), expr)
        if op in ("<", "<=", ">", ">="):
            if lt == ANY or rt == ANY:
                return "Bool"
            if lt in NUMERIC and rt in NUMERIC:
                return "Bool"
            if T.base(lt) == T.base(rt) == "String":
                return "Bool"
            self.error("cannot order %s and %s with '%s'" % (lt, rt, op), expr,
                       hint="ordering works on numbers and Strings")
        if op == "+":
            if lt == ANY or rt == ANY:
                return ANY
            if lt == "String" and rt == "String":
                return "String"
            if T.base(lt) == "List" and T.base(rt) == "List":
                left_args, right_args = T.args(lt), T.args(rt)
                if left_args and right_args and left_args[0] != right_args[0]:
                    self.error("cannot add %s and %s" % (lt, rt), expr)
                if left_args:
                    return T.make("List", [left_args[0]])
                if right_args:
                    return T.make("List", [right_args[0]])
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
        if T.base(t) == "List":
            if it not in ("Int", ANY):
                self.error("list index must be Int, found %s" % it, expr.index)
            element = T.args(t)
            return element[0] if element else ANY
        if t == "String":
            if it not in ("Int", ANY):
                self.error("string index must be Int, found %s" % it, expr.index)
            return "String"
        if T.base(t) == "Map":
            parts = T.args(t)
            key_type = parts[0] if parts else "String"
            if it not in (key_type, ANY) and not self.compatible(it, key_type):
                self.error("map key must be %s, found %s" % (key_type, it), expr.index)
            return parts[1] if len(parts) > 1 else ANY
        if t == ANY:
            return ANY
        self.error("cannot index a value of type %s" % t, expr)

    def _suggest(self, name, candidates):
        import difflib
        matches = difflib.get_close_matches(name, list(candidates), 1)
        return ("did you mean '%s'?" % matches[0]) if matches else None

    def user_type(self, type_name):
        """The TypeInfo for a type expression whose base is a declared type."""
        if not isinstance(type_name, str):
            return None
        try:
            return self.types.get(T.base(type_name))
        except T.TypeError_:
            return None

    def is_module_path(self, node):
        """True when `node` names a module, or a dotted path starting at one."""
        if isinstance(node, ast.Ident):
            return (node.name in self.modules or self.is_imported(node.name)
                    or module_exists(node.name) or node.name in PLANNED_MODULES)
        if isinstance(node, ast.Member):
            return self.is_module_path(node.obj)
        return False

    def type_member(self, expr, want_call):
        """Resolve `Type.name` or `instance.name`. Returns a type, or None.

        Returns None only when the object is not a declared type or an instance
        of one, so the caller can fall through to module resolution.
        """
        obj = expr.obj
        # static access: Type.name
        if isinstance(obj, ast.Ident) and obj.name in self.types:
            info = self.types[obj.name]
            method = info.methods.get(expr.name)
            if method is None:
                self.error("%s has no member '%s'" % (info.name, expr.name), expr,
                           hint=self._suggest(expr.name, list(info.methods)))
            if not method.is_static:
                self.error("%s.%s is an instance method" % (info.name, expr.name), expr,
                           hint="call it on an instance, e.g. value.%s(...)" % expr.name)
            if method.is_private and self.current_type is not info:
                self.error("'%s' is private to %s" % (expr.name, info.name), expr)
            if not want_call:
                self.error("'%s.%s' must be called with (...)" % (info.name, expr.name),
                           expr)
            return method

        if self.is_module_path(obj):
            # A module reference (or a dotted path rooted at one): leave it to
            # the module path, which reports a missing import with the right
            # message instead of "unknown name".
            return None

        obj_type = self.expr_type(obj)
        if obj_type == ANY:
            # A List/Map element is `Any` until generics land, so a member of an
            # Any-typed value is resolved at run time and typed `Any`.
            return ANY
        info = self.user_type(obj_type)
        if info is None:
            return None
        if expr.name in info.fields:
            field_type, is_private = info.fields[expr.name]
            if is_private and self.current_type is not info:
                self.error("'%s' is private to %s" % (expr.name, info.name), expr)
            if want_call:
                self.error("'%s' is a field of %s, not a method"
                           % (expr.name, info.name), expr)
            return field_type
        method = info.methods.get(expr.name)
        if method is None:
            self.error("%s has no member '%s'" % (info.name, expr.name), expr,
                       hint=self._suggest(expr.name,
                                          list(info.fields) + list(info.methods)))
        if method.is_private and self.current_type is not info:
            self.error("'%s' is private to %s" % (expr.name, info.name), expr)
        if method.is_static:
            self.error("%s.%s is a static method" % (info.name, expr.name), expr,
                       hint="call it on the type: %s.%s(...)" % (info.name, expr.name))
        if not want_call:
            self.error("'%s.%s' must be called with (...)" % (info.name, expr.name), expr)
        return method

    def member_type(self, expr):
        resolved = self.type_member(expr, want_call=False)
        if resolved is not None and isinstance(resolved, str):
            return resolved
        module, member = self.resolve_member_path(expr)
        found, _value = get_constant(module, member)
        if found:
            return "Float"
        native = get_native(module, member)
        if native is not None:
            self.error("'%s' must be called with (...)" % native.qualified, expr)
        self.error("module '%s' has no member '%s'" % (module, member), expr,
                   hint="available: %s" % _module_members(module))

    def check_method_args(self, expr, label, method):
        params = [p[1] for p in method.params]
        if len(expr.args) != len(params):
            self.error("%s expects %d argument(s) but got %d"
                       % (label, len(params), len(expr.args)), expr)
        for index, arg in enumerate(expr.args):
            actual = self.expr_type(arg)
            if not self.compatible(actual, params[index]):
                self.error("argument %d of %s must be %s, found %s"
                           % (index + 1, label, params[index], actual), arg,
                           hint=self.conversion_hint(actual, params[index]))

    def infer_generic_call(self, expr, info):
        """Infer a generic function's type arguments from its arguments (E32)."""
        if len(expr.args) != len(info.params):
            self.error("function '%s' expects %d argument(s) but got %d"
                       % (info.name, len(info.params), len(expr.args)), expr)
        mapping = {}
        for index, arg in enumerate(expr.args):
            actual = self.expr_type(arg)
            expected = info.params[index][1]
            if not T.unify(expected, actual, mapping):
                self.error("argument %d of '%s' must be %s, found %s"
                           % (index + 1, info.name, expected, actual), arg)
        missing = [name for name, _c in info.type_params if name not in mapping]
        if missing:
            self.error("cannot infer type parameter(s) %s for '%s'"
                       % (", ".join(missing), info.name), expr,
                       hint="pass an argument that determines it")
        for name, constraint in info.type_params:
            if not T.satisfies(mapping[name], constraint):
                self.error("type argument %s = %s does not satisfy %s"
                           % (name, mapping[name], constraint), expr,
                           hint="%s accepts %s" % (constraint,
                                                   ", ".join(T.KINDS[constraint])))
        return T.substitute(info.ret, mapping)

    def construct_type(self, expr, info):
        """`Point(1, 2)` / `Box(1)` — positional construction (E21/E22/E33)."""
        expected = info.field_order
        if len(expr.args) != len(expected):
            self.error("%s expects %d argument(s) (%s), got %d"
                       % (info.name, len(expected), info.field_names(),
                          len(expr.args)), expr,
                       hint="arguments are positional, in field declaration order")
        mapping = {}
        if info.type_params and self.pending_annotation:
            # `let s: Stack<String> = Stack([])` — the annotation supplies what
            # the arguments cannot, which is the common empty-container case.
            try:
                if T.base(self.pending_annotation) == info.name:
                    T.unify(T.make(info.name, [name for name, _c in info.type_params]),
                            self.pending_annotation, mapping)
            except T.TypeError_:
                pass
        for index, arg in enumerate(expr.args):
            actual = self.expr_type(arg)
            field_type = info.fields[expected[index]][0]
            if info.type_params:
                if not T.unify(field_type, actual, mapping):
                    self.error("argument %d of %s must be %s, found %s"
                               % (index + 1, info.name, field_type, actual), arg,
                               hint="field '%s' is declared as %s"
                                    % (expected[index], field_type))
            elif not self.compatible(actual, field_type):
                self.error("argument %d of %s must be %s, found %s"
                           % (index + 1, info.name, field_type, actual), arg,
                           hint="field '%s' is declared as %s: %s"
                                % (expected[index], field_type,
                                   self.conversion_hint(actual, field_type) or ""))
        if not info.type_params:
            return info.name
        missing = [name for name, _c in info.type_params if name not in mapping]
        if missing:
            self.error("cannot infer type parameter(s) %s for %s"
                       % (", ".join(missing), info.name), expr,
                       hint="pass an argument that determines it, or annotate the "
                            "argument with the type you mean")
        for name, constraint in info.type_params:
            if not T.satisfies(mapping[name], constraint):
                self.error("type argument %s = %s does not satisfy %s"
                           % (name, mapping[name], constraint), expr,
                           hint="%s accepts %s" % (constraint,
                                                   ", ".join(T.KINDS[constraint])))
        return T.make(info.name, [mapping[name] for name, _c in info.type_params])

    def call_type(self, expr):
        callee = expr.callee
        if isinstance(callee, ast.Ident) and callee.name in self.types:
            return self.construct_type(expr, self.types[callee.name])
        if isinstance(callee, ast.Member):
            resolved = self.type_member(callee, want_call=True)
            if resolved == ANY:
                for arg in expr.args:
                    self.expr_type(arg)
                return ANY
            if resolved is not None and not isinstance(resolved, str):
                mapping = {}
                receiver_type = None
                if not (isinstance(callee.obj, ast.Ident)
                        and callee.obj.name in self.types):
                    receiver_type = self.expr_type(callee.obj)
                    owner = self.user_type(receiver_type)
                    if owner is not None and owner.type_params:
                        T.unify(T.make(owner.name,
                                       [name for name, _c in owner.type_params]),
                                receiver_type, mapping)
                label = "%s.%s" % (
                    callee.obj.name if isinstance(callee.obj, ast.Ident)
                    else (receiver_type or "value"), callee.name)
                if mapping:
                    substituted = FuncInfo(resolved.name,
                                           [(n, T.substitute(t, mapping))
                                            for n, t in resolved.params],
                                           T.substitute(resolved.ret, mapping),
                                           resolved.node)
                    self.check_method_args(expr, label, substituted)
                    return substituted.ret
                self.check_method_args(expr, label, resolved)
                return resolved.ret
        if isinstance(callee, ast.Ident):
            name = callee.name
            info = self.functions.get(name)
            if info is not None and info.type_params:
                return self.infer_generic_call(expr, info)
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
                           callee, hint="Silica v0.8.0 has no first-class functions")
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
        try:
            actual_base, actual_args = T.parse(actual)
            expected_base, expected_args = T.parse(expected)
        except T.TypeError_:
            return False
        if actual_base != expected_base:
            return actual == "Int" and expected == "Float"
        if not expected_args or not actual_args:
            # A bare container type accepts any parameterisation (and an
            # unannotated literal is accepted where a parameterised type is
            # expected). Annotate both sides to get the check.
            return True
        if len(actual_args) != len(expected_args):
            return False
        # type arguments are invariant: List<Int> is not a List<Float>
        return all(T.render(a) == T.render(e) or T.render(a) == ANY
                   or T.render(e) == ANY
                   for a, e in zip(actual_args, expected_args))

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
