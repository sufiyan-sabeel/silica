"""Bytecode tests: serialization stability, versioning, and verifier rejections.

Every rejection test builds a deliberately broken chunk and asserts the
verifier refuses it, so an untrusted .sbc file cannot make the VM misbehave.
"""

import struct
import unittest
import zlib

from silica.bytecode import (FORMAT_MAJOR, MAGIC, Chunk, Function, deserialize,
                             encode, serialize, verify_chunk)
from silica.errors import VerifyError
from silica.engine import compile_source

from .helpers import make_chunk


def rejects(testcase, chunk, fragment):
    with testcase.assertRaises(VerifyError) as ctx:
        verify_chunk(chunk, "<test>")
    testcase.assertIn(fragment, ctx.exception.message)
    return ctx.exception


def ret():
    return encode("UNIT") + encode("RET")


class SerializationTests(unittest.TestCase):
    def test_roundtrip_preserves_every_field(self):
        fn = Function("main", 0, 3, 7, "Int",
                      encode("CONST", 0) + encode("RET"), [(0, 4), (2, 5)])
        chunk = Chunk([42, 1.5, "text", True], [("g", "String")], [fn], entry=0,
                      init=None)
        data = serialize(chunk)
        self.assertEqual(data[:8], MAGIC)
        self.assertEqual(struct.unpack_from("<H", data, 8)[0], FORMAT_MAJOR)
        back = deserialize(data)
        self.assertEqual(back.constants, [42, 1.5, "text", True])
        self.assertEqual(back.globals, [("g", "String")])
        self.assertEqual(back.entry, 0)
        self.assertIsNone(back.init)
        self.assertEqual(back.functions[0].name, "main")
        self.assertEqual(back.functions[0].n_locals, 3)
        self.assertEqual(back.functions[0].max_stack, 7)
        self.assertEqual(back.functions[0].ret_type, "Int")
        self.assertEqual(back.functions[0].lines, [(0, 4), (2, 5)])
        self.assertEqual(back.functions[0].code, fn.code)

    def test_compiled_program_roundtrips_and_runs(self):
        chunk = compile_source("sfn main() {\n sprint(7)\n}\n").chunk
        back = deserialize(serialize(chunk))
        verify_chunk(back)
        self.assertEqual([f.name for f in back.functions], ["main"])

    def test_serialization_is_deterministic(self):
        chunk = compile_source("sfn main() {\n sprint(1 + 2)\n}\n").chunk
        self.assertEqual(serialize(chunk), serialize(chunk))

    def test_bad_magic(self):
        data = bytearray(serialize(make_chunk(ret())))
        data[0] = ord("X")
        with self.assertRaises(VerifyError) as ctx:
            deserialize(bytes(data))
        self.assertIn("magic", ctx.exception.message)

    def test_unsupported_version(self):
        data = bytearray(serialize(make_chunk(ret())))
        struct.pack_into("<H", data, 8, 99)
        with self.assertRaises(VerifyError) as ctx:
            deserialize(bytes(data))
        self.assertIn("unsupported bytecode format version", ctx.exception.message)

    def test_nonzero_flags_rejected(self):
        data = bytearray(serialize(make_chunk(ret())))
        data[12] = 1
        with self.assertRaises(VerifyError) as ctx:
            deserialize(bytes(data))
        self.assertIn("flags", ctx.exception.message)

    def test_corrupted_payload_fails_checksum(self):
        data = bytearray(serialize(make_chunk(ret())))
        data[-1] ^= 0xFF
        with self.assertRaises(VerifyError) as ctx:
            deserialize(bytes(data))
        self.assertIn("checksum", ctx.exception.message)

    def test_truncated_file(self):
        data = serialize(make_chunk(ret()))
        with self.assertRaises(VerifyError):
            deserialize(data[:10])

    def test_trailing_bytes_detected(self):
        data = bytearray(serialize(make_chunk(ret())))
        payload = bytes(data[17:]) + b"\x00"
        data[13:17] = struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)
        with self.assertRaises(VerifyError) as ctx:
            deserialize(bytes(data) + b"\x00")
        self.assertIn("trailing", ctx.exception.message)

    def test_truncated_payload_with_valid_checksum(self):
        data = bytearray(serialize(make_chunk(ret())))
        payload = bytes(data[17:])[:-3]
        data[13:17] = struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)
        with self.assertRaises(VerifyError) as ctx:
            deserialize(bytes(data[:17]) + payload)
        self.assertIn("truncated", ctx.exception.message)


