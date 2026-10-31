"""Silica bytecode: instruction set, versioned `.sbc` serialization, verifier.

File layout (all integers little-endian):

    offset  size  field
    0       8     magic  b"SILICABC"
    8       2     format major version
    10      2     format minor version
    12      1     flags (reserved, must be 0)
    13      4     CRC-32 of the payload that follows the header
    17      ...   payload

Payload (LEB128 varints unless stated):

    varint  constant count
      for each constant: u8 tag, then value
        1 = Int    -> 8 bytes i64
        2 = Float  -> 8 bytes f64
        3 = String -> varint byte length + UTF-8 bytes
        4 = Bool   -> u8 (0/1)
    varint  global count
      for each global: varint name length + UTF-8 name, u8 type tag
    varint  function count
      for each function: varint name length + UTF-8 name, varint arity,
        varint local count, varint max stack, u8 return-type tag,
        varint code length + code bytes,
        varint line-table length + (varint offset, varint line) pairs
    u8      has init (0/1), then varint function index if 1
    u8      has entry (0/1), then varint function index if 1

Rust memory structures are never serialized directly: every field is written
explicitly and read back with bounds checks, so the format stays stable across
implementations and can be validated before execution.
"""

import struct
import zlib

from .errors import VerifyError

MAGIC = b"SILICABC"
FORMAT_MAJOR = 1
FORMAT_MINOR = 0
HEADER_SIZE = 17
MAX_CODE_BYTES = 1 << 20
MAX_CONSTANTS = 1 << 16
MAX_FUNCTIONS = 1 << 12
MAX_STACK = 4096
MAX_LOCALS = 4096

# --- opcodes -----------------------------------------------------------------
OPS = {
    "NOP": 0x00,
    "CONST": 0x01,
    "UNIT": 0x02,
    "TRUE": 0x03,
    "FALSE": 0x04,
    "LOAD_LOCAL": 0x05,
    "STORE_LOCAL": 0x06,
    "LOAD_GLOBAL": 0x07,
    "STORE_GLOBAL": 0x08,
    "POP": 0x09,
    "ADD": 0x0A,
    "SUB": 0x0B,
    "MUL": 0x0C,
    "DIV": 0x0D,
    "MOD": 0x0E,
    "NEG": 0x0F,
    "NOT": 0x10,
    "EQ": 0x11,
    "NE": 0x12,
    "LT": 0x13,
    "LE": 0x14,
    "GT": 0x15,
    "GE": 0x16,
    "JUMP": 0x17,
    "JUMP_IF_FALSE": 0x18,
    "CALL": 0x19,
    "CALL_NATIVE": 0x1A,
    "RET": 0x1B,
    "PRINT": 0x1C,
    "DIT": 0x1D,
    "MAKE_LIST": 0x1E,
    "MAKE_MAP": 0x1F,
    "INDEX_GET": 0x20,
    "LEN": 0x21,
    "ITER_START": 0x22,
    "ITER_NEXT": 0x23,
    "HALT_OK": 0x24,
    "HALT_POP": 0x25,
    # 0.9.2: structs
    "MAKE_STRUCT": 0x26,     # operands: (descriptor const index, field count)
    "GET_FIELD": 0x27,       # operand: field-name const index
    "SET_FIELD": 0x28,       # operand: field-name const index
    "FREEZE": 0x29,          # mark the value on top of the stack immutable
}

OP_NAMES = {code: name for name, code in OPS.items()}

# operand layout: 'u' = varint, 'j' = 4-byte little-endian code offset
OPERANDS = {
    "CONST": ("u",),
    "LOAD_LOCAL": ("u",),
    "STORE_LOCAL": ("u",),
    "LOAD_GLOBAL": ("u",),
    "STORE_GLOBAL": ("u",),
    "JUMP": ("j",),
    "JUMP_IF_FALSE": ("j",),
    "CALL": ("u", "u"),
    "CALL_NATIVE": ("u", "u", "u"),
    "MAKE_LIST": ("u",),
    "MAKE_MAP": ("u",),
    "ITER_NEXT": ("j",),
    "MAKE_STRUCT": ("u", "u"),
    "GET_FIELD": ("u",),
    "SET_FIELD": ("u",),
    "FREEZE": (),
}

