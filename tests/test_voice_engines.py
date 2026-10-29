"""Phase 2: the speech engine layer.

What is being tested is *selection*, not audio quality: which engine gets picked,
what happens when none can run, and that the voice layer's behaviour and error
types did not change when the indirection was introduced.

The engines themselves are covered by `tests/test_voice.py` (real models, opt-in
via `SILICA_VOICE_TESTS=1`). The sherpa adapter was additionally run against real
Piper and Whisper-tiny models during development; that is recorded in the
changelog, and it is not something these unit tests can reproduce without models.
"""

import os
import unittest
from unittest import mock

from silica.voice import engines


class FakeEngine:
    """An engine whose availability and output the test controls."""

    def __init__(self, name, available=True, reason=None, kind="tts"):
        self.name = name
        self.kind = kind
        self._available = available
        self._reason = reason
        self.calls = []

    def available(self):
        return self._available

    def describe(self):
        detail = {"engine": self.name, "available": self._available}
        if not self._available and self._reason:
            detail["reason"] = self._reason
        return detail

    def synthesize(self, text, voice=None, length_scale=None, noise_scale=None):
        self.calls.append(("synthesize", text, voice))
        return [0.0, 0.1], 22050

    def transcribe(self, path, language=None, model=None):
        self.calls.append(("transcribe", path, language))
        return {"text": "fake", "language": language or "en", "engine": self.name}

    def close(self):
        return None


