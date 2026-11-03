"""NOP (0x00) is part of the opcode contract, and the runtime must agree with it.

`NOP` is in `OPS`, carries a `(0, 0)` stack effect, and passes the verifier — but
the compiler never emits it, so no source-level test can reach it. `.sbc` is a
versioned artifact that a third party can emit, so the runtime must execute what
the verifier accepts. Before this test existed, a chunk containing `NOP` verified
cleanly and then failed at run time with `unknown opcode 0x00`.

These tests therefore build bytecode **by hand**, with no compiler involved:

* `NOP` advances the instruction pointer and changes nothing else;
* the operand stack is untouched, so the abstract stack depth is unchanged;
* the verifier and the runtime agree, in both directions;
* a hand-written `.sbc` file containing `NOP` loads, verifies and runs;
* the container format is not affected (still magic `SILICABC`, format 1.0).
"""

import io
import os
import tempfile
import unittest

from silica.bytecode import (MAGIC, FORMAT_MAJOR, FORMAT_MINOR, Chunk, Function,
                             OP_NAMES, OPS, STACK_EFFECT, decode, deserialize,
                             encode, serialize, verify_chunk, verify_function)
from silica.engine import load_bytecode, run_chunk
from silica.errors import SilicaError


def build(body, constants=(), max_stack=1):
    """A one-function chunk from (name, *operands) tuples."""
    code = b"".join(encode(name, *args) for name, *args in body)
    fn = Function("main", arity=0, n_locals=0, max_stack=max_stack,
                  ret_type="Unit", code=code, lines=[(0, 1)])
    return Chunk(constants=list(constants), globals=[], functions=[fn], entry=0)


def run(chunk):
    """(stdout, exit code) for a verified chunk."""
    verify_chunk(chunk, "<nop>")
    out = io.StringIO()
    code = run_chunk(chunk, "<nop>", stdin=io.StringIO(""), stdout=out,
                     stderr=io.StringIO())
    return out.getvalue(), code


class NopContractTests(unittest.TestCase):
    def test_nop_is_opcode_zero_with_no_stack_effect(self):
        self.assertEqual(OPS["NOP"], 0x00)
        self.assertEqual(STACK_EFFECT["NOP"], (0, 0))
        self.assertEqual(OP_NAMES[0x00], "NOP")

    def test_the_container_format_is_unchanged(self):
        # The correction must not touch the format: only the VM learned a handler.
        self.assertEqual(MAGIC, b"SILICABC")
        self.assertEqual((FORMAT_MAJOR, FORMAT_MINOR), (1, 0))


class NopVerifierTests(unittest.TestCase):
    def test_the_verifier_accepts_nop_anywhere(self):
        cases = {
            "leading": [("NOP",), ("HALT_OK",)],
            "between": [("CONST", 0), ("NOP",), ("PRINT",), ("HALT_OK",)],
            "trailing": [("NOP",), ("NOP",), ("HALT_OK",)],
            "only": [("NOP",), ("HALT_OK",)],
        }
        for label, body in cases.items():
            with self.subTest(position=label):
                verify_chunk(build(body, constants=["x"]), "<nop>")

    def test_nop_does_not_change_the_abstract_stack_depth(self):
        # The verifier's stack analysis must be unaffected: NOP pops and pushes
        # nothing, so the peak depth is the same as the program without it.
        plain = build([("CONST", 0), ("PRINT",), ("HALT_OK",)], constants=["x"])
        padded = build([("NOP",), ("CONST", 0), ("NOP",), ("PRINT",), ("NOP",),
                        ("HALT_OK",)], constants=["x"])
        verify_chunk(plain, "<nop>")
        verify_chunk(padded, "<nop>")
        depth_plain = verify_function(plain, plain.functions[0], 0, "<nop>")
        depth_padded = verify_function(padded, padded.functions[0], 0, "<nop>")
        self.assertEqual(depth_plain, depth_padded)
        self.assertEqual(depth_padded, 1)

    def test_a_jump_may_target_a_nop(self):
        # NOP is an instruction boundary, so a jump target landing on one is legal
        # and the verifier must keep accepting it. Layout: NOP@0 (1 byte),
        # JUMP@1 (5 bytes, target 6), NOP@6, HALT_OK@7.
        body = [("NOP",), ("JUMP", 6), ("NOP",), ("HALT_OK",)]
        chunk = build(body)
        offsets = [ins.offset for ins in decode(chunk.functions[0].code, "<nop>", "main")]
        self.assertEqual(offsets, [0, 1, 6, 7])
        verify_chunk(chunk, "<nop>")
        # and it runs: the jump lands on the NOP, which falls through to HALT_OK
        out, code = run(chunk)
        self.assertEqual((out, code), ("", 0))