class VerifierTests(unittest.TestCase):
    def test_valid_chunk_passes(self):
        verify_chunk(make_chunk(ret()))

    def test_no_entry_point(self):
        chunk = make_chunk(ret(), entry=None)
        rejects(self, chunk, "no entry point")

    def test_entry_out_of_range(self):
        rejects(self, make_chunk(ret(), entry=5), "entry function index")

    def test_unknown_opcode(self):
        rejects(self, make_chunk(bytes([0xFF])), "unknown opcode")

    def test_code_must_terminate(self):
        rejects(self, make_chunk(encode("UNIT")), "does not end with RET or HALT")

    def test_empty_code(self):
        rejects(self, make_chunk(b""), "empty code")

    def test_constant_index_out_of_range(self):
        rejects(self, make_chunk(encode("CONST", 3) + ret()), "constant index")

    def test_local_slot_out_of_range(self):
        rejects(self, make_chunk(encode("LOAD_LOCAL", 9) + ret(), n_locals=2),
                "local slot")

    def test_global_index_out_of_range(self):
        rejects(self, make_chunk(encode("LOAD_GLOBAL", 0) + ret()), "global index")

    def test_jump_target_must_be_instruction_boundary(self):
        code = encode("JUMP", 1) + encode("UNIT") + encode("RET")
        rejects(self, make_chunk(code), "not an instruction boundary")

    def test_stack_underflow(self):
        rejects(self, make_chunk(encode("ADD") + ret()), "underflow")

    def test_stack_depth_must_agree_at_joins(self):
        # TRUE / JUMP_IF_FALSE -> L / TRUE / JUMP L / L: UNIT RET
        # fallthrough path reaches L with depth 1, jump path with depth 0
        prefix = encode("TRUE") + encode("JUMP_IF_FALSE", 12)
        middle = encode("TRUE") + encode("JUMP", 12)
        tail = encode("UNIT") + encode("RET")
        code = prefix + middle + tail
        rejects(self, make_chunk(code), "inconsistent stack depth")

    def test_declared_max_stack_must_be_sufficient(self):
        chunk = make_chunk(encode("CONST", 0) + ret(), constants=[1], max_stack=0)
        rejects(self, chunk, "declares max stack")

    def test_call_arity_must_match(self):
        callee = Function("f", 1, 1, 4, "Unit", ret(), [])
        caller = Function("main", 0, 2, 8, "Unit", encode("CALL", 1, 0) + ret(), [])
        chunk = Chunk([], [], [caller, callee], entry=0)
        rejects(self, chunk, "passes 0 argument")

    def test_call_target_out_of_range(self):
        chunk = make_chunk(encode("CALL", 9, 0) + ret())
        rejects(self, chunk, "call target")

    def test_unknown_native(self):
        chunk = make_chunk(encode("CALL_NATIVE", 0, 1, 0) + ret(),
                           constants=["core", "nope"])
        rejects(self, chunk, "unknown function 'core.nope'")

    def test_native_argument_count_checked(self):
        chunk = make_chunk(encode("CALL_NATIVE", 0, 1, 0) + ret(),
                           constants=["core", "range"])
        rejects(self, chunk, "passes 0 argument")

    def test_native_requires_string_constants(self):
        chunk = make_chunk(encode("CALL_NATIVE", 0, 1, 0) + ret(), constants=[1, 2])
        rejects(self, chunk, "non-string module/function constant")

    def test_too_many_locals(self):
        fn = Function("main", 0, 99999, 4, "Unit", ret(), [])
        rejects(self, Chunk([], [], [fn], entry=0), "too many locals")

    def test_fewer_locals_than_parameters(self):
        fn = Function("main", 3, 1, 4, "Unit", ret(), [])
        rejects(self, Chunk([], [], [fn], entry=0), "fewer locals")


if __name__ == "__main__":
    unittest.main()
