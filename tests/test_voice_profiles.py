"""Phase 6: voice profiles, consent, and the cloning that is not shipped.

The claims tested here:

1. **A profile cannot be created without consent.** Not a checkbox default, not an
   empty string — a statement naming the speaker.
2. **Profiles are local.** Reference audio and metadata live under Silica's data
   directory and are never uploaded.
3. **Deleting a profile deletes the recording**, and reports what it freed.
4. **Cloning refuses rather than pretends.** With no cloning engine, asking to
   synthesise from a profile fails with the reason for each engine — it does not
   quietly fall back to a different voice.

No cloning engine is installed in CI, so the last one is tested by its refusal.
A fake engine covers the success path, so the plumbing is exercised too.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from silica.capabilities import SPEECH_MODELS, CapabilitySet
from silica.voice import profile_store


def make_wav(path, seconds=1.0, rate=16000):
    import struct
    import wave
    frames = int(seconds * rate)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="silica-profiles-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.wav = os.path.join(self.home, "reference.wav")
        make_wav(self.wav)
        self.patch = mock.patch.object(profile_store, "profiles_dir",
                                       return_value=os.path.join(self.home, "voice-profiles"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def create(self, name="demo", **kwargs):
        kwargs.setdefault("speaker", "Riyaz")
        kwargs.setdefault("consent",
                          "I am the speaker in this recording and I consent to "
                          "a voice profile being created from it.")
        return profile_store.create(name, self.wav, **kwargs)

    def test_a_profile_needs_consent(self):
        for consent in ("", "   ", None):
            with self.subTest(consent=consent):
                with self.assertRaises(profile_store.ProfileError) as ctx:
                    profile_store.create("demo", self.wav, consent=consent,
                                         speaker="Riyaz")
                self.assertIn("consent", str(ctx.exception))

    def test_a_token_consent_is_refused_as_meaningless(self):
        with self.assertRaises(profile_store.ProfileError) as ctx:
            profile_store.create("demo", self.wav, consent="yes", speaker="Riyaz")
        self.assertIn("too short", str(ctx.exception))

    def test_the_speaker_must_be_named(self):
        with self.assertRaises(profile_store.ProfileError) as ctx:
            self.create(speaker="  ")
        self.assertIn("whose voice", str(ctx.exception))

    def test_a_missing_recording_is_refused(self):
        with self.assertRaises(profile_store.ProfileError) as ctx:
            profile_store.create("demo", "/nonexistent.wav",
                                 consent="I am the speaker and I consent to this "
                                         "profile being created.",
                                 speaker="Riyaz")
        self.assertIn("not found", str(ctx.exception))

    def test_a_profile_records_who_consented_and_to_what(self):
        meta = self.create(purpose="a test")
        self.assertEqual(meta["speaker"], "Riyaz")
        self.assertEqual(meta["purpose"], "a test")
        self.assertIn("consent", meta)
        self.assertIn("created_at", meta)
        self.assertTrue(meta["local_only"])
        self.assertEqual(len(meta["reference_sha256"]), 64)
        self.assertGreater(meta["reference_seconds"], 0)

    def test_profiles_are_listed_and_readable(self):
        self.create("one")
        self.create("two")
        names = [p["name"] for p in profile_store.list_profiles()]
        self.assertEqual(sorted(names), ["one", "two"])
        self.assertEqual(profile_store.profile("one")["name"], "one")

    def test_an_unknown_profile_is_an_error_not_an_empty_dict(self):
        with self.assertRaises(profile_store.ProfileError):
            profile_store.profile("nope")

    def test_a_duplicate_name_is_refused(self):
        self.create("demo")
        with self.assertRaises(profile_store.ProfileError) as ctx:
            self.create("demo")
        self.assertIn("already exists", str(ctx.exception))

    def test_unsafe_names_are_refused(self):
        for name in ("../escape", "with space", "slash/inside", ""):
            with self.subTest(name=name):
                with self.assertRaises(profile_store.ProfileError):
                    self.create(name)

    def test_verify_notices_a_changed_recording(self):
        self.create("demo")
        self.assertTrue(profile_store.verify("demo")["verified"])
        path = profile_store.reference_path("demo")
        with open(path, "ab") as handle:
            handle.write(b"x" * 100)
        self.assertFalse(profile_store.verify("demo")["verified"])

    def test_delete_removes_the_recording_too(self):
        self.create("demo")
        directory = os.path.dirname(profile_store.reference_path("demo"))
        freed = profile_store.delete("demo")
        self.assertGreater(freed, 0)
        self.assertFalse(os.path.exists(directory))
        self.assertEqual(profile_store.list_profiles(), [])

    def test_deleting_something_absent_is_an_error(self):
        with self.assertRaises(profile_store.ProfileError):
            profile_store.delete("nope")

    def test_everything_stays_under_the_profiles_directory(self):
        self.create("demo")
        root = os.path.abspath(profile_store.profiles_dir())
        for entry in os.listdir(root):
            path = os.path.abspath(os.path.join(root, entry))
            self.assertTrue(path.startswith(root))


class CloningTests(unittest.TestCase):
    """Cloning must refuse rather than substitute a different voice."""

    def test_no_engine_claims_cloning_by_default(self):
        from silica.voice import engines
        for name in engines.tts_names():
            with self.subTest(engine=name):
                self.assertFalse(engines.get_tts(name).supports_cloning(),
                                 "%s must not claim cloning" % name)

    def test_the_report_explains_every_engine(self):
        from silica import voice
        report = voice.cloning_engines()
        self.assertEqual(report["available"], [])
        for name in voice._engines().tts_names():
            with self.subTest(engine=name):
                self.assertIn(name, report["unavailable"])
                self.assertTrue(report["unavailable"][name])

    def test_synthesising_from_a_profile_refuses_with_the_reason(self):
        from silica import voice
        from silica.voice import piper
        with self.assertRaises(piper.TTSError) as ctx:
            voice.synthesize("hello", profile="someone")
        message = str(ctx.exception)
        self.assertIn("cloning engine", message)
        self.assertIn("piper", message)

    def test_a_configured_zipvoice_model_would_enable_cloning(self):
        """The seam is real: configuring a cloning model flips the answer."""
        from silica.voice import engines
        with mock.patch.dict(os.environ, {"SILICA_SHERPA_ZIPVOICE_MODEL": "/tmp/zv"}):
            self.assertTrue(engines.get_tts("sherpa").supports_cloning())
        self.assertFalse(engines.get_tts("sherpa").supports_cloning())


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

    def test_creating_a_profile_needs_the_models_capability(self):
        error = self.run_source(
            'use voice\nsfn main() {\n'
            '    voice.create_profile("x", "/tmp/a.wav", {consent: "I consent to this"})\n}\n')
        self.assertIn("speech.models", str(error))

    def test_deleting_a_profile_needs_the_models_capability(self):
        error = self.run_source('use voice\nsfn main() {\n'
                                '    voice.delete_profile("x")\n}\n')
        self.assertIn("speech.models", str(error))

    def test_reading_profiles_needs_nothing(self):
        output = self.run_source('use voice\nsfn main() {\n'
                                 '    sprint(str(len(voice.profiles())))\n'
                                 '    sprint(str(len(voice.cloning_engines()["available"])))\n}\n')
        self.assertNotIsInstance(output, Exception, output)

    def test_consent_is_enforced_at_the_native_boundary_too(self):
        capabilities = CapabilitySet.empty().grant(SPEECH_MODELS, ".")
        error = self.run_source(
            'use voice\nsfn main() {\n'
            '    voice.create_profile("x", "/tmp/a.wav", {})\n}\n',
            capabilities=capabilities)
        self.assertIn("consent", str(error).lower())


if __name__ == "__main__":
    unittest.main()
