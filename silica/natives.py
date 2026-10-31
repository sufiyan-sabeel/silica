"""Native (built-in) function registry for Silica.

Modules:

  core         always in scope, no `use` needed
  math         `use math`
  string       `use string`
  collections  `use collections`

Each native records the parameter types and return type the static checker
needs, plus a Python implementation the VM calls. Type `Any` in a signature
means "any Silica value" and is accepted by the checker without inspection;
the implementation still validates at runtime and raises a located runtime
error on a mismatch.
"""

import math as _math

from .errors import SilicaRuntimeError

I64_MIN = -(2 ** 63)
I64_MAX = 2 ** 63 - 1


def i64(value):
    """Wrap a Python int into signed 64-bit range (documented Int overflow)."""
    value &= (2 ** 64 - 1)
    if value >= 2 ** 63:
        value -= 2 ** 64
    return value


def type_name(value):
    if value is None:
        return "Unit"
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int"
    if isinstance(value, float):
        return "Float"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        return "List"
    if isinstance(value, dict):
        return "Map"
    if isinstance(value, Iterator):
        return "Iterator"
    return "Any"


def format_float(value):
    if value != value:  # NaN
        return "nan"
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    text = repr(float(value))
    return text


def format_value(value):
    """How `sprint` / `dit` render a value (see docs/LANGUAGE_SPEC.md)."""
    if value is None:
        return "unit"
    if isinstance(value, bool):
        return "oui" if value else "nein"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_float(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "[" + ", ".join(_format_inner(v) for v in value) + "]"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            parts.append("%s: %s" % (_format_inner(k), _format_inner(v)))
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, Iterator):
        return "<iterator>"
    return str(value)


def _format_inner(value):
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return format_value(value)


class Iterator:
    """Runtime-only iterator used by the `per` loop. Not a user-visible type."""

    __slots__ = ("items", "index")

    def __init__(self, items):
        self.items = items
        self.index = 0

    def has_next(self):
        return self.index < len(self.items)


class Native:
    __slots__ = ("module", "name", "params", "ret", "fn", "min_args", "max_args",
                 "requires", "path_arg", "accepts_block")

    def __init__(self, module, name, params, ret, fn, min_args=None, max_args=None,
                 requires=None, path_arg=None, accepts_block=False):
        self.module = module
        self.name = name
        self.params = params
        self.ret = ret
        self.fn = fn
        self.min_args = len(params) if min_args is None else min_args
        self.max_args = len(params) if max_args is None else max_args
        # A privileged native names the capability the VM must authorise before
        # the body runs, and which argument holds the path. `requires=None`
        # means the native touches nothing outside the VM's own state.
        self.requires = requires
        self.path_arg = path_arg
        # Builder metadata: True when the native may be followed by a { ... }
        # block (a UI widget), False for an ordinary function.
        self.accepts_block = accepts_block

    @property
    def qualified(self):
        return "%s.%s" % (self.module, self.name)


# --- runtime helpers ---------------------------------------------------------
def _fail(message, hint=None):
    raise SilicaRuntimeError(message, hint=hint)


def _check_arity(native, args):
    n = len(args)
    if n < native.min_args or n > native.max_args:
        _fail("%s expects %s argument(s) but got %d" % (
            native.qualified, _arity_text(native), n))


def _arity_text(native):
    if native.min_args == native.max_args:
        return str(native.min_args)
    return "%d to %d" % (native.min_args, native.max_args)


def _need_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("%s expects an Int, got %s" % (name, type_name(value)))
    return value