# (pops, pushes) for straight-line instructions
STACK_EFFECT = {
    "NOP": (0, 0),
    "CONST": (0, 1),
    "UNIT": (0, 1),
    "TRUE": (0, 1),
    "FALSE": (0, 1),
    "LOAD_LOCAL": (0, 1),
    "STORE_LOCAL": (1, 0),
    "LOAD_GLOBAL": (0, 1),
    "STORE_GLOBAL": (1, 0),
    "POP": (1, 0),
    "ADD": (2, 1),
    "SUB": (2, 1),
    "MUL": (2, 1),
    "DIV": (2, 1),
    "MOD": (2, 1),
    "NEG": (1, 1),
    "NOT": (1, 1),
    "EQ": (2, 1),
    "NE": (2, 1),
    "LT": (2, 1),
    "LE": (2, 1),
    "GT": (2, 1),
    "GE": (2, 1),
    "JUMP": (0, 0),
    "JUMP_IF_FALSE": (1, 0),
    "RET": (1, 0),
    "PRINT": (1, 0),
    "DIT": (1, 0),
    "MAKE_LIST": (None, 1),      # pops n
    "MAKE_MAP": (None, 1),       # pops 2n
    "INDEX_GET": (2, 1),
    "LEN": (1, 1),
    "ITER_START": (1, 1),
    "HALT_OK": (0, 0),
    "HALT_POP": (1, 0),
    "MAKE_STRUCT": (None, 1),    # pops n, where n is the second operand
    "GET_FIELD": (1, 1),
    "SET_FIELD": (2, 0),         # pops the value, then the struct
    "FREEZE": (0, 0),            # peeks; does not change the stack
}

TERMINATORS = {"RET", "HALT_OK", "HALT_POP"}

# --- constants ---------------------------------------------------------------
TAG_INT = 1
TAG_FLOAT = 2
TAG_STRING = 3
TAG_BOOL = 4

TYPE_TAGS = {"Unit": 0, "Int": 1, "Float": 2, "Bool": 3, "String": 4,
             "List": 5, "Map": 6, "Any": 7}
TAG_TYPES = {v: k for k, v in TYPE_TAGS.items()}


def constant_tag(value):
    if isinstance(value, bool):
        return TAG_BOOL
    if isinstance(value, int):
        return TAG_INT
    if isinstance(value, float):
        return TAG_FLOAT
    if isinstance(value, str):
        return TAG_STRING
    raise ValueError("unsupported constant %r" % (value,))


def constant_key(value):
    return (constant_tag(value), value)


class Function:
    __slots__ = ("name", "arity", "n_locals", "max_stack", "ret_type", "code", "lines")

    def __init__(self, name, arity=0, n_locals=0, max_stack=0, ret_type="Unit",
                 code=b"", lines=None):
        self.name = name
        self.arity = arity
        self.n_locals = n_locals
        self.max_stack = max_stack
        self.ret_type = ret_type
        self.code = code
        self.lines = lines or []

    def line_for(self, offset):
        """Source line for a code offset (best effort, for runtime errors)."""
        best = 0
        for off, line in self.lines:
            if off <= offset:
                best = line
            else:
                break
        return best

    def __repr__(self):
        return "Function(%s, arity=%d, locals=%d, bytes=%d)" % (
            self.name, self.arity, self.n_locals, len(self.code))


class Chunk:
    """A complete compiled program: constants, globals, functions, entry."""

    def __init__(self, constants=None, globals=None, functions=None,
                 entry=None, init=None):
        self.constants = constants or []
        self.globals = globals or []      # list of (name, type)
        self.functions = functions or []
        self.entry = entry                # index of `main`, or None
        self.init = init                  # index of global initialiser, or None

    def function(self, index):
        return self.functions[index]


# --- varint + reader/writer --------------------------------------------------
def write_varint(out, value):
    if value < 0:
        raise ValueError("varint must be non-negative")
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return


def write_string(out, text):
    data = text.encode("utf-8")
    write_varint(out, len(data))
    out.extend(data)


