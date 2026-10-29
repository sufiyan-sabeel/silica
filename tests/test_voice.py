"""Speech tests: the library, the Silica module, and the capability boundary.

Two tiers. Everything here runs without any engine installed — the catalogue, the
WAV plumbing, the capability checks and the honest "engine missing" errors. The
round-trip test needs `onnxruntime`, an espeak library, `faster-whisper` and a
downloaded voice, so it is skipped unless `SILICA_VOICE_TESTS=1`.

The round-trip is the only real check on whether the voice is intelligible:
synthesise a sentence, transcribe it, compare. It cannot tell you whether the
voice sounds *good* — that needs ears.
"""

import os
import shutil
import tempfile
import unittest

try:
    import numpy as np
    HAVE_NUMPY = True
except ModuleNotFoundError:  # pragma: no cover - CI installs it via .[dev]
    np = None
    HAVE_NUMPY = False

from silica.capabilities import (SPEECH_LISTEN, SPEECH_SPEAK, CapabilitySet,
                                 KNOWN)
from silica.errors import CapabilityError, SilicaRuntimeError
from silica.natives import MODULES
from silica.voice import catalogue  # pure Python: no numpy needed

if HAVE_NUMPY:
    from silica.voice import audio, espeak, piper, whisper
else:  # the engine modules need numpy; the catalogue does not
    audio = espeak = piper = whisper = None

RUN_ENGINE_TESTS = os.environ.get("SILICA_VOICE_TESTS") == "1"


def _restore(name, previous):
    """Put an environment variable back the way we found it.

    Deleting it outright would break any later test that depends on the caller's
    value — which is exactly what happened before this helper existed.
    """
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def engines_ready():
    return piper.available() and whisper.available() and bool(catalogue.installed())


class CatalogueTests(unittest.TestCase):
    def test_every_voice_has_a_language_and_a_path(self):
        for name, entry in catalogue.VOICES.items():
            with self.subTest(voice=name):
                self.assertEqual(len(entry), 4)
                code, label, quality, path = entry
                self.assertTrue(code and label and quality and path)
                self.assertIn("/", path)

    def test_voice_names_are_unique_and_prefixed_by_language(self):
        for name, (code, _label, _quality, _path) in catalogue.VOICES.items():
            with self.subTest(voice=name):
                self.assertTrue(name.startswith(code))

    def test_the_default_voice_exists_in_the_catalogue(self):
        self.assertIn(catalogue.DEFAULT_VOICE, catalogue.VOICES)

    def test_languages_without_a_voice_are_really_absent(self):
        """The 'no voice' list must not lie: those codes must have no entries."""
        for code in catalogue.NO_VOICE:
            with self.subTest(language=code):
                self.assertFalse(
                    [n for n, v in catalogue.VOICES.items() if v[0] == code],
                    "%s is listed as having no voice but one is present" % code)

    def test_language_table_separates_speaking_and_listening(self):
        table = catalogue.languages()
        self.assertIn("hi_IN", table["speaking"])
        self.assertIn("ta_IN", table["speaking_missing"])
        # Whisper hears Tamil even though Piper cannot speak it
        self.assertIn("ta", table["listening"])
        self.assertNotIn("ta_IN", table["speaking"])

    def test_installed_voices_are_discovered(self):
        previous = os.environ.get("SILICA_VOICES")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["SILICA_VOICES"] = directory
            try:
                self.assertEqual(catalogue.installed(), [])
                open(os.path.join(directory, "x.onnx"), "w").close()
                self.assertEqual(catalogue.installed(), [],
                                 "a model without a config must not count")
                open(os.path.join(directory, "x.onnx.json"), "w").close()
                self.assertEqual(catalogue.installed(), ["x"])
            finally:
                _restore("SILICA_VOICES", previous)

    def test_unknown_voice_is_named_in_the_error(self):
        with self.assertRaises(catalogue.VoiceError) as ctx:
            catalogue.resolve("klingon-1")
        self.assertIn("unknown voice", str(ctx.exception))
        self.assertIn("en_US-lessac-medium", str(ctx.exception))

    def test_an_uninstalled_voice_says_how_to_install_it(self):
        previous = os.environ.get("SILICA_VOICES")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["SILICA_VOICES"] = directory
            try:
                with self.assertRaises(catalogue.VoiceError) as ctx:
                    catalogue.resolve("hi_IN-pratham-medium")
                self.assertIn("silica voice install", str(ctx.exception))
            finally:
                _restore("SILICA_VOICES", previous)


