"""Script Mode IDE tests: the API, the runner, and the real toolchain.

The IDE is a local web application, so the tests drive its HTTP API the way the
browser does — including the token, because an unauthenticated request must fail.

Two tiers:

* **API and security** — files, paths, tokens, argument validation. No browser.
* **Execution** — starts the real `silica run` through the IDE and asserts on the
  actual stdout, stderr, exit code and parsed diagnostics.

What is *not* tested: the rendering of the HTML in a browser. There is no browser
in this environment, so the front-end is verified structurally (it is served, it
carries the token, it references the endpoints it uses) and by hand. `docs/IDE.md`
says so rather than implying a visual check happened.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from silica.ide import Workspace, parse_diagnostics, serve

HELLO = 'sfn main() {\n    sprint("Hello from Silica")\n}\n'
BROKEN = "sfn main() {\n    sprint(\n}\n"
SLOW = ("sfn main() {\n    let i: Int = 0\n    tant i < 400000000 {\n"
        "        i = i + 1\n    }\n    sprint(i)\n}\n")


class IDEHarness(unittest.TestCase):
    """Starts a real server on a free port and talks to it over HTTP."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="silica-ide-")
        cls.httpd, url = serve(cls.root, port=0, open_browser=False, quiet=True)
        parsed = urllib.parse.urlparse(url)
        cls.token = urllib.parse.parse_qs(parsed.query)["token"][0]
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    # -- helpers --------------------------------------------------------------
    def url(self, path, token=True):
        separator = "&" if "?" in path else "?"
        return self.base + path + (separator + "token=" + self.token if token else "")

    def call(self, path, data=None, token=True, raw=False):
        request = urllib.request.Request(
            self.url(path, token), method="POST" if data is not None else "GET")
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, body, timeout=120) as response:
            payload = response.read().decode("utf-8")
            return payload if raw else json.loads(payload)

    def fails(self, path, data=None, token=True):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call(path, data, token)
        return caught.exception.code

    def write(self, name, text):
        self.call("/api/file", {"path": name, "text": text})

    def run_script(self, name, limit=250):
        started = self.call("/api/run", {"path": name})
        for _ in range(limit):
            snapshot = self.call("/api/run?id=" + started["id"])
            if snapshot["status"] in ("finished", "failed", "stopped"):
                return snapshot
            time.sleep(0.05)
        self.fail("run did not finish in time")


class SecurityTests(IDEHarness):
    def test_requests_without_a_token_are_refused(self):
        self.assertEqual(self.fails("/api/meta", token=False), 401)

    def test_a_wrong_token_is_refused(self):
        request = urllib.request.Request(self.base + "/api/meta?token=wrong")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=30)
        self.assertEqual(caught.exception.code, 401)

    def test_the_index_page_needs_the_token_too(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/", timeout=30)
        self.assertEqual(caught.exception.code, 401)

    def test_paths_cannot_escape_the_workspace(self):
        for attempt in ("../outside.sc", "../../etc/passwd", "/etc/passwd",
                        "nested/../../escape.sc"):
            with self.subTest(path=attempt):
                self.assertIn(self.fails("/api/file?path=" + urllib.parse.quote(attempt)),
                              (403, 404))

    def test_writing_outside_the_workspace_is_refused(self):
        self.assertIn(self.fails("/api/file", {"path": "../escape.sc", "text": "x"}),
                      (400, 403))

    def test_only_sc_files_can_be_written(self):
        self.assertEqual(self.fails("/api/file", {"path": "notes.txt", "text": "x"}), 400)

    def test_a_null_byte_in_a_path_is_refused(self):
        self.assertIn(self.fails("/api/file?path=a%00b.sc"), (400, 403, 404))

    def test_the_workspace_resolves_inside_itself(self):
        workspace = Workspace(self.root)
        self.assertTrue(workspace.resolve("a.sc").startswith(workspace.root))
        with self.assertRaises(Exception):
            workspace.resolve("../x.sc")


class FileTests(IDEHarness):
    def test_a_script_can_be_created_read_and_saved(self):
        self.write("new.sc", HELLO)
        self.assertEqual(self.call("/api/file?path=new.sc")["text"], HELLO)
        self.write("new.sc", HELLO + "\n")
        self.assertEqual(self.call("/api/file?path=new.sc")["text"], HELLO + "\n")

    def test_listing_shows_only_sc_files(self):
        self.write("listed.sc", HELLO)
        with open(os.path.join(self.root, "ignored.txt"), "w") as handle:
            handle.write("no")
        paths = [f["path"] for f in self.call("/api/files")["files"]]
        self.assertIn("listed.sc", paths)
        self.assertNotIn("ignored.txt", paths)

    def test_reading_a_missing_file_is_404(self):
        self.assertEqual(self.fails("/api/file?path=absent.sc"), 404)

    def test_metadata_comes_from_the_implementation(self):
        meta = self.call("/api/meta")
        from silica import __version__
        from silica.tokens import KEYWORDS
        self.assertEqual(meta["version"], __version__)
        for keyword in ("sfn", "sprint", "si", "oui", "nein"):
            self.assertIn(keyword, meta["keywords"])
        self.assertEqual(sorted(meta["keywords"]), sorted(KEYWORDS))

    def test_the_page_is_served_with_the_token_embedded(self):
        page = self.call("/", raw=True)
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn(self.token, page)
        self.assertNotIn("__SILICA_TOKEN__", page)

    def test_the_page_references_the_endpoints_it_uses(self):
        page = self.call("/", raw=True)
        for endpoint in ("/api/meta", "/api/files", "/api/file", "/api/run", "/api/stop"):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, page)