class Reader:
    def __init__(self, data, filename="<bytecode>"):
        self.data = data
        self.pos = 0
        self.filename = filename

    def need(self, n, what):
        if self.pos + n > len(self.data):
            raise VerifyError("truncated bytecode while reading %s" % what,
                              filename=self.filename)

    def u8(self, what="u8"):
        self.need(1, what)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self, what="u16"):
        self.need(2, what)
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u32(self, what="u32"):
        self.need(4, what)
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def i64(self, what="i64"):
        self.need(8, what)
        value = struct.unpack_from("<q", self.data, self.pos)[0]
        self.pos += 8
        return value

    def f64(self, what="f64"):
        self.need(8, what)
        value = struct.unpack_from("<d", self.data, self.pos)[0]
        self.pos += 8
        return value

    def varint(self, what="varint"):
        result = 0
        shift = 0
        while True:
            byte = self.u8(what)
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7
            if shift > 63:
                raise VerifyError("malformed varint in bytecode (%s)" % what,
                                  filename=self.filename)

    def string(self, what="string"):
        length = self.varint(what + " length")
        self.need(length, what)
        raw = self.data[self.pos:self.pos + length]
        self.pos += length
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise VerifyError("invalid UTF-8 in %s" % what, filename=self.filename)

    def at_end(self):
        return self.pos >= len(self.data)


# --- serialization -----------------------------------------------------------
def serialize(chunk):
    payload = bytearray()

    write_varint(payload, len(chunk.constants))
    for value in chunk.constants:
        tag = constant_tag(value)
        payload.append(tag)
        if tag == TAG_INT:
            payload.extend(struct.pack("<q", value))
        elif tag == TAG_FLOAT:
            payload.extend(struct.pack("<d", value))
        elif tag == TAG_STRING:
            write_string(payload, value)
        else:
            payload.append(1 if value else 0)

    write_varint(payload, len(chunk.globals))
    for name, type_name in chunk.globals:
        write_string(payload, name)
        payload.append(TYPE_TAGS.get(type_name, TYPE_TAGS["Any"]))

    write_varint(payload, len(chunk.functions))
    for fn in chunk.functions:
        write_string(payload, fn.name)
        write_varint(payload, fn.arity)
        write_varint(payload, fn.n_locals)
        write_varint(payload, fn.max_stack)
        payload.append(TYPE_TAGS.get(fn.ret_type, TYPE_TAGS["Any"]))
        write_varint(payload, len(fn.code))
        payload.extend(fn.code)
        write_varint(payload, len(fn.lines))
        for offset, line in fn.lines:
            write_varint(payload, offset)
            write_varint(payload, line)

    if chunk.init is None:
        payload.append(0)
    else:
        payload.append(1)
        write_varint(payload, chunk.init)

    if chunk.entry is None:
        payload.append(0)
    else:
        payload.append(1)
        write_varint(payload, chunk.entry)

    header = bytearray()
    header.extend(MAGIC)
    header.extend(struct.pack("<H", FORMAT_MAJOR))
    header.extend(struct.pack("<H", FORMAT_MINOR))
    header.append(0)  # flags
    header.extend(struct.pack("<I", zlib.crc32(bytes(payload)) & 0xFFFFFFFF))
    return bytes(header) + bytes(payload)