@unittest.skipUnless(HAVE_NUMPY, "numpy is needed for the audio tests")
class AudioTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="silica-audio-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def tone(self, seconds=0.5, rate=22050, freq=220.0):
        t = np.arange(int(seconds * rate), dtype=np.float32) / rate
        return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)

    def test_write_then_read_round_trips(self):
        path = os.path.join(self.dir, "tone.wav")
        samples = self.tone()
        audio.write_wav(path, samples, 22050)
        back, rate = audio.read_wav(path)
        self.assertEqual(rate, 22050)
        self.assertEqual(back.size, samples.size)
        self.assertLess(float(np.abs(back - samples).max()), 1e-3)

    def test_clipping_is_bounded(self):
        path = os.path.join(self.dir, "loud.wav")
        audio.write_wav(path, np.array([2.0, -2.0, 0.0], dtype=np.float32), 16000)
        back, _ = audio.read_wav(path)
        self.assertLessEqual(float(np.abs(back).max()), 1.0)

    def test_resample_to_16k(self):
        samples = self.tone(seconds=1.0, rate=22050)
        out = audio.resample(samples, 22050)
        self.assertAlmostEqual(out.size, 16000, delta=2)

    def test_resample_is_a_no_op_at_16k(self):
        samples = self.tone(seconds=0.1, rate=16000)
        out = audio.resample(samples, 16000)
        self.assertEqual(out.size, samples.size)

    def test_describe_reports_silence(self):
        path = os.path.join(self.dir, "silence.wav")
        audio.write_wav(path, np.zeros(8000, dtype=np.float32), 16000)
        info = audio.describe(path)
        self.assertTrue(info["silent"])
        self.assertAlmostEqual(info["seconds"], 0.5, places=3)

    def test_describe_reports_sound(self):
        path = os.path.join(self.dir, "sound.wav")
        audio.write_wav(path, self.tone(), 22050)
        info = audio.describe(path)
        self.assertFalse(info["silent"])
        self.assertGreater(info["rms"], 0.1)

    def test_missing_file_is_a_clear_error(self):
        with self.assertRaises(audio.AudioError) as ctx:
            audio.read_wav(os.path.join(self.dir, "nope.wav"))
        self.assertIn("no such audio file", str(ctx.exception))

    def test_a_non_wav_is_a_clear_error(self):
        path = os.path.join(self.dir, "text.wav")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not audio")
        with self.assertRaises(audio.AudioError) as ctx:
            audio.read_wav(path)
        self.assertIn("not a PCM WAV", str(ctx.exception))