class NopRuntimeTests(unittest.TestCase):
    def test_the_runtime_executes_nop(self):
        # This is the regression: it raised `unknown opcode 0x00` before the fix.
        out, code = run(build([("NOP",), ("HALT_OK",)]))
        self.assertEqual(out, "")
        self.assertEqual(code, 0)

    def test_nop_leaves_the_operand_stack_alone(self):
        # A value pushed before the NOPs must still be on the stack for PRINT.
        out, _code = run(build([("CONST", 0), ("NOP",), ("NOP",), ("NOP",),
                                ("PRINT",), ("HALT_OK",)], constants=["kept"]))
        self.assertEqual(out, "kept\n")

    def test_the_instruction_pointer_advances_past_each_nop(self):
        body = [("NOP",)] * 8 + [("CONST", 0), ("PRINT",), ("HALT_OK",)]
        chunk = build(body, constants=["after"])
        # each NOP is exactly one byte, and the offsets are strictly increasing
        decoded = decode(chunk.functions[0].code, "<nop>", "main")
        nops = [ins for ins in decoded if ins.name == "NOP"]
        self.assertEqual(len(nops), 8)
        self.assertEqual([ins.offset for ins in nops], list(range(8)))
        self.assertEqual({ins.size for ins in nops}, {1})
        # and execution still reaches the instruction after the last NOP
        out, _code = run(chunk)
        self.assertEqual(out, "after\n")

    def test_nop_is_semantically_invisible(self):
        # Differential: inserting NOPs anywhere must not change observable output.
        plain = build([("CONST", 0), ("CONST", 1), ("ADD",), ("PRINT",),
                       ("HALT_OK",)], constants=[2, 3], max_stack=2)
        padded = build([("NOP",), ("CONST", 0), ("NOP",), ("CONST", 1), ("NOP",),
                        ("ADD",), ("NOP",), ("PRINT",), ("NOP",), ("HALT_OK",)],
                       constants=[2, 3], max_stack=2)
        self.assertEqual(run(plain), run(padded))
        self.assertEqual(run(padded)[0], "5\n")


class HandWrittenBytecodeTests(unittest.TestCase):
    """A `.sbc` file assembled by hand, with no compiler in the loop."""

    def test_a_hand_written_sbc_with_nop_round_trips_and_runs(self):
        chunk = build([("NOP",), ("CONST", 0), ("NOP",), ("PRINT",), ("NOP",),
                       ("HALT_OK",)], constants=["from bytecode"])
        data = serialize(chunk)

        handle, path = tempfile.mkstemp(suffix=".sbc")
        os.close(handle)
        try:
            with open(path, "wb") as fh:
                fh.write(data)

            # load_bytecode deserialises *and* verifies, so this exercises the
            # whole path a third-party .sbc takes.
            loaded = load_bytecode(path)
            self.assertEqual(len(loaded.constants), 1)
            self.assertIn("NOP", [ins.name for ins in
                                  decode(loaded.functions[0].code, path, "main")])

            out = io.StringIO()
            code = run_chunk(loaded, path, stdin=io.StringIO(""), stdout=out,
                             stderr=io.StringIO())
            self.assertEqual(out.getvalue(), "from bytecode\n")
            self.assertEqual(code, 0)
        finally:
            os.unlink(path)

    def test_the_serialised_bytes_are_stable(self):
        # The format did not change: same chunk, same bytes, header intact.
        chunk = build([("NOP",), ("HALT_OK",)])
        data = serialize(chunk)
        self.assertEqual(data[:8], MAGIC)
        self.assertEqual(data[8:12], b"\x01\x00\x00\x00")   # major 1, minor 0
        self.assertEqual(data, serialize(build([("NOP",), ("HALT_OK",)])))
        # and it deserialises back to the same instruction stream
        again = deserialize(data, "<nop>")
        self.assertEqual(again.functions[0].code, chunk.functions[0].code)


if __name__ == "__main__":
    unittest.main()