def patched(mapping):
    """Replace engine loading with the given {name: engine} map."""
    def loader(kind, name):
        engine = mapping.get(name)
        if engine is None:
            raise engines.EngineError("unknown %s engine %r" % (kind, name))
        return engine
    return mock.patch.object(engines, "_load", loader)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        engines.reset()

    def test_the_orders_are_documented_and_stable(self):
        self.assertEqual(engines.tts_names(), ["piper", "sherpa"])
        self.assertEqual(engines.stt_names(), ["whisper", "sherpa"])

    def test_every_named_engine_can_be_loaded(self):
        for name in engines.tts_names():
            with self.subTest(engine=name):
                engine = engines.get_tts(name)
                self.assertEqual(engine.name, name)
                self.assertIsInstance(engine.describe(), dict)
        for name in engines.stt_names():
            with self.subTest(engine=name):
                engine = engines.get_stt(name)
                self.assertEqual(engine.name, name)

    def test_an_unknown_engine_is_refused(self):
        with self.assertRaises(engines.EngineError):
            engines.get_tts("nonsense")

    def test_report_covers_every_engine_without_raising(self):
        report = engines.report()
        self.assertEqual(sorted(report), ["stt", "tts"])
        self.assertEqual(sorted(report["tts"]), sorted(engines.tts_names()))
        self.assertEqual(sorted(report["stt"]), sorted(engines.stt_names()))
        for kind in ("tts", "stt"):
            for name, detail in report[kind].items():
                with self.subTest(engine=name):
                    self.assertIn("available", detail)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        engines.reset()

    def test_auto_prefers_the_shipped_engine(self):
        piper = FakeEngine("piper")
        sherpa = FakeEngine("sherpa")
        with patched({"piper": piper, "sherpa": sherpa}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            self.assertIs(engines.select_tts(), piper)

    def test_auto_falls_through_to_the_next_available_engine(self):
        piper = FakeEngine("piper", available=False, reason="no onnxruntime")
        sherpa = FakeEngine("sherpa")
        with patched({"piper": piper, "sherpa": sherpa}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            self.assertIs(engines.select_tts(), sherpa)

    def test_an_explicit_engine_wins_even_when_auto_would_differ(self):
        piper = FakeEngine("piper")
        sherpa = FakeEngine("sherpa")
        with patched({"piper": piper, "sherpa": sherpa}):
            self.assertIs(engines.select_tts(preferred="sherpa"), sherpa)

    def test_the_environment_can_force_an_engine(self):
        piper = FakeEngine("piper")
        sherpa = FakeEngine("sherpa")
        with patched({"piper": piper, "sherpa": sherpa}), \
                mock.patch.dict(os.environ, {"SILICA_VOICE_TTS": "sherpa"}):
            self.assertIs(engines.select_tts(), sherpa)

    def test_an_unknown_environment_value_is_refused_with_the_options(self):
        with mock.patch.dict(os.environ, {"SILICA_VOICE_TTS": "nonsense"}):
            with self.assertRaises(engines.EngineError) as ctx:
                engines.select_tts()
        message = str(ctx.exception)
        self.assertIn("nonsense", message)
        self.assertIn("piper", message)
        self.assertIn("auto", message)

    def test_stt_selection_is_independent_of_tts(self):
        whisper = FakeEngine("whisper", kind="stt")
        sherpa_stt = FakeEngine("sherpa", kind="stt")
        with patched({"whisper": whisper, "sherpa": sherpa_stt}), \
                mock.patch.dict(os.environ, {"SILICA_VOICE_STT": "sherpa"}):
            self.assertIs(engines.select_stt(), sherpa_stt)

    def test_when_nothing_is_available_the_error_names_every_reason(self):
        piper = FakeEngine("piper", available=False, reason="needs onnxruntime")
        sherpa = FakeEngine("sherpa", available=False, reason="not installed")
        with patched({"piper": piper, "sherpa": sherpa}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            with self.assertRaises(engines.EngineError) as ctx:
                engines.select_tts()
        message = str(ctx.exception)
        self.assertIn("needs onnxruntime", message)
        self.assertIn("not installed", message)

    def test_an_engine_that_fails_to_load_does_not_crash_selection(self):
        good = FakeEngine("sherpa")
        with patched({"piper": None, "sherpa": good}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            self.assertIs(engines.select_tts(), good)


class VoiceLayerTests(unittest.TestCase):
    """The indirection must not change what callers see."""

    def setUp(self):
        engines.reset()

    def test_synthesize_uses_the_selected_engine(self):
        from silica import voice
        engine = FakeEngine("piper")
        with patched({"piper": engine, "sherpa": FakeEngine("sherpa")}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            samples, rate = voice.synthesize("hello there")
        self.assertEqual(engine.calls, [("synthesize", "hello there", None)])
        self.assertEqual(rate, 22050)
        self.assertEqual(len(samples), 2)

    def test_transcribe_uses_the_selected_engine(self):
        from silica import voice
        engine = FakeEngine("whisper", kind="stt")
        with patched({"whisper": engine, "sherpa": FakeEngine("sherpa", kind="stt")}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_STT", None)
            result = voice.transcribe("/tmp/does-not-need-to-exist.wav")
        self.assertEqual(result["text"], "fake")
        self.assertEqual(engine.calls[0][0], "transcribe")

    def test_empty_text_is_still_refused_before_any_engine_runs(self):
        from silica import voice
        engine = FakeEngine("piper")
        with patched({"piper": engine}):
            with self.assertRaises(Exception) as ctx:
                voice.synthesize("   ")
        self.assertIn("empty", str(ctx.exception))
        self.assertEqual(engine.calls, [], "no engine should have been asked")

    def test_a_missing_engine_still_raises_the_old_error_type(self):
        from silica import voice
        from silica.voice import piper
        piper_engine = FakeEngine("piper", available=False, reason="needs onnxruntime")
        sherpa = FakeEngine("sherpa", available=False, reason="not installed")
        with patched({"piper": piper_engine, "sherpa": sherpa}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            with self.assertRaises(piper.TTSError) as ctx:
                voice.synthesize("hello")
        self.assertIn("onnxruntime", str(ctx.exception))

    def test_a_missing_stt_engine_still_raises_the_old_error_type(self):
        from silica import voice
        from silica.voice import whisper
        stt = FakeEngine("whisper", available=False, reason="needs faster-whisper")
        sherpa = FakeEngine("sherpa", available=False, reason="not installed")
        with patched({"whisper": stt, "sherpa": sherpa}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_STT", None)
            with self.assertRaises(whisper.STTError) as ctx:
                voice.transcribe("/tmp/x.wav")
        self.assertIn("faster-whisper", str(ctx.exception))

    def test_available_reflects_the_engine_layer(self):
        from silica import voice
        with patched({"piper": FakeEngine("piper"),
                      "sherpa": FakeEngine("sherpa", available=False),
                      "whisper": FakeEngine("whisper", kind="stt"),
                      }), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_VOICE_TTS", None)
            os.environ.pop("SILICA_VOICE_STT", None)
            result = voice.available()
        self.assertEqual(result, {"tts": True, "stt": True})

    def test_status_reports_the_engines(self):
        from silica import voice
        status = voice.status()
        self.assertIn("engines", status)
        self.assertIn("tts", status["engines"])
        self.assertIn("piper", status["engines"]["tts"])


class SherpaConfigurationTests(unittest.TestCase):
    """The adapter must explain its own requirements rather than fail obscurely."""

    def setUp(self):
        engines.reset()

    def test_without_the_module_it_says_to_install_it(self):
        with mock.patch("silica.voice.engines.sherpa_engine._sherpa",
                        side_effect=engines.EngineError("sherpa-onnx is not installed")):
            detail = engines.get_tts("sherpa").describe()
        self.assertFalse(detail["available"])
        self.assertIn("not installed", detail.get("reason", ""))

    def test_with_the_module_but_no_model_it_names_the_variable(self):
        fake = mock.MagicMock()
        fake.__version__ = "1.13.8"
        with mock.patch("silica.voice.engines.sherpa_engine._sherpa", return_value=fake), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_SHERPA_TTS_MODEL", None)
            detail = engines.get_tts("sherpa").describe()
        self.assertFalse(detail["available"])
        self.assertIn("SILICA_SHERPA_TTS_MODEL", detail.get("reason", ""))

    def test_a_configured_directory_without_a_model_is_not_available(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"SILICA_SHERPA_TTS_MODEL": directory}):
                detail = engines.get_tts("sherpa").describe()
        self.assertFalse(detail["available"])

    def test_asr_without_configuration_explains_itself(self):
        fake = mock.MagicMock()
        fake.__version__ = "1.13.8"
        with mock.patch("silica.voice.engines.sherpa_engine._sherpa", return_value=fake), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SILICA_SHERPA_ASR_MODEL", None)
            detail = engines.get_stt("sherpa").describe()
        self.assertFalse(detail["available"])
        self.assertIn("SILICA_SHERPA_ASR_MODEL", detail.get("reason", ""))

    def test_a_piper_model_on_sherpa_two_is_refused_with_the_reason(self):
        """The Phase 0 finding: 2.x ignores data_dir and needs a phonemizer."""
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            open(os.path.join(directory, "voice.onnx"), "w").close()
            open(os.path.join(directory, "tokens.txt"), "w").close()
            os.makedirs(os.path.join(directory, "espeak-ng-data"), exist_ok=True)
            engine = engines.get_tts("sherpa")
            fake = mock.MagicMock()
            fake.__version__ = "2.0.1"
            with mock.patch.dict(os.environ, {"SILICA_SHERPA_TTS_MODEL": directory}), \
                    mock.patch("silica.voice.engines.sherpa_engine._sherpa",
                               return_value=fake):
                detail = engine.describe()
        self.assertFalse(detail["available"])
        self.assertIn("phoneme", detail.get("reason", "").lower())


if __name__ == "__main__":
    unittest.main()
