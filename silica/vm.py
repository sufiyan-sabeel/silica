"""The Silica virtual machine.

A stack machine with explicit call frames (no host recursion), so deep Silica
recursion is limited by `max_frames` rather than by the Python interpreter.
Bytecode is decoded once per function and cached; execution then walks a list
of (opcode, operands, offset) tuples.

Runtime semantics fixed by docs/LANGUAGE_SPEC.md:
  * Int is 64-bit signed and wraps on overflow.
  * Int / Int truncates toward zero; `%` keeps the sign of the dividend.
  * Division (or modulo) by zero is a runtime error, for Int and Float.
  * Negative indices and missing map keys are runtime errors.
  * `sprint`/`dit` render Bool as oui/nein, Unit as `unit`.
"""

import math

from .bytecode import (OPS, decode, verify_chunk)
from .capabilities import CapabilitySet
from .errors import SilicaError, SilicaRuntimeError
from .natives import (Iterator, MODULES, format_value, get_native, i64, type_name)


class Context:
    """I/O and limits handed to native functions."""

    __slots__ = ("vm", "stdin", "stdout", "stderr")

    def __init__(self, vm, stdin, stdout, stderr):
        self.vm = vm
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def write(self, text):
        self.stdout.write(text)

    def flush(self):
        try:
            self.stdout.flush()
        except Exception:
            pass

    def readline(self):
        line = self.stdin.readline()
        if line == "":
            return None
        if line.endswith("\n"):
            line = line[:-1]
        if line.endswith("\r"):
            line = line[:-1]
        return line

    @property
    def capabilities(self):
        """The capability set of the running VM (read-only in practice)."""
        return self.vm.capabilities


class Frame:
    __slots__ = ("fn", "index", "ip", "locals", "stack")

    def __init__(self, fn, index, locals_):
        self.fn = fn
        self.index = index
        self.ip = 0
        self.locals = locals_
        self.stack = []


