"""Engine pipeline tests: the full source -> bytecode -> run path."""

import io
import os
import tempfile
import unittest

from silica.engine import (compile_source, default_output_path, is_bytecode,
                           load_bytecode, run_source)
from silica.errors import SilicaError


class PipelineTests(unittest.TestCase):
    def test_pipeline_runs_and_reports_exit_code(self):
        out = io.StringIO()
        code = run_source("sfn main() {\n    sprint(1)\n    halt(3)\n}\n",
                          stdout=out, stdin=io.StringIO(""))
        self.assertEqual(code, 3)
        self.assertEqual(out.getvalue(), "1\n")

    def test_compile_returns_verified_chunk(self):
        result = compile_source("sfn main() {\n    sprint(2 + 2)\n}\n")
        self.assertEqual(result.chunk.entry, 0)
        self.assertEqual(result.chunk.functions[0].name, "main")
        self.assertGreater(result.chunk.functions[0].max_stack, 0)

    def test_globals_use_an_init_function(self):
        result = compile_source('let g: Int = 5\nsfn main() {\n    sprint(g)\n}\n')
        self.assertIsNotNone(result.chunk.init)
        self.assertEqual(result.chunk.globals, [("g", "Int")])

    def test_no_init_without_globals(self):
        result = compile_source("sfn main() {\n}\n")
        self.assertIsNone(result.chunk.init)

    def test_deeply_nested_source_is_a_diagnostic_not_a_crash(self):
        source = "sfn main() {\n    sprint(%s1%s)\n}\n" % ("(" * 300, ")" * 300)
        with self.assertRaises(SilicaError) as ctx:
            compile_source(source)
        self.assertIn("nesting is too deep", ctx.exception.message)

    def test_comments_are_reported_for_the_formatter(self):
        result = compile_source("# note\nsfn main() {\n}\n")
        self.assertEqual(result.comments, ["# note"])

    def test_output_path_sits_next_to_the_source(self):
        self.assertEqual(default_output_path("src/main.sc"), "src/main.sbc")
        self.assertEqual(default_output_path("main.sc"), "main.sbc")

    def test_is_bytecode(self):
        self.assertTrue(is_bytecode("a.sbc"))
        self.assertFalse(is_bytecode("a.sc"))


class BytecodeFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="silica-engine-")

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_load_bytecode_from_disk(self):
        from silica.bytecode import serialize
        chunk = compile_source("sfn main() {\n    sprint(9)\n}\n").chunk
        path = os.path.join(self.dir, "main.sbc")
        with open(path, "wb") as handle:
            handle.write(serialize(chunk))
        loaded = load_bytecode(path)
        out = io.StringIO()
        from silica.engine import run_chunk
        run_chunk(loaded, path, stdin=io.StringIO(""), stdout=out)
        self.assertEqual(out.getvalue(), "9\n")

    def test_load_bytecode_rejects_garbage(self):
        path = os.path.join(self.dir, "bad.sbc")
        with open(path, "wb") as handle:
            handle.write(b"not bytecode at all")
        with self.assertRaises(SilicaError):
            load_bytecode(path)


if __name__ == "__main__":
    unittest.main()