def deserialize(data, filename="<bytecode>"):
    if len(data) < HEADER_SIZE:
        raise VerifyError("file is too small to be Silica bytecode", filename=filename)
    if data[:8] != MAGIC:
        raise VerifyError("bad magic bytes: not a Silica .sbc file", filename=filename,
                          hint="recompile the source with 'silica compile'")
    major, minor = struct.unpack_from("<HH", data, 8)
    if major != FORMAT_MAJOR:
        raise VerifyError(
            "unsupported bytecode format version %d.%d (this engine reads %d.x)"
            % (major, minor, FORMAT_MAJOR), filename=filename,
            hint="recompile the source with this version of silica")
    flags = data[12]
    if flags != 0:
        raise VerifyError("unsupported bytecode flags 0x%02x" % flags, filename=filename)
    expected_crc = struct.unpack_from("<I", data, 13)[0]
    payload = data[HEADER_SIZE:]
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise VerifyError("bytecode checksum mismatch (file is corrupt or truncated)",
                          filename=filename)

    reader = Reader(payload, filename)

    n_const = reader.varint("constant count")
    if n_const > MAX_CONSTANTS:
        raise VerifyError("too many constants (%d)" % n_const, filename=filename)
    constants = []
    for _ in range(n_const):
        tag = reader.u8("constant tag")
        if tag == TAG_INT:
            constants.append(reader.i64("Int constant"))
        elif tag == TAG_FLOAT:
            constants.append(reader.f64("Float constant"))
        elif tag == TAG_STRING:
            constants.append(reader.string("String constant"))
        elif tag == TAG_BOOL:
            constants.append(bool(reader.u8("Bool constant")))
        else:
            raise VerifyError("unknown constant tag %d" % tag, filename=filename)

    n_globals = reader.varint("global count")
    if n_globals > MAX_CONSTANTS:
        raise VerifyError("too many globals (%d)" % n_globals, filename=filename)
    globals_ = []
    for _ in range(n_globals):
        name = reader.string("global name")
        tag = reader.u8("global type")
        if tag not in TAG_TYPES:
            raise VerifyError("unknown type tag %d for global '%s'" % (tag, name),
                              filename=filename)
        globals_.append((name, TAG_TYPES[tag]))

    n_funcs = reader.varint("function count")
    if n_funcs > MAX_FUNCTIONS:
        raise VerifyError("too many functions (%d)" % n_funcs, filename=filename)
    functions = []
    for _ in range(n_funcs):
        name = reader.string("function name")
        arity = reader.varint("arity")
        n_locals = reader.varint("local count")
        max_stack = reader.varint("max stack")
        ret_tag = reader.u8("return type")
        if ret_tag not in TAG_TYPES:
            raise VerifyError("unknown return type tag %d in '%s'" % (ret_tag, name),
                              filename=filename)
        code_len = reader.varint("code length")
        if code_len > MAX_CODE_BYTES:
            raise VerifyError("function '%s' code too large (%d bytes)" % (name, code_len),
                              filename=filename)
        reader.need(code_len, "code of '%s'" % name)
        code = bytes(reader.data[reader.pos:reader.pos + code_len])
        reader.pos += code_len
        n_lines = reader.varint("line table length")
        lines = []
        for _ in range(n_lines):
            offset = reader.varint("line offset")
            line = reader.varint("line number")
            lines.append((offset, line))
        functions.append(Function(name, arity, n_locals, max_stack,
                                  TAG_TYPES[ret_tag], code, lines))

    init = None
    if reader.u8("init flag"):
        init = reader.varint("init function index")
    entry = None
    if reader.u8("entry flag"):
        entry = reader.varint("entry function index")

    if not reader.at_end():
        raise VerifyError("trailing bytes after bytecode payload", filename=filename)

    return Chunk(constants, globals_, functions, entry, init)


# --- instruction decoding ----------------------------------------------------
class Instruction:
    __slots__ = ("offset", "op", "operands", "size")

    def __init__(self, offset, op, operands, size):
        self.offset = offset
        self.op = op
        self.operands = operands
        self.size = size

    @property
    def name(self):
        return OP_NAMES[self.op]

    def __repr__(self):
        return "%04d %s %s" % (self.offset, self.name, self.operands)


def decode(code, filename="<bytecode>", fn_name="<function>"):
    instructions = []
    pos = 0
    while pos < len(code):
        start = pos
        op = code[pos]
        pos += 1
        if op not in OP_NAMES:
            raise VerifyError("unknown opcode 0x%02x at offset %d in '%s'"
                              % (op, start, fn_name), filename=filename)
        name = OP_NAMES[op]
        operands = []
        for kind in OPERANDS.get(name, ()):
            if kind == "u":
                result = 0
                shift = 0
                while True:
                    if pos >= len(code):
                        raise VerifyError("truncated operand at offset %d in '%s'"
                                          % (start, fn_name), filename=filename)
                    byte = code[pos]
                    pos += 1
                    result |= (byte & 0x7F) << shift
                    if not byte & 0x80:
                        break
                    shift += 7
                    if shift > 63:
                        raise VerifyError("malformed varint operand at offset %d in '%s'"
                                          % (start, fn_name), filename=filename)
                operands.append(result)
            else:  # 'j' -> 4-byte LE offset
                if pos + 4 > len(code):
                    raise VerifyError("truncated jump operand at offset %d in '%s'"
                                      % (start, fn_name), filename=filename)
                operands.append(struct.unpack_from("<I", code, pos)[0])
                pos += 4
        instructions.append(Instruction(start, op, operands, pos - start))
    return instructions


