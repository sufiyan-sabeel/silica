# Silica Bytecode Format — version 1.0

A `.sbc` file is a versioned, checksummed container for one compiled program.
It is written by `silica compile` and read by `silica run file.sbc`.

Design rules:

1. **No host memory layout is serialized.** Every field is written explicitly
   and read back with bounds checks, so the format is stable across
   implementations and platforms (this matters for the Rust port and for
   self-hosting).
2. **Versioned.** A reader refuses a major version it does not implement instead
   of guessing.
3. **Verifiable before execution.** A verifier checks structure, operands, jump
   targets, call arities, native existence and stack discipline before a single
   instruction runs. Untrusted `.sbc` files are validated, not trusted.
4. **Checksummed.** A CRC-32 over the payload detects corruption and truncation.

## 1. Header (17 bytes)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 8 | magic | `b"SILICABC"` |
| 8 | 2 | major version | little-endian `u16`, currently `1` |
| 10 | 2 | minor version | little-endian `u16`, currently `0` |
| 12 | 1 | flags | reserved, must be `0` |
| 13 | 4 | payload CRC-32 | little-endian `u32`, standard CRC-32 (zlib polynomial) |

A file is rejected if: it is shorter than 17 bytes, the magic is wrong, the
major version differs from 1, flags are non-zero, or the CRC does not match.

## 2. Payload

All counts and lengths are unsigned LEB128 varints. Strings are a varint byte
length followed by UTF-8 bytes.

```
varint  constant_count
  constant * {
    u8 tag;                       // 1 Int, 2 Float, 3 String, 4 Bool
    tag 1 -> i64 (8 bytes LE)
    tag 2 -> f64 (8 bytes LE)
    tag 3 -> varint length + UTF-8 bytes
    tag 4 -> u8 (0 or 1)
  }
varint  global_count
  global * { varint name_length + name, u8 type_tag }
varint  function_count
  function * {
    varint name_length + name
    varint arity
    varint local_count
    varint max_stack
    u8     return_type_tag
    varint code_length + code bytes
    varint line_table_count
    (varint code_offset, varint source_line) * line_table_count
  }
u8      has_init;  varint init_function_index   (only if has_init == 1)
u8      has_entry; varint entry_function_index  (only if has_entry == 1)
```

Type tags: `0 Unit`, `1 Int`, `2 Float`, `3 Bool`, `4 String`, `5 List`,
`6 Map`, `7 Any`.

The line table maps code offsets to source lines so runtime errors can report a
line number. It is informational: the verifier does not depend on it.

Any bytes left after the payload is read are an error (`trailing bytes`), so a
file cannot smuggle unverified data past the reader.

## 3. Instruction encoding

One byte opcode, then its operands:

* `u` — unsigned LEB128 varint
* `j` — 4-byte little-endian absolute code offset

Jump targets are absolute byte offsets into the function's own code, which keeps
the encoding simple and lets the verifier check each target against the set of
instruction boundaries.

## 4. Opcodes

| Opcode | Name | Operands | Stack effect |
|---|---|---|---|
| `0x00` | `NOP` | - | 0 -> 0 |
| `0x01` | `CONST` | const idx | 0 -> 1 |
| `0x02` | `UNIT` | - | 0 -> 1 |
| `0x03` | `TRUE` | - | 0 -> 1 |
| `0x04` | `FALSE` | - | 0 -> 1 |
| `0x05` | `LOAD_LOCAL` | slot | 0 -> 1 |
| `0x06` | `STORE_LOCAL` | slot | 1 -> 0 |
| `0x07` | `LOAD_GLOBAL` | global idx | 0 -> 1 |
| `0x08` | `STORE_GLOBAL` | global idx | 1 -> 0 |
| `0x09` | `POP` | - | 1 -> 0 |
| `0x0A` | `ADD` | - | 2 -> 1 |
| `0x0B` | `SUB` | - | 2 -> 1 |
| `0x0C` | `MUL` | - | 2 -> 1 |
| `0x0D` | `DIV` | - | 2 -> 1 |
| `0x0E` | `MOD` | - | 2 -> 1 |
| `0x0F` | `NEG` | - | 1 -> 1 |
| `0x10` | `NOT` | - | 1 -> 1 |
| `0x11` | `EQ` | - | 2 -> 1 |
| `0x12` | `NE` | - | 2 -> 1 |
| `0x13` | `LT` | - | 2 -> 1 |
| `0x14` | `LE` | - | 2 -> 1 |
| `0x15` | `GT` | - | 2 -> 1 |
| `0x16` | `GE` | - | 2 -> 1 |
| `0x17` | `JUMP` | target | 0 -> 0 |
| `0x18` | `JUMP_IF_FALSE` | target | 1 -> 0 |
| `0x19` | `CALL` | fn idx, argc | argc -> 1 |
| `0x1A` | `CALL_NATIVE` | module const, name const, argc | argc -> 1 |
| `0x1B` | `RET` | - | 1 -> 0 |
| `0x1C` | `PRINT` | - | 1 -> 0 |
| `0x1D` | `DIT` | - | 1 -> 0 |
| `0x1E` | `MAKE_LIST` | n | n -> 1 |
| `0x1F` | `MAKE_MAP` | n pairs | 2n -> 1 |
| `0x20` | `INDEX_GET` | - | 2 -> 1 |
| `0x21` | `LEN` | - | 1 -> 1 |
| `0x22` | `ITER_START` | - | 1 -> 1 |
| `0x23` | `ITER_NEXT` | target | branch (see below) |
| `0x24` | `HALT_OK` | - | 0 -> 0 (terminal) |
| `0x25` | `HALT_POP` | - | 1 -> 0 (terminal) |
| `0x26` | `NEW` | type name const, field count | argc -> 1 |
| `0x27` | `GET_FIELD` | field name const | 1 -> 1 |
| `0x28` | `SET_FIELD` | field name const | 2 -> 0 |
| `0x29` | `CALL_METHOD` | method name const, argc | argc + 1 -> 1 |