def _need_number(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("%s expects a number, got %s" % (name, type_name(value)))
    return value


def _need_string(name, value):
    if not isinstance(value, str):
        _fail("%s expects a String, got %s" % (name, type_name(value)))
    return value


def _need_list(name, value):
    if not isinstance(value, list):
        _fail("%s expects a List, got %s" % (name, type_name(value)))
    return value


def _need_map(name, value):
    if not isinstance(value, dict):
        _fail("%s expects a Map, got %s" % (name, type_name(value)))
    return value


# --- core implementations ----------------------------------------------------
def _n_sprint(ctx, args):
    ctx.write(format_value(args[0]) + "\n")
    return None


def _n_dit(ctx, args):
    ctx.write(format_value(args[0]))
    return None


def _n_input(ctx, args):
    ctx.write(_need_string("input", args[0]))
    ctx.flush()
    line = ctx.readline()
    if line is None:
        _fail("input reached end of input",
              hint="pipe more data in, or check the program's input handling")
    return line


def _n_type_of(ctx, args):
    return type_name(args[0])


def _n_assert(ctx, args):
    cond = args[0]
    if not isinstance(cond, bool):
        _fail("assert expects a Bool, got %s" % type_name(cond))
    if not cond:
        msg = "assertion failed"
        if len(args) > 1:
            msg = "assertion failed: " + _need_string("assert", args[1])
        _fail(msg)
    return None


def _n_str(ctx, args):
    return format_value(args[0])


def _n_int(ctx, args):
    value = args[0]
    if isinstance(value, bool):
        _fail("int expects a String, Float or Int, got Bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            _fail("cannot convert %s to Int" % format_float(value))
        return i64(int(value))
    if isinstance(value, str):
        text = value.strip()
        try:
            return i64(int(text, 10))
        except ValueError:
            _fail("cannot convert %r to Int" % value,
                  hint="int(\"...\") needs a plain base-10 integer")
    _fail("int expects a String, Float or Int, got %s" % type_name(value))


def _n_float(ctx, args):
    value = args[0]
    if isinstance(value, bool):
        _fail("float expects a String, Int or Float, got Bool")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            _fail("cannot convert %r to Float" % value)
    _fail("float expects a String, Int or Float, got %s" % type_name(value))


def _n_len(ctx, args):
    value = args[0]
    if isinstance(value, (list, str)):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    _fail("len expects a List, Map or String, got %s" % type_name(value))


def _n_range(ctx, args):
    if len(args) == 1:
        start, stop, step = 0, _need_int("range", args[0]), 1
    elif len(args) == 2:
        start, stop, step = _need_int("range", args[0]), _need_int("range", args[1]), 1
    else:
        start, stop = _need_int("range", args[0]), _need_int("range", args[1])
        step = _need_int("range", args[2])
    if step == 0:
        _fail("range step must not be zero")
    return [i64(i) for i in range(start, stop, step)]


def _n_push(ctx, args):
    lst = _need_list("push", args[0])
    lst.append(args[1])
    return None


def _n_keys(ctx, args):
    return list(_need_map("keys", args[0]).keys())


def _n_values(ctx, args):
    return list(_need_map("values", args[0]).values())


def _n_has(ctx, args):
    container, key = args[0], args[1]
    if isinstance(container, dict):
        if not isinstance(key, str):
            _fail("has on a Map expects a String key, got %s" % type_name(key))
        return key in container
    if isinstance(container, list):
        return any(_value_eq(item, key) for item in container)
    if isinstance(container, str):
        return _need_string("has", key) in container
    _fail("has expects a List, Map or String, got %s" % type_name(container))


def _value_eq(a, b):
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_value_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_value_eq(a[k], b[k]) for k in a)
    return a == b


# --- math --------------------------------------------------------------------
def _m_abs(ctx, args):
    v = _need_number("math.abs", args[0])
    return i64(abs(v)) if isinstance(v, int) else abs(v)


def _m_min(ctx, args):
    a, b = _need_number("math.min", args[0]), _need_number("math.max", args[1])
    if isinstance(a, float) or isinstance(b, float):
        return float(min(a, b))
    return i64(min(a, b))


def _m_max(ctx, args):
    a, b = _need_number("math.min", args[0]), _need_number("math.max", args[1])
    if isinstance(a, float) or isinstance(b, float):
        return float(max(a, b))
    return i64(max(a, b))


def _m_sqrt(ctx, args):
    v = _need_number("math.sqrt", args[0])
    if v < 0:
        _fail("math.sqrt of a negative number: %s" % format_float(float(v)))
    return _math.sqrt(v)


def _m_pow(ctx, args):
    base = _need_number("math.pow", args[0])
    exp = _need_number("math.pow", args[1])
    try:
        return float(_math.pow(base, exp))
    except OverflowError:
        _fail("math.pow overflow")


def _m_floor(ctx, args):
    v = _need_number("math.floor", args[0])
    if isinstance(v, int):
        return v
    if v != v or v in (float("inf"), float("-inf")):
        _fail("math.floor needs a finite number")
    return i64(int(_math.floor(v)))


def _m_ceil(ctx, args):
    v = _need_number("math.ceil", args[0])
    if isinstance(v, int):
        return v
    if v != v or v in (float("inf"), float("-inf")):
        _fail("math.ceil needs a finite number")
    return i64(int(_math.ceil(v)))


def _m_round(ctx, args):
    v = _need_number("math.round", args[0])
    if isinstance(v, int):
        return v
    if v != v or v in (float("inf"), float("-inf")):
        _fail("math.round needs a finite number")
    # round half away from zero, unlike Python's banker's rounding
    return i64(int(_math.floor(v + 0.5)) if v >= 0 else int(_math.ceil(v - 0.5)))


# --- string ------------------------------------------------------------------
def _s_split(ctx, args):
    s = _need_string("string.split", args[0])
    sep = _need_string("string.split", args[1])
    if sep == "":
        _fail("string.split needs a non-empty separator")
    return s.split(sep)


def _s_join(ctx, args):
    lst = _need_list("string.join", args[0])
    sep = _need_string("string.join", args[1])
    for item in lst:
        if not isinstance(item, str):
            _fail("string.join expects a List of String, found %s" % type_name(item))
    return sep.join(lst)


def _s_trim(ctx, args):
    return _need_string("string.trim", args[0]).strip()


def _s_replace(ctx, args):
    s = _need_string("string.replace", args[0])
    old = _need_string("string.replace", args[1])
    new = _need_string("string.replace", args[2])
    if old == "":
        _fail("string.replace needs a non-empty search string")
    return s.replace(old, new)


def _s_contains(ctx, args):
    s = _need_string("string.contains", args[0])
    sub = _need_string("string.contains", args[1])
    return sub in s


def _s_starts_with(ctx, args):
    return _need_string("string.starts_with", args[0]).startswith(
        _need_string("string.starts_with", args[1]))


def _s_ends_with(ctx, args):
    return _need_string("string.ends_with", args[0]).endswith(
        _need_string("string.ends_with", args[1]))


def _s_upper(ctx, args):
    return _need_string("string.upper", args[0]).upper()


def _s_lower(ctx, args):
    return _need_string("string.lower", args[0]).lower()


# --- collections -------------------------------------------------------------
def _c_sort(ctx, args):
    lst = _need_list("collections.sort", args[0])
    for item in lst:
        if not isinstance(item, (int, float, str)) or isinstance(item, bool):
            _fail("collections.sort supports Int, Float and String elements, found %s"
                  % type_name(item))
    kinds = {type(x) for x in lst}
    if len(kinds) > 1:
        _fail("collections.sort needs homogeneous elements, found mixed types")
    return sorted(lst)


def _c_reverse(ctx, args):
    lst = _need_list("collections.reverse", args[0])
    return list(reversed(lst))


def _c_index_of(ctx, args):
    lst = _need_list("collections.index_of", args[0])
    for i, item in enumerate(lst):
        if _value_eq(item, args[1]):
            return i64(i)
    return i64(-1)


def _c_sum(ctx, args):
    lst = _need_list("collections.sum", args[0])
    total = 0
    is_float = False
    for item in lst:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _fail("collections.sum expects a List of numbers, found %s" % type_name(item))
        if isinstance(item, float):
            is_float = True
        total += item
    return float(total) if is_float else i64(total)


# --- registry ----------------------------------------------------------------
def _build():
    mods = {"core": {}, "math": {}, "string": {}, "collections": {},
            "fs": {}, "gui": {}, "gui.lib.widgets": {}, "gui.lib.layout": {},
            "colors": {}, "gui.lib.theme": {}, "json": {}, "speech": {},
            "voice": {}, "tui": {},
            "tui.lib.widgets": {}, "tui.lib.layout": {}, "tui.lib.style": {},
            "ui": {}, "ui.state": {},
            "ui.lib.widgets": {}, "ui.lib.theme": {}, "ui.lib.colors": {},
            "ui.lib.layout": {}, "ui.lib.scroll": {}, "ui.lib.animation": {}}

    def add(module, name, params, ret, fn, min_args=None, max_args=None,
            requires=None, path_arg=None, accepts_block=False):
        native = Native(module, name, params, ret, fn, min_args, max_args,
                        requires, path_arg, accepts_block)
        mods[module][name] = native

    add("core", "sprint", ["Any"], "Unit", _n_sprint)
    add("core", "dit", ["Any"], "Unit", _n_dit)
    add("core", "input", ["String"], "String", _n_input)
    add("core", "type_of", ["Any"], "String", _n_type_of)
    add("core", "assert", ["Bool", "String"], "Unit", _n_assert, 1, 2)
    add("core", "str", ["Any"], "String", _n_str)
    add("core", "int", ["Any"], "Int", _n_int)
    add("core", "float", ["Any"], "Float", _n_float)
    add("core", "len", ["Any"], "Int", _n_len)
    add("core", "range", ["Int", "Int", "Int"], "List", _n_range, 1, 3)
    add("core", "push", ["List", "Any"], "Unit", _n_push)
    add("core", "keys", ["Map"], "List", _n_keys)
    add("core", "values", ["Map"], "List", _n_values)
    add("core", "has", ["Any", "Any"], "Bool", _n_has)

    add("math", "abs", ["Any"], "Any", _m_abs)
    add("math", "min", ["Any", "Any"], "Any", _m_min)
    add("math", "max", ["Any", "Any"], "Any", _m_max)
    add("math", "sqrt", ["Any"], "Float", _m_sqrt)
    add("math", "pow", ["Any", "Any"], "Float", _m_pow)
    add("math", "floor", ["Any"], "Int", _m_floor)
    add("math", "ceil", ["Any"], "Int", _m_ceil)
    add("math", "round", ["Any"], "Int", _m_round)

    add("string", "split", ["String", "String"], "List", _s_split)
    add("string", "join", ["List", "String"], "String", _s_join)
    add("string", "trim", ["String"], "String", _s_trim)
    add("string", "replace", ["String", "String", "String"], "String", _s_replace)
    add("string", "contains", ["String", "String"], "Bool", _s_contains)
    add("string", "starts_with", ["String", "String"], "Bool", _s_starts_with)
    add("string", "ends_with", ["String", "String"], "Bool", _s_ends_with)
    add("string", "upper", ["String"], "String", _s_upper)
    add("string", "lower", ["String"], "String", _s_lower)

    add("collections", "sort", ["List"], "List", _c_sort)
    add("collections", "reverse", ["List"], "List", _c_reverse)
    add("collections", "index_of", ["List", "Any"], "Int", _c_index_of)
    add("collections", "sum", ["List"], "Any", _c_sum)

    # fs and json live in their own modules; importing them here (inside the
    # builder) avoids a circular import at module load time.
    from .stdlib_fs import FUNCTIONS as _FS
    from .stdlib_json import FUNCTIONS as _JSON

    for module, table in (("fs", _FS), ("json", _JSON)):
        for name, params, ret, fn, requires, path_arg, min_args in table:
            add(module, name, params, ret, fn, min_args=min_args,
                requires=requires, path_arg=path_arg)

    from .gui.natives_gui import FUNCTION_TABLES as _GUI
    for module, table in _GUI.items():
        for (name, params, ret, fn, min_args, max_args,
             requires, path_arg) in table:
            add(module, name, params, ret, fn, min_args=min_args,
                max_args=max_args, requires=requires, path_arg=path_arg)

    from .tui.natives_tui import FUNCTIONS as _TUI
    for module, table in _TUI.items():
        for (name, params, ret, fn, min_args, max_args,
             requires, path_arg) in table:
            add(module, name, params, ret, fn, min_args=min_args,
                max_args=max_args, requires=requires, path_arg=path_arg)

    from .voice.natives_speech import FUNCTIONS as _SPEECH
    # `voice` is the preferred namespace; `speech` stays for compatibility.
    # The natives are built once and the very same objects are aliased into
    # `voice`, so there is one implementation, one registry and one set of
    # capability requirements — not two copies that could drift apart.
    for (name, params, ret, fn, min_args, max_args,
         requires, path_arg) in _SPEECH:
        add("speech", name, params, ret, fn, min_args=min_args,
            max_args=max_args, requires=requires, path_arg=path_arg)
    mods["voice"].update(mods["speech"])

    from .ui.natives_colors import FUNCTIONS as _COLORS
    for (name, params, ret, fn, min_args, max_args,
         requires, path_arg) in _COLORS:
        add("colors", name, params, ret, fn, min_args=min_args,
            max_args=max_args, requires=requires, path_arg=path_arg)

    from .ui.natives_ui import FUNCTIONS as _UI
    for (module, name, params, ret, fn, min_args, max_args,
         accepts_block) in _UI:
        add(module, name, params, ret, fn, min_args=min_args, max_args=max_args,
            accepts_block=accepts_block)

    return mods


MODULES = _build()

# module-level constants available as `module.name`
CONSTANTS = {
    "math": {"pi": _math.pi, "e": _math.e, "tau": 2 * _math.pi},
}

# modules that exist as documentation but are not implemented yet
PLANNED_MODULES = {"path", "time", "random", "regex", "http",
                   "net", "process", "log", "crypto", "test", "async", "ai"}


def ui_reserved_modules():
    """Reserved and adapter module names, with the reason they are unavailable."""
    from .ui.natives_ui import ADAPTER_MODULES, RESERVED_MODULES
    return RESERVED_MODULES, ADAPTER_MODULES


def get_native(module, name):
    return MODULES.get(module, {}).get(name)


def get_constant(module, name):
    """Return (found, value) for `module.name` constants."""
    table = CONSTANTS.get(module, {})
    if name in table:
        return True, table[name]
    return False, None


def module_exists(module):
    return module in MODULES


def constant_names(module):
    return sorted(CONSTANTS.get(module, {}).keys())


def native_names(module):
    return sorted(MODULES.get(module, {}).keys())
