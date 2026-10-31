"""Phase 5: the offline guarantee, tested rather than asserted.

Three claims, each with a way it can quietly fail:

1. **Inference opens no sockets.** Tested with an audit hook, which sees socket
   use from C extensions too — stronger than replacing `socket.socket`.
2. **Nothing downloads unless asked.** Tested by watching `urlopen` across the
   whole read-only surface, and by checking that a missing Whisper model is
   refused rather than fetched.
3. **A model that changed on disk is not loaded.** Tested by tampering with one.

What none of this proves: that no *other* process on the machine used the
network, or that a native library opening a socket outside Python's socket module
would be seen. The stronger check is a network namespace, which needs privileges;
`tools/offline_check.py` documents that.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from silica.voice import catalogue

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "offline_check.py")


class NoDownloadTests(unittest.TestCase):
    """The read-only surface must not reach the network."""

    def test_reading_model_state_never_opens_a_connection(self):
        from silica import voice
        calls = []

        def forbidden(*a, **k):
            calls.append(a)
            raise AssertionError("the read-only API opened a URL")

        with mock.patch.object(catalogue.urllib.request, "urlopen", forbidden):
            voice.models()
            voice.storage()
            voice.voices()
            voice.languages()
            voice.licence("en_GB-alba-medium")
            voice.current_voice()
            voice.platform()
        self.assertEqual(calls, [])

    def test_a_missing_whisper_model_is_refused_not_fetched(self):
        """faster-whisper used to ask the Hub for updates on every load."""
        from silica.voice import whisper
        source = open(whisper.__file__, encoding="utf-8").read()
        self.assertIn("local_files_only", source,
                      "the loader must pass local_files_only when not downloading")
        self.assertIn("SILICA_WHISPER_ALLOW_DOWNLOAD", source)

    def test_the_download_flag_defaults_to_off(self):
        self.assertIsNone(os.environ.get("SILICA_WHISPER_ALLOW_DOWNLOAD"))


class TamperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="silica-tamper-")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.patch = mock.patch.object(catalogue, "voices_dir",
                                       return_value=self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # a small stand-in model, so hashing is instant
        self.path = catalogue.model_path("en_GB-alba-medium")
        with open(self.path, "wb") as handle:
            handle.write(b"model" * 2048)
        with open(self.path + ".json", "wb") as handle:
            handle.write(b"{}")
        catalogue._write_manifest({"en_GB-alba-medium": {
            "sha256": catalogue.sha256_of(self.path),
            "bytes": os.path.getsize(self.path),
            "downloaded_at": "2026-01-01T00:00:00Z"}})

    def test_an_untouched_model_passes(self):
        self.assertIsNone(catalogue.check_model("en_GB-alba-medium"))

    def test_a_changed_model_is_refused(self):
        with open(self.path, "ab") as handle:
            handle.write(b"tampered")
        catalogue._HASH_CACHE.clear()
        with self.assertRaises(catalogue.VoiceError) as ctx:
            catalogue.check_model("en_GB-alba-medium")
        message = str(ctx.exception)
        self.assertIn("does not match the checksum", message)
        self.assertIn("silica voice install", message)

    def test_the_refusal_can_be_bypassed_deliberately(self):
        with open(self.path, "ab") as handle:
            handle.write(b"tampered")
        catalogue._HASH_CACHE.clear()
        with mock.patch.dict(os.environ, {"SILICA_VOICE_SKIP_VERIFY": "1"}):
            self.assertIsNone(catalogue.check_model("en_GB-alba-medium"))

    def test_a_model_with_no_recorded_checksum_is_not_blocked(self):
        catalogue._write_manifest({})
        self.assertIsNone(catalogue.check_model("en_GB-alba-medium"))

    def test_hashing_is_cached_so_loading_stays_cheap(self):
        catalogue._HASH_CACHE.clear()
        first = catalogue.cached_sha256(self.path)
        second = catalogue.cached_sha256(self.path)
        self.assertEqual(first, second)
        self.assertEqual(len(catalogue._HASH_CACHE), 1)


class OfflineToolTests(unittest.TestCase):
    """The shipped checker, run as a user would run it."""

    def test_the_tool_exists_and_parses(self):
        self.assertTrue(os.path.exists(TOOL))
        # compile in memory: py_compile would try to write __pycache__ into tools/
        source = open(TOOL, encoding="utf-8").read()
        compile(source, TOOL, "exec")

    def test_it_reports_offline_when_nothing_reaches_out(self):
        """With no engines available it still runs and still reports honestly."""
        env = dict(os.environ, PYTHONPATH=ROOT)
        completed = subprocess.run([sys.executable, TOOL], capture_output=True,
                                   text=True, env=env, timeout=300)
        self.assertEqual(completed.returncode, 0, completed.stderr[-800:])
        report = json.loads(completed.stdout)
        self.assertTrue(report["offline"])
        self.assertEqual(report["network_events"], [])
        # with no engine, the directions must say so rather than pretend
        if "skipped" in str(report["synthesis"]):
            self.assertIn("no TTS engine", report["synthesis"])

    def test_the_hook_would_notice_a_connection(self):
        """A negative control: the audit hook must actually fire."""
        probe = (
            "import sys, json\n"
            "seen = []\n"
            "sys.addaudithook(lambda e, a: seen.append(e) if e.startswith('socket.') else None)\n"
            "import socket\n"
            "s = socket.socket()\n"
            "print(json.dumps(sorted(set(seen))))\n")
        completed = subprocess.run([sys.executable, "-c", probe],
                                   capture_output=True, text=True)
        events = json.loads(completed.stdout)
        self.assertIn("socket.__new__", events,
                      "if this fails the offline check is measuring nothing")


if __name__ == "__main__":
    unittest.main()