class CapabilityTests(unittest.TestCase):
    def test_speech_capabilities_are_known(self):
        self.assertIn(SPEECH_SPEAK, KNOWN)
        self.assertIn(SPEECH_LISTEN, KNOWN)

    def test_the_registry_guards_the_right_functions(self):
        speech = MODULES["speech"]
        self.assertEqual(speech["speak"].requires, SPEECH_SPEAK)
        self.assertEqual(speech["save"].requires, SPEECH_SPEAK)
        self.assertEqual(speech["save"].path_arg, 1)
        self.assertEqual(speech["transcribe"].requires, SPEECH_LISTEN)
        self.assertEqual(speech["transcribe"].path_arg, 0)

    def test_read_only_queries_need_no_capability(self):
        for name in ("voices", "languages", "status"):
            with self.subTest(native=name):
                self.assertIsNone(MODULES["speech"][name].requires)

    def test_a_save_without_the_capability_is_refused(self):
        from silica.engine import compile_source, run_chunk
        import io
        source = ('use speech\nsfn main() {\n'
                  '    speech.save("hello", "/tmp/never.wav")\n}\n')
        chunk = compile_source(source, "<test>").chunk
        with self.assertRaises(CapabilityError) as ctx:
            run_chunk(chunk, "<test>", stdin=io.StringIO(""),
                      stdout=io.StringIO(), stderr=io.StringIO(),
                      capabilities=CapabilitySet.empty())
        self.assertIn("speech.speak", str(ctx.exception))

    def test_a_transcribe_without_the_capability_is_refused(self):
        from silica.engine import compile_source, run_chunk
        import io
        source = ('use speech\nsfn main() {\n'
                  '    sprint(speech.transcribe("/tmp/never.wav"))\n}\n')
        chunk = compile_source(source, "<test>").chunk
        with self.assertRaises(CapabilityError) as ctx:
            run_chunk(chunk, "<test>", stdin=io.StringIO(""),
                      stdout=io.StringIO(), stderr=io.StringIO(),
                      capabilities=CapabilitySet.empty())
        self.assertIn("speech.listen", str(ctx.exception))

    def test_a_save_path_outside_the_grant_is_refused(self):
        from silica.engine import compile_source, run_chunk
        import io
        with tempfile.TemporaryDirectory() as allowed:
            caps = CapabilitySet.empty().grant(SPEECH_SPEAK, allowed)
            source = ('use speech\nsfn main() {\n'
                      '    speech.save("hello", "/etc/never.wav")\n}\n')
            chunk = compile_source(source, "<test>").chunk
            with self.assertRaises(CapabilityError):
                run_chunk(chunk, "<test>", stdin=io.StringIO(""),
                          stdout=io.StringIO(), stderr=io.StringIO(),
                          capabilities=caps)

    def test_queries_work_with_no_capabilities_at_all(self):
        from silica.engine import compile_source, run_chunk
        import io
        source = ('use speech\nsfn main() {\n'
                  '    sprint(type_of(speech.status()))\n'
                  '    sprint(len(speech.voices()) > 0)\n}\n')
        chunk = compile_source(source, "<test>").chunk
        out = io.StringIO()
        run_chunk(chunk, "<test>", stdin=io.StringIO(), stdout=out,
                  stderr=io.StringIO(), capabilities=CapabilitySet.empty())
        self.assertEqual(out.getvalue(), "Map\noui\n")


@unittest.skipUnless(HAVE_NUMPY, "numpy is needed to reach the engines")
class InstallPathTests(unittest.TestCase):
    """`voice install` must write the filename that `is_installed` looks for."""

    def test_the_model_lands_at_the_path_is_installed_checks(self):
        from silica.voice import catalogue
        expected = catalogue.model_path("en_GB-alba-medium")
        self.assertTrue(expected.endswith("en_GB-alba-medium.onnx"),
                        "model_path must end in .onnx exactly once: %s" % expected)
        self.assertNotIn(".onnx.onnx", expected)

    def test_download_writes_exactly_two_files(self):
        """A download produces <name>.onnx and <name>.onnx.json, nothing else."""
        import tempfile
        from unittest import mock
        from silica.voice import catalogue

        with tempfile.TemporaryDirectory() as directory:
            written = []

            class FakeResponse:
                def __init__(self, payload):
                    self.payload = payload
                def read(self, size=-1):
                    data, self.payload = self.payload, b""
                    return data
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False

            def fake_urlopen(url, timeout=None):
                written.append(url)
                # the downloader rejects anything under 1 KB as truncated
                return FakeResponse(b"x" * 2048)

            with mock.patch.object(catalogue, "voices_dir", return_value=directory), \
                    mock.patch.object(catalogue.urllib.request, "urlopen", fake_urlopen):
                catalogue.download("en_GB-alba-medium")
            files = sorted(os.listdir(directory))
        self.assertEqual(files, ["en_GB-alba-medium.onnx",
                                 "en_GB-alba-medium.onnx.json"])