class ExecutionTests(IDEHarness):
    def test_a_valid_script_runs_with_real_output(self):
        self.write("ok.sc", HELLO)
        snapshot = self.run_script("ok.sc")
        self.assertEqual(snapshot["status"], "finished")
        self.assertEqual(snapshot["exit_code"], 0)
        self.assertEqual(snapshot["stdout"], "Hello from Silica\n")
        self.assertEqual(snapshot["stderr"], "")

    def test_the_optimizer_is_live_in_the_ide(self):
        self.write("fold.sc", "sfn main() {\n    sprint(2 + 3 * 4)\n}\n")
        snapshot = self.run_script("fold.sc")
        self.assertEqual(snapshot["stdout"], "14\n")

    def test_a_compile_error_is_reported_with_its_location(self):
        self.write("bad.sc", BROKEN)
        snapshot = self.run_script("bad.sc")
        self.assertEqual(snapshot["exit_code"], 1)
        self.assertIn("parse error", snapshot["stderr"])
        self.assertTrue(snapshot["diagnostics"], "no structured diagnostic parsed")
        diagnostic = snapshot["diagnostics"][0]
        self.assertEqual(diagnostic["kind"], "parse error")
        self.assertGreaterEqual(diagnostic["line"], 1)
        self.assertTrue(diagnostic["path"].endswith("bad.sc"))

    def test_a_runtime_error_is_reported(self):
        self.write("runtime.sc", "sfn main() {\n    sprint(1 / 0)\n}\n")
        snapshot = self.run_script("runtime.sc")
        self.assertEqual(snapshot["exit_code"], 1)
        self.assertIn("division by zero", snapshot["stderr"])
        self.assertEqual(snapshot["diagnostics"][0]["kind"], "runtime error")

    def test_a_missing_script_is_refused(self):
        self.assertEqual(self.fails("/api/run", {"path": "nope.sc"}), 404)

    def test_a_running_script_can_be_stopped(self):
        self.write("slow.sc", SLOW)
        started = self.call("/api/run", {"path": "slow.sc"})
        time.sleep(0.6)
        stopped = self.call("/api/stop", {"id": started["id"]})
        self.assertEqual(stopped["status"], "stopped")
        self.assertTrue(stopped["stopped"])

    def test_unknown_run_ids_are_404(self):
        self.assertEqual(self.fails("/api/run?id=999"), 404)
        self.assertEqual(self.fails("/api/stop", {"id": "999"}), 404)

    def test_diagnostics_parser_handles_both_error_shapes(self):
        stderr = ("/tmp/a.sc:3:1: parse error: unexpected '}'\n"
                  "  hint: something\n"
                  "/tmp/a.sc:7: runtime error: division by zero\n")
        found = parse_diagnostics(stderr)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["kind"], "parse error")
        self.assertEqual(found[0]["line"], 3)
        self.assertEqual(found[0]["col"], 1)
        self.assertEqual(found[1]["kind"], "runtime error")
        self.assertEqual(found[1]["col"], 0)

    def test_unrelated_stderr_produces_no_diagnostics(self):
        self.assertEqual(parse_diagnostics("Traceback (most recent call last):\n"), [])


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io
        from silica import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_help_documents_the_options(self):
        code, out, _ = self.run_cli(["ide", "--help"])
        self.assertEqual(code, 0)
        for option in ("--root", "--port", "--host", "--no-open"):
            self.assertIn(option, out)

    def test_a_bad_port_is_a_usage_error(self):
        code, _out, err = self.run_cli(["ide", "--port", "abc"])
        self.assertEqual(code, 2)
        self.assertIn("needs a number", err)

    def test_an_unknown_option_is_a_usage_error(self):
        code, _out, err = self.run_cli(["ide", "--frobnicate"])
        self.assertEqual(code, 2)
        self.assertIn("unexpected argument", err)

    def test_a_missing_workspace_is_reported(self):
        code, _out, err = self.run_cli(["ide", "--root", "/definitely/not/here"])
        self.assertEqual(code, 1)
        self.assertIn("workspace", err.lower())


if __name__ == "__main__":
    unittest.main()