def encode(op_name, *operands):
    out = bytearray([OPS[op_name]])
    kinds = OPERANDS.get(op_name, ())
    if len(kinds) != len(operands):
        raise ValueError("%s expects %d operand(s)" % (op_name, len(kinds)))
    for kind, value in zip(kinds, operands):
        if kind == "u":
            write_varint(out, value)
        else:
            out.extend(struct.pack("<I", value))
    return bytes(out)


# --- verifier ----------------------------------------------------------------
def verify_chunk(chunk, filename="<bytecode>"):
    """Validate a chunk structurally and by abstract stack-depth analysis."""
    if chunk.entry is not None and not (0 <= chunk.entry < len(chunk.functions)):
        raise VerifyError("entry function index %d out of range" % chunk.entry,
                          filename=filename)
    if chunk.init is not None and not (0 <= chunk.init < len(chunk.functions)):
        raise VerifyError("init function index %d out of range" % chunk.init,
                          filename=filename)
    if chunk.entry is None and chunk.init is None:
        raise VerifyError("bytecode has no entry point", filename=filename)

    for index, fn in enumerate(chunk.functions):
        verify_function(chunk, fn, index, filename)
    return True


def verify_function(chunk, fn, index, filename):
    if fn.arity > MAX_LOCALS or fn.n_locals > MAX_LOCALS:
        raise VerifyError("function '%s' declares too many locals (%d)"
                          % (fn.name, fn.n_locals), filename=filename)
    if fn.n_locals < fn.arity:
        raise VerifyError("function '%s' has fewer locals (%d) than parameters (%d)"
                          % (fn.name, fn.n_locals, fn.arity), filename=filename)
    if not fn.code:
        raise VerifyError("function '%s' has empty code" % fn.name, filename=filename)
    if len(fn.code) > MAX_CODE_BYTES:
        raise VerifyError("function '%s' code too large" % fn.name, filename=filename)

    instructions = decode(fn.code, filename, fn.name)
    by_offset = {ins.offset: ins for ins in instructions}
    boundaries = set(by_offset)
    last = instructions[-1]
    if last.name not in TERMINATORS:
        raise VerifyError("function '%s' does not end with RET or HALT (last opcode: %s)"
                          % (fn.name, last.name), filename=filename)

    # structural operand checks
    for ins in instructions:
        name = ins.name
        if name == "CONST":
            if ins.operands[0] >= len(chunk.constants):
                raise VerifyError("constant index %d out of range in '%s'"
                                  % (ins.operands[0], fn.name), filename=filename)
        elif name in ("LOAD_LOCAL", "STORE_LOCAL"):
            if ins.operands[0] >= fn.n_locals:
                raise VerifyError("local slot %d out of range in '%s' (has %d)"
                                  % (ins.operands[0], fn.name, fn.n_locals),
                                  filename=filename)
        elif name in ("LOAD_GLOBAL", "STORE_GLOBAL"):
            if ins.operands[0] >= len(chunk.globals):
                raise VerifyError("global index %d out of range in '%s'"
                                  % (ins.operands[0], fn.name), filename=filename)
        elif name == "CALL":
            target, argc = ins.operands
            if target >= len(chunk.functions):
                raise VerifyError("call target %d out of range in '%s'"
                                  % (target, fn.name), filename=filename)
            callee = chunk.functions[target]
            if argc != callee.arity:
                raise VerifyError(
                    "call to '%s' passes %d argument(s) but it takes %d"
                    % (callee.name, argc, callee.arity), filename=filename)
        elif name == "CALL_NATIVE":
            mod_idx, fn_idx, argc = ins.operands
            for i in (mod_idx, fn_idx):
                if i >= len(chunk.constants) or not isinstance(chunk.constants[i], str):
                    raise VerifyError(
                        "native call in '%s' has a non-string module/function constant"
                        % fn.name, filename=filename)
            from .natives import get_native
            module = chunk.constants[mod_idx]
            fname = chunk.constants[fn_idx]
            native = get_native(module, fname)
            if native is None:
                raise VerifyError("native call to unknown function '%s.%s' in '%s'"
                                  % (module, fname, fn.name), filename=filename)
            if argc < native.min_args or argc > native.max_args:
                raise VerifyError("native call to '%s.%s' passes %d argument(s)"
                                  % (module, fname, argc), filename=filename)
        elif name in ("JUMP", "JUMP_IF_FALSE", "ITER_NEXT"):
            target = ins.operands[0]
            if target not in boundaries:
                raise VerifyError(
                    "jump target %d in '%s' is not an instruction boundary"
                    % (target, fn.name), filename=filename)

    # stack-depth analysis over the control-flow graph
    depths = {}
    worklist = [(0, 0)]
    max_depth = 0
    while worklist:
        offset, depth = worklist.pop()
        if depth < 0:
            raise VerifyError("stack underflow in '%s' at offset %d"
                              % (fn.name, offset), filename=filename)
        if depth > MAX_STACK:
            raise VerifyError("stack depth %d exceeds limit %d in '%s'"
                              % (depth, MAX_STACK, fn.name), filename=filename)
        if offset in depths:
            if depths[offset] != depth:
                raise VerifyError(
                    "inconsistent stack depth in '%s' at offset %d (%d vs %d)"
                    % (fn.name, offset, depths[offset], depth), filename=filename)
            continue
        depths[offset] = depth
        max_depth = max(max_depth, depth)
        ins = by_offset.get(offset)
        if ins is None:
            raise VerifyError(
                "control flow falls off the end of function '%s' at offset %d"
                % (fn.name, offset), filename=filename)
        name = ins.name

        if name in TERMINATORS:
            pops, pushes = STACK_EFFECT[name]
            if depth < pops:
                raise VerifyError("stack underflow in '%s' at offset %d"
                                  % (fn.name, offset), filename=filename)
            continue

        if name == "ITER_NEXT":
            if depth < 1:
                raise VerifyError("stack underflow in '%s' at offset %d"
                                  % (fn.name, offset), filename=filename)
            worklist.append((offset + ins.size, depth + 1))
            worklist.append((ins.operands[0], depth - 1))
            continue

        if name == "JUMP":
            worklist.append((ins.operands[0], depth))
            continue

        if name == "JUMP_IF_FALSE":
            if depth < 1:
                raise VerifyError("stack underflow in '%s' at offset %d"
                                  % (fn.name, offset), filename=filename)
            worklist.append((offset + ins.size, depth - 1))
            worklist.append((ins.operands[0], depth - 1))
            continue

        if name == "CALL":
            pops, pushes = ins.operands[1], 1
        elif name == "CALL_NATIVE":
            pops, pushes = ins.operands[2], 1
        elif name == "MAKE_LIST":
            pops, pushes = ins.operands[0], 1
        elif name == "MAKE_MAP":
            pops, pushes = ins.operands[0] * 2, 1
        elif name == "MAKE_STRUCT":
            pops, pushes = ins.operands[1], 1
        else:
            pops, pushes = STACK_EFFECT[name]

        if depth < pops:
            raise VerifyError("stack underflow in '%s' at offset %d (needs %d, has %d)"
                              % (fn.name, offset, pops, depth), filename=filename)
        worklist.append((offset + ins.size, depth - pops + pushes))

    if max_depth > fn.max_stack:
        raise VerifyError(
            "function '%s' declares max stack %d but needs %d"
            % (fn.name, fn.max_stack, max_depth), filename=filename)
    if max_depth > MAX_STACK:
        raise VerifyError("function '%s' exceeds the stack limit" % fn.name,
                          filename=filename)
    # returning the peak depth lets the compiler declare max_stack from the
    # code it actually emitted, using this one analysis implementation
    return max_depth


def verify_bytes(data, filename="<bytecode>"):
    chunk = deserialize(data, filename)
    verify_chunk(chunk, filename)
    return chunk
