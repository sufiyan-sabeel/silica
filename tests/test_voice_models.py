"""Phase 4: the model-management API.

Four things are being tested, and each has a failure mode worth catching:

* **`set_voice` persists and respects precedence** — an explicit argument beats
  the environment, which beats the saved choice, which beats whatever happens to
  be installed.
* **`download_model` never runs on its own** and needs its own capability, because
  it reaches the network and the disk.
* **`verify` detects a changed file**, using the checksum recorded at download.
* **`delete_model` frees what it claims**, and refuses what is not there.

No network is used: downloads are exercised against a fake `urlopen`.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from silica.capabilities import SPEECH_MODELS, CapabilitySet
from silica.voice import catalogue


class FakeDownload:
    """Serve a voice without touching the network."""

    def __init__(self, payload=b"x" * 4096):
        self.payload = payload
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        payload = self.payload

        class Response:
            def read(self, size=-1):
                nonlocal payload
                data, payload = payload, b""
                return data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Response()


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="silica-models-")
        self.addCleanup(__import__("shutil").rmtree, self.directory, True)
        self.patch = mock.patch.object(catalogue, "voices_dir",
                                       return_value=self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def install(self, name="en_GB-alba-medium"):
        with mock.patch.object(catalogue.urllib.request, "urlopen", FakeDownload()):
            return catalogue.download(name)

    def test_models_lists_only_installed_voices(self):
        self.assertEqual(catalogue.models(), [])
        self.install()
        rows = catalogue.models()
        self.assertEqual([r["name"] for r in rows], ["en_GB-alba-medium"])
        row = rows[0]
        for key in ("name", "language", "bytes", "sha256", "licence",
                    "licence_verified", "commercial_use", "downloaded_at"):
            self.assertIn(key, row)

    def test_a_download_records_a_checksum(self):
        self.install()
        recorded = catalogue.manifest()["en_GB-alba-medium"]
        self.assertEqual(len(recorded["sha256"]), 64)
        self.assertGreater(recorded["bytes"], 0)
        self.assertIn("downloaded_at", recorded)

    def test_verify_passes_for_an_untouched_file(self):
        self.install()
        result = catalogue.verify("en_GB-alba-medium")
        self.assertTrue(result["verified"])
        self.assertIsNone(result["reason"])

    def test_verify_notices_a_changed_file(self):
        self.install()
        path = catalogue.model_path("en_GB-alba-medium")
        with open(path, "ab") as handle:
            handle.write(b"tampered")
        result = catalogue.verify("en_GB-alba-medium")
        self.assertFalse(result["verified"])
        self.assertIn("changed", result["reason"])

    def test_verify_says_so_when_nothing_was_recorded(self):
        self.install()
        # a voice installed before the manifest existed
        os.unlink(catalogue.manifest_path())
        result = catalogue.verify("en_GB-alba-medium")
        self.assertFalse(result["verified"])
        self.assertIn("no checksum", result["reason"])

    def test_verify_on_a_missing_voice_is_not_an_error(self):
        result = catalogue.verify("en_GB-alba-medium")
        self.assertFalse(result["installed"])
        self.assertFalse(result["verified"])

    def test_delete_removes_both_files_and_reports_the_bytes(self):
        self.install()
        before = catalogue.storage()["model_bytes"]
        freed = catalogue.delete("en_GB-alba-medium")
        self.assertGreater(freed, 0)
        self.assertEqual(catalogue.installed(), [])
        # model_bytes excludes the manifest, which itself shrinks on delete
        self.assertEqual(catalogue.storage()["model_bytes"], before - freed)
        self.assertNotIn("en_GB-alba-medium", catalogue.manifest())

    def test_deleting_something_not_installed_is_refused(self):
        with self.assertRaises(catalogue.VoiceError) as ctx:
            catalogue.delete("en_GB-alba-medium")
        self.assertIn("not installed", str(ctx.exception))

    def test_deleting_an_unknown_voice_is_refused(self):
        with self.assertRaises(catalogue.VoiceError):
            catalogue.delete("not-a-voice")

    def test_storage_accounts_for_every_file(self):
        self.install()
        storage = catalogue.storage()
        self.assertEqual(storage["voices"], ["en_GB-alba-medium"])
        total = sum(f["bytes"] for f in storage["files"])
        self.assertEqual(storage["bytes"], total)
        self.assertGreater(storage["model_bytes"], 0)
        self.assertGreaterEqual(storage["bytes"], storage["model_bytes"])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="silica-select-")
        self.addCleanup(__import__("shutil").rmtree, self.directory, True)
        for patch in (mock.patch.object(catalogue, "voices_dir",
                                        return_value=self.directory),
                      mock.patch.dict(os.environ, {}, clear=False)):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("SILICA_VOICE", None)
        with mock.patch.object(catalogue.urllib.request, "urlopen", FakeDownload()):
            catalogue.download("en_GB-alba-medium")
            catalogue.download("te_IN-padmavathi-medium")

    def test_the_choice_persists_to_disk(self):
        catalogue.set_selected("te_IN-padmavathi-medium")
        self.assertTrue(os.path.exists(catalogue.selection_path()))
        self.assertEqual(catalogue.selected(), "te_IN-padmavathi-medium")

    def test_the_choice_can_be_cleared(self):
        catalogue.set_selected("te_IN-padmavathi-medium")
        catalogue.set_selected(None)
        self.assertIsNone(catalogue.selected())
        self.assertFalse(os.path.exists(catalogue.selection_path()))

    def test_choosing_an_uninstalled_voice_is_refused(self):
        with self.assertRaises(catalogue.VoiceError) as ctx:
            catalogue.set_selected("bn_BD-google-medium")
        self.assertIn("not installed", str(ctx.exception))

    def test_choosing_an_unknown_voice_is_refused(self):
        with self.assertRaises(catalogue.VoiceError):
            catalogue.set_selected("not-a-voice")

    def test_resolve_prefers_the_environment_over_the_saved_choice(self):
        catalogue.set_selected("te_IN-padmavathi-medium")
        with mock.patch.dict(os.environ, {"SILICA_VOICE": "en_GB-alba-medium"}):
            name, _path = catalogue.resolve()
        self.assertEqual(name, "en_GB-alba-medium")

    def test_resolve_prefers_an_explicit_name_over_everything(self):
        catalogue.set_selected("te_IN-padmavathi-medium")
        with mock.patch.dict(os.environ, {"SILICA_VOICE": "en_GB-alba-medium"}):
            name, _path = catalogue.resolve("te_IN-padmavathi-medium")
        self.assertEqual(name, "te_IN-padmavathi-medium")

    def test_resolve_falls_back_to_the_saved_choice(self):
        catalogue.set_selected("te_IN-padmavathi-medium")
        name, _path = catalogue.resolve()
        self.assertEqual(name, "te_IN-padmavathi-medium")


class SilicaSurfaceTests(unittest.TestCase):
    def run_source(self, source, capabilities=None):
        import io
        from silica.engine import compile_source, run_chunk
        out = io.StringIO()
        try:
            chunk = compile_source(source, "<test>").chunk
            run_chunk(chunk, "<test>", stdin=io.StringIO(), stdout=out,
                      stderr=io.StringIO(),
                      capabilities=capabilities or CapabilitySet.empty())
        except Exception as exc:  # noqa: BLE001
            return exc
        return out.getvalue()

    def test_download_and_delete_need_the_models_capability(self):
        for call in ('voice.download_model("en_GB-alba-medium")',
                     'voice.delete_model("en_GB-alba-medium")'):
            with self.subTest(call=call):
                error = self.run_source("use voice\nsfn main() {\n    %s\n}\n" % call)
                self.assertIn("speech.models", str(error))

    def test_reading_model_state_needs_no_capability(self):
        output = self.run_source(
            'use voice\nsfn main() {\n'
            '    sprint(str(len(voice.models())))\n'
            '    sprint(str(voice.storage()["megabytes"] > 0))\n'
            '    sprint(voice.current_voice())\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        self.assertEqual(len(output.split()), 3)

    def test_the_capability_is_listed_and_has_a_flag(self):
        from silica.capabilities import KNOWN, grant_flag
        self.assertIn(SPEECH_MODELS, KNOWN)
        self.assertEqual(grant_flag(SPEECH_MODELS), "--allow-speech-models")

    def test_a_grant_lets_a_download_through_the_capability_check(self):
        """The capability is the only thing being tested; the download is faked."""
        capabilities = CapabilitySet.empty().grant(SPEECH_MODELS, ".")
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(catalogue, "voices_dir", return_value=directory), \
                mock.patch.object(catalogue.urllib.request, "urlopen", FakeDownload()), \
                mock.patch("silica.voice.download_model") as fake:
            fake.return_value = {"name": "en_GB-alba-medium", "path": "x"}
            output = self.run_source(
                'use voice\nsfn main() {\n'
                '    let r = voice.download_model("en_GB-alba-medium")\n'
                '    sprint(r["name"])\n}\n', capabilities=capabilities)
        self.assertNotIsInstance(output, Exception, output)
        self.assertEqual(output.strip(), "en_GB-alba-medium")


if __name__ == "__main__":
    unittest.main()