`CALL_NATIVE` refers to its module and function by **string constants**, not by
index into a runtime table, so a native is resolved by name at load time and an
unknown one is rejected by the verifier.

### 4.1 `ITER_NEXT` semantics

The iterator stays on the stack. On fallthrough the instruction pushes the next
value (depth `d -> d+1`); when the iterator is exhausted it pops the iterator and
jumps to its target (depth `d -> d-1`). This gives the `per` loop a single
branching instruction with no hidden temporaries.

## 5. Verifier rules

The verifier (`silica/bytecode.py`) rejects a chunk when any of these fail:

**Container**
* entry or init function index out of range; neither present at all
* more than 4096 functions, 65536 constants/globals
* function code empty or larger than 1 MiB

**Function**
* `local_count < arity`, or either exceeds 4096
* code does not end in `RET` / `HALT_OK` / `HALT_POP`
* `NEW` names a type that is not in the type table, or passes a field count that
  does not match that type
* `CALL_METHOD` names a method no type declares, or passes an argument count that
  no declaration accepts
* `GET_FIELD` / `SET_FIELD` name a field no declared type has
* unknown opcode, truncated operand, malformed varint

**Operands**
* `CONST` index outside the constant pool
* `LOAD_LOCAL`/`STORE_LOCAL` slot ≥ `local_count`
* `LOAD_GLOBAL`/`STORE_GLOBAL` index outside the global table
* `CALL` target out of range, or `argc` ≠ callee arity
* `CALL_NATIVE` module/name constants not strings, unknown native, or `argc`
  outside the native's accepted range
* jump target that is not an instruction boundary

**Stack discipline** (abstract interpretation over the control-flow graph)
* stack underflow on any path
* inconsistent stack depth where two paths meet
* control flow falling off the end of the code
* computed peak depth greater than the declared `max_stack`, or greater than the
  4096 hard limit

The compiler does not guess `max_stack`: it runs the same analysis after code
generation and writes the real peak into the function header.

## 6. Versioning policy

* **Minor** version bumps (1.0 → 1.1) add opcodes or optional trailing fields a
  v1.0 reader can ignore. Current readers reject unknown trailing data, so any
  additive change requires a minor bump *and* a reader change; this is
  deliberate.
* **Major** version bumps (1.x → 2.0) may change anything. Readers must refuse a
  major version they do not implement, with a message telling the user to
  recompile.
* A `.sbc` file is tied to the engine that produced it, not to the source: always
  recompile after upgrading when the major version changes.

## 8. Format 1.1 — declared types (Phase 2)

Version 1.1 appends a **type table** to the payload, after the entry point:

```
varint  type_count
  type * {
    varint name length + name
    u8     kind (1 = struct, 0 = class)
    varint field_count;  field * { varint name length + name }   // declaration order
    varint method_count; method * {
      varint name length + name
      varint arity            // explicit arguments; the receiver is implicit
      varint function_index   // the compiled method body
    }
  }
```

The table is what makes the four new opcodes verifiable: `NEW` can be checked
against a declared field count, `CALL_METHOD` against declared arities, and
`GET_FIELD`/`SET_FIELD` against declared field names, all before execution.

**Compatibility.** A reader accepts any `1.x`, and the table is read only when
`minor >= 1`, so **a 1.0 file still loads and runs unchanged** — proven by a test
that ships a hand-built 1.0 payload. Files written by 1.1 are not readable by a
0.9.1 engine, which is the expected direction for an additive change.