class VM:
    def __init__(self, chunk, stdin=None, stdout=None, stderr=None,
                 max_frames=4096, filename="<bytecode>", initial_globals=None,
                 capabilities=None):
        import sys
        self.chunk = chunk
        self.filename = filename
        # Least privilege: a VM with no explicit grants can touch nothing.
        self.capabilities = capabilities if capabilities is not None else CapabilitySet.empty()
        self._global_slots = [None] * len(chunk.globals)
        if initial_globals:
            for i, value in enumerate(initial_globals[:len(self._global_slots)]):
                self._global_slots[i] = value
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.max_frames = max_frames
        self.ctx = Context(self, self.stdin, self.stdout, self.stderr)
        self.exit_code = 0
        self._decoded = {}

    # -- helpers -------------------------------------------------------------
    def _code(self, fn_index):
        cached = self._decoded.get(fn_index)
        if cached is None:
            fn = self.chunk.functions[fn_index]
            instrs = decode(fn.code, self.filename, fn.name)
            offsets = {ins.offset: i for i, ins in enumerate(instrs)}
            cached = ([(ins.op, ins.operands, ins.offset) for ins in instrs], offsets)
            self._decoded[fn_index] = cached
        return cached

    def _fail(self, frame, message, hint=None):
        line = frame.fn.line_for(frame.ip_offset) if hasattr(frame, "ip_offset") else 0
        raise SilicaRuntimeError(message, line, 0, self.filename, hint)

    def run(self, entry=None, verify=True):
        if verify:
            verify_chunk(self.chunk, self.filename)
        if self.chunk.init is not None:
            self._execute(self.chunk.init)
        target = entry if entry is not None else self.chunk.entry
        if target is None:
            raise SilicaRuntimeError("bytecode has no entry point", filename=self.filename)
        self._execute(target)
        return self.exit_code

    # -- the interpreter loop ------------------------------------------------
    def _execute(self, fn_index):
        fn = self.chunk.functions[fn_index]
        if fn.arity != 0:
            raise SilicaRuntimeError("cannot start function '%s': it takes %d argument(s)"
                                     % (fn.name, fn.arity), filename=self.filename)
        frames = [Frame(fn, fn_index, [None] * fn.n_locals)]
        chunk = self.chunk
        constants = chunk.constants
        functions = chunk.functions
        natives = MODULES
        ctx = self.ctx

        while frames:
            frame = frames[-1]
            instrs, offsets = self._code(frame.index)
            fn = frame.fn
            code_len = len(instrs)
            # hoisting these into locals keeps the inner loop off attribute
            # lookups; they are written back to the frame on CALL/RET
            ip = frame.ip
            stack = frame.stack
            locals_ = frame.locals

            while True:
                if ip >= code_len:
                    frame.ip = ip
                    raise SilicaRuntimeError(
                        "function '%s' ran past the end of its code" % fn.name,
                        filename=self.filename)
                op, operands, offset = instrs[ip]
                ip += 1

                if op == 0x01:  # CONST
                    stack.append(constants[operands[0]])
                elif op == 0x02:  # UNIT
                    stack.append(None)
                elif op == 0x03:  # TRUE
                    stack.append(True)
                elif op == 0x04:  # FALSE
                    stack.append(False)
                elif op == 0x05:  # LOAD_LOCAL
                    stack.append(locals_[operands[0]])
                elif op == 0x06:  # STORE_LOCAL
                    locals_[operands[0]] = stack.pop()
                elif op == 0x07:  # LOAD_GLOBAL
                    stack.append(self._global_slots[operands[0]])
                elif op == 0x08:  # STORE_GLOBAL
                    self._global_slots[operands[0]] = stack.pop()
                elif op == 0x09:  # POP
                    stack.pop()
                elif op == 0x0A:  # ADD
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._add(a, b, fn, offset))
                elif op == 0x0B:  # SUB
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._numeric("subtract", a, b, fn, offset,
                                               lambda x, y: x - y))
                elif op == 0x0C:  # MUL
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._numeric("multiply", a, b, fn, offset,
                                               lambda x, y: x * y))
                elif op == 0x0D:  # DIV
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._divide(a, b, fn, offset))
                elif op == 0x0E:  # MOD
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._modulo(a, b, fn, offset))
                elif op == 0x0F:  # NEG
                    a = stack.pop()
                    if isinstance(a, bool) or not isinstance(a, (int, float)):
                        self._raise(fn, offset, "cannot negate %s" % type_name(a))
                    stack.append(i64(-a) if isinstance(a, int) else -a)
                elif op == 0x10:  # NOT
                    a = stack.pop()
                    if not isinstance(a, bool):
                        self._raise(fn, offset, "'non' expects Bool, found %s" % type_name(a))
                    stack.append(not a)
                elif op == 0x11:  # EQ
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._equal(a, b))
                elif op == 0x12:  # NE
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(not self._equal(a, b))
                elif op == 0x13:  # LT
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._order(a, b, fn, offset, "<"))
                elif op == 0x14:  # LE
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._order(a, b, fn, offset, "<="))
                elif op == 0x15:  # GT
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._order(a, b, fn, offset, ">"))
                elif op == 0x16:  # GE
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(self._order(a, b, fn, offset, ">="))
                elif op == 0x17:  # JUMP
                    ip = offsets[operands[0]]
                elif op == 0x18:  # JUMP_IF_FALSE
                    cond = stack.pop()
                    if not isinstance(cond, bool):
                        self._raise(fn, offset, "condition must be Bool, found %s"
                                    % type_name(cond))
                    if not cond:
                        ip = offsets[operands[0]]
                elif op == 0x19:  # CALL
                    target, argc = operands
                    callee = functions[target]
                    if len(frames) >= self.max_frames:
                        self._raise(fn, offset,
                                    "call stack overflow at depth %d" % len(frames),
                                    hint="Silica limits recursion depth; check the base case")
                    args = stack[-argc:] if argc else []
                    if argc:
                        del stack[-argc:]
                    frame.ip = ip
                    frames.append(Frame(callee, target,
                                        list(args) + [None] * (callee.n_locals - argc)))
                    break
                elif op == 0x1A:  # CALL_NATIVE
                    mod_idx, fn_idx, argc = operands
                    module = constants[mod_idx]
                    fname = constants[fn_idx]
                    native = natives.get(module, {}).get(fname)
                    if native is None:  # pragma: no cover - verifier blocks this
                        self._raise(fn, offset, "unknown native %s.%s" % (module, fname))
                    args = stack[-argc:] if argc else []
                    if argc:
                        del stack[-argc:]
                    try:
                        # Single choke point: a privileged native is authorised
                        # here, before its body runs. The native never re-checks
                        # and never re-resolves the path it is handed.
                        if native.requires is not None:
                            args = self.capabilities.authorize_call(native, args)
                        result = native.fn(ctx, args)
                    except SilicaError as err:
                        if not err.line:
                            err.line = fn.line_for(offset)
                            err.filename = self.filename
                        raise
                    stack.append(result)
                elif op == 0x1B:  # RET
                    value = stack.pop()
                    frames.pop()
                    if not frames:
                        return
                    frames[-1].stack.append(value)
                    break
                elif op == 0x1C:  # PRINT
                    ctx.write(format_value(stack.pop()) + "\n")
                elif op == 0x1D:  # DIT
                    ctx.write(format_value(stack.pop()))
                elif op == 0x1E:  # MAKE_LIST
                    n = operands[0]
                    items = stack[-n:] if n else []
                    if n:
                        del stack[-n:]
                    stack.append(list(items))
                elif op == 0x1F:  # MAKE_MAP
                    n = operands[0]
                    pairs = stack[-n * 2:] if n else []
                    if n:
                        del stack[-n * 2:]
                    result = {}
                    for i in range(0, len(pairs), 2):
                        key = pairs[i]
                        if not isinstance(key, str):
                            self._raise(fn, offset,
                                        "map keys must be String, found %s" % type_name(key))
                        result[key] = pairs[i + 1]
                    stack.append(result)
                elif op == 0x20:  # INDEX_GET
                    index = stack.pop()
                    target = stack.pop()
                    stack.append(self._index(target, index, fn, offset))
                elif op == 0x21:  # LEN
                    target = stack.pop()
                    if isinstance(target, (list, dict, str)):
                        stack.append(i64(len(target)))
                    else:
                        self._raise(fn, offset, "len expects a List, Map or String, found %s"
                                    % type_name(target))
                elif op == 0x22:  # ITER_START
                    target = stack.pop()
                    stack.append(self._make_iterator(target, fn, offset))
                elif op == 0x23:  # ITER_NEXT
                    iterator = stack[-1]
                    if iterator.has_next():
                        value = iterator.items[iterator.index]
                        iterator.index += 1
                        stack.append(value)
                    else:
                        stack.pop()
                        ip = offsets[operands[0]]
                elif op == 0x24:  # HALT_OK
                    self.exit_code = 0
                    return
                elif op == 0x25:  # HALT_POP
                    value = stack.pop()
                    if isinstance(value, bool) or not isinstance(value, int):
                        self._raise(fn, offset,
                                    "halt exit code must be Int, found %s" % type_name(value))
                    self.exit_code = value
                    return
                else:  # pragma: no cover - verifier blocks unknown opcodes
                    self._raise(fn, offset, "unknown opcode 0x%02x" % op)

    # -- operators -----------------------------------------------------------
    def _raise(self, fn, offset, message, hint=None):
        raise SilicaRuntimeError(message, fn.line_for(offset), 0, self.filename, hint)

    def _numeric(self, verb, a, b, fn, offset, op):
        if isinstance(a, bool) or isinstance(b, bool):
            self._raise(fn, offset, "cannot %s Bool and %s" % (verb, type_name(b)))
        if isinstance(a, int) and isinstance(b, int):
            return i64(op(a, b))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(op(float(a), float(b)))
        self._raise(fn, offset, "cannot %s %s and %s" % (verb, type_name(a), type_name(b)))

    def _add(self, a, b, fn, offset):
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        if isinstance(a, list) and isinstance(b, list):
            return list(a) + list(b)
        if isinstance(a, bool) or isinstance(b, bool):
            self._raise(fn, offset, "cannot add Bool and %s" % type_name(b))
        if isinstance(a, int) and isinstance(b, int):
            return i64(a + b)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) + float(b)
        self._raise(fn, offset, "cannot add %s and %s" % (type_name(a), type_name(b)),
                    hint="'+' works on numbers, Strings and Lists")

    def _divide(self, a, b, fn, offset):
        if isinstance(a, bool) or isinstance(b, bool) or \
                not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            self._raise(fn, offset, "cannot divide %s by %s" % (type_name(a), type_name(b)))
        if b == 0:
            self._raise(fn, offset, "division by zero",
                        hint="guard the divisor with 'si' before dividing")
        if isinstance(a, int) and isinstance(b, int):
            quotient = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                quotient = -quotient
            return i64(quotient)
        return float(a) / float(b)

    def _modulo(self, a, b, fn, offset):
        if isinstance(a, bool) or isinstance(b, bool) or \
                not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            self._raise(fn, offset, "cannot take %s modulo %s"
                        % (type_name(a), type_name(b)))
        if b == 0:
            self._raise(fn, offset, "modulo by zero")
        if isinstance(a, int) and isinstance(b, int):
            remainder = abs(a) % abs(b)
            return i64(-remainder if a < 0 else remainder)
        return math.fmod(float(a), float(b))

    def _equal(self, a, b):
        from .natives import _value_eq
        return _value_eq(a, b)

    def _order(self, a, b, fn, offset, op):
        if isinstance(a, str) and isinstance(b, str):
            if op == "<":
                return a < b
            if op == "<=":
                return a <= b
            if op == ">":
                return a > b
            return a >= b
        if isinstance(a, bool) or isinstance(b, bool) or \
                not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            self._raise(fn, offset, "cannot order %s and %s with '%s'"
                        % (type_name(a), type_name(b), op))
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b

    def _index(self, target, index, fn, offset):
        if isinstance(target, list):
            if isinstance(index, bool) or not isinstance(index, int):
                self._raise(fn, offset, "list index must be Int, found %s"
                            % type_name(index))
            if index < 0:
                self._raise(fn, offset,
                            "list index %d out of range (length %d)" % (index, len(target)),
                            hint="Silica has no negative indexing")
            if index >= len(target):
                self._raise(fn, offset,
                            "list index %d out of range (length %d)" % (index, len(target)))
            return target[index]
        if isinstance(target, str):
            if isinstance(index, bool) or not isinstance(index, int):
                self._raise(fn, offset, "string index must be Int, found %s"
                            % type_name(index))
            if index < 0 or index >= len(target):
                self._raise(fn, offset,
                            "string index %d out of range (length %d)" % (index, len(target)))
            return target[index]
        if isinstance(target, dict):
            if not isinstance(index, str):
                self._raise(fn, offset, "map key must be String, found %s"
                            % type_name(index))
            if index not in target:
                self._raise(fn, offset, "map key %r not found" % index,
                            hint="check the key with 'has' before indexing")
            return target[index]
        self._raise(fn, offset, "cannot index a value of type %s" % type_name(target))

    def _make_iterator(self, target, fn, offset):
        if isinstance(target, list):
            return Iterator(list(target))
        if isinstance(target, str):
            return Iterator(list(target))
        if isinstance(target, dict):
            return Iterator(list(target.keys()))
        self._raise(fn, offset, "'per' needs a List, Map or String, found %s"
                    % type_name(target))

    # -- globals -------------------------------------------------------------
    def global_values(self):
        """Snapshot of global slots (used by the REPL to keep state)."""
        return list(self._global_slots)