class HonestErrorTests(unittest.TestCase):
    """When an engine is missing, say which one and how to install it."""

    def test_tts_reports_the_missing_piece(self):
        if piper.available():
            self.skipTest("a TTS engine is installed here")
        from silica import voice
        with self.assertRaises(Exception) as ctx:
            voice.synthesize("hello")
        message = str(ctx.exception)
        self.assertTrue("onnxruntime" in message or "espeak" in message, message)

    @unittest.skipUnless(HAVE_NUMPY, "numpy is needed to write a test WAV")
    def test_stt_reports_the_missing_piece(self):
        if whisper.available():
            self.skipTest("faster-whisper is installed here")
        from silica import voice
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "x.wav")
            audio.write_wav(path, np.zeros(1600, dtype=np.float32), 16000)
            with self.assertRaises(Exception) as ctx:
                voice.transcribe(path)
            self.assertIn("faster-whisper", str(ctx.exception))

    def test_empty_text_is_refused_before_any_engine_runs(self):
        from silica import voice
        with self.assertRaises(Exception) as ctx:
            voice.synthesize("   ")
        self.assertIn("empty", str(ctx.exception))

    def test_status_always_reports_something(self):
        from silica import voice
        info = voice.status()
        for key in ("tts", "stt", "espeak", "voices_dir", "default_voice"):
            self.assertIn(key, info)

    def test_importing_the_package_needs_no_engine(self):
        """A program that never speaks must not pay for onnxruntime."""
        import subprocess
        import sys
        code = ("import sys; import silica.voice; "
                "print('onnxruntime' in sys.modules, 'faster_whisper' in sys.modules)")
        result = subprocess.run([sys.executable, "-c", code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False False",
                         "importing silica.voice must not import the engines")


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io
        from silica import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_voice_list_shows_the_catalogue(self):
        code, out, _ = self.run_cli(["voice", "list"])
        self.assertEqual(code, 0)
        self.assertIn("en_US-lessac-medium", out)
        self.assertIn("hi_IN-pratham-medium", out)

    def test_voice_languages_states_the_gaps(self):
        code, out, _ = self.run_cli(["voice", "languages"])
        self.assertEqual(code, 0)
        self.assertIn("hi_IN", out)
        self.assertIn("Tamil", out)
        self.assertIn("no voice available", out)

    def test_voice_status_is_informative(self):
        code, out, _ = self.run_cli(["voice", "status"])
        self.assertEqual(code, 0)
        self.assertIn("speaking", out)
        self.assertIn("listening", out)

    def test_voice_help(self):
        code, out, _ = self.run_cli(["voice"])
        self.assertEqual(code, 0)
        self.assertIn("silica voice install", out)

    def test_unknown_subcommand(self):
        code, _out, err = self.run_cli(["voice", "yodel"])
        self.assertEqual(code, 2)
        self.assertIn("unknown voice subcommand", err)

    def test_speak_without_text_is_a_usage_error(self):
        code, _out, err = self.run_cli(["voice", "speak"])
        self.assertEqual(code, 2)
        self.assertIn("usage: silica voice speak", err)

    def test_transcribe_missing_file(self):
        code, _out, err = self.run_cli(["voice", "transcribe", "/nope/x.wav"])
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)


@unittest.skipUnless(RUN_ENGINE_TESTS, "set SILICA_VOICE_TESTS=1 with engines installed")
class EngineRoundTripTests(unittest.TestCase):
    """The only objective check on intelligibility: say it, hear it back."""

    @classmethod
    def setUpClass(cls):
        if not engines_ready():
            raise unittest.SkipTest(
                "needs onnxruntime, espeak-ng, faster-whisper and an installed voice")

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="silica-voice-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_english_round_trip(self):
        from silica import voice
        sentence = "Silica can speak and listen now."
        path = os.path.join(self.dir, "en.wav")
        voice.synthesize(sentence, out=path)

        info = audio.describe(path)
        self.assertFalse(info["silent"], "synthesis produced silence")
        self.assertGreater(info["seconds"], 0.5)

        heard = voice.transcribe(path)
        self.assertEqual(heard["language"], "en")
        self.assertEqual(heard["text"].strip().rstrip("."), sentence.rstrip("."))

    def test_hindi_synthesises(self):
        from silica import voice
        hindi = [v for v in catalogue.installed() if v.startswith("hi_IN")]
        if not hindi:
            self.skipTest("no Hindi voice installed")
        path = os.path.join(self.dir, "hi.wav")
        voice.synthesize("नमस्ते, मैं सिलिका हूँ।", out=path, voice=hindi[0])
        info = audio.describe(path)
        self.assertFalse(info["silent"])
        self.assertGreater(info["seconds"], 0.5)


if __name__ == "__main__":
    unittest.main()
