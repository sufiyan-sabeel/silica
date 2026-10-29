"""Phase 3: platform audio — playback and recording, on real detection.

There is no Android device here, so nothing in this file proves Termux works.
What it does prove is the part that can be proven anywhere: that the module finds
the right tool when one exists, builds the right command, converts what needs
converting, and says something useful when nothing is installed.

The Termux path is exercised with a stand-in binary that behaves like
`termux-microphone-record` (writes a compressed file), so the conversion branch
is covered rather than assumed.
"""

import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from silica.capabilities import SPEECH_LISTEN, CapabilitySet
from silica.voice import platform_audio as pa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A WAV header + a little silence, so files look real to anything that reads them.
WAV_BYTES = (b"RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
             b"\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x08"
             b"\x00\x00" + b"\x00" * 2048)


class FakeBinaries:
    """A PATH directory of stand-in executables."""

    def __init__(self, names, payload=WAV_BYTES, touch_last_arg=True):
        self.directory = tempfile.mkdtemp(prefix="silica-fakebin-")
        for name in names:
            path = os.path.join(self.directory, name)
            body = "#!/bin/sh\n"
            if touch_last_arg:
                body += 'for a in "$@"; do last="$a"; done\n'
                body += 'cat > "$last" <<\'EOF\'\n'
                body += payload.decode("latin-1") + "\nEOF\n"
            body += "exit 0\n"
            with open(path, "w") as handle:
                handle.write(body)
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP
                     | stat.S_IXOTH)
        self._original = os.environ.get("PATH", "")

    def __enter__(self):
        os.environ["PATH"] = self.directory + os.pathsep + self._original
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self._original
        shutil.rmtree(self.directory, ignore_errors=True)
        return False


class TermuxDetectionTests(unittest.TestCase):
    def test_termux_version_is_enough(self):
        with mock.patch.dict(os.environ, {"TERMUX_VERSION": "0.118"}, clear=False):
            self.assertTrue(pa.is_termux())

    def test_a_termux_prefix_is_enough(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.dict(os.environ,
                                {"PREFIX": "/data/data/com.termux/files/usr"}):
            self.assertTrue(pa.is_termux())

    def test_plain_linux_is_not_termux(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(pa.os.path, "isdir", return_value=False):
            self.assertFalse(pa.is_termux())


class DetectionTests(unittest.TestCase):
    def test_termux_player_wins_when_present(self):
        with FakeBinaries(["termux-media-player", "paplay", "aplay"]):
            name, path, _extra = pa.playback_tool()
        self.assertEqual(name, "termux-media-player")

    def test_aplay_is_found_when_it_is_the_only_player(self):
        with FakeBinaries(["aplay"]):
            name, _path, extra = pa.playback_tool()
        self.assertEqual(name, "aplay")
        self.assertEqual(extra, ("-q",))

    def test_no_player_is_reported_rather_than_guessed(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            name, path, _extra = pa.playback_tool()
            detail = pa.describe()
        self.assertIsNone(name)
        self.assertIsNone(path)
        self.assertIn("no audio player", detail["playback_reason"])

    def test_the_termux_recorder_is_preferred_when_arecord_is_absent(self):
        with FakeBinaries(["termux-microphone-record"]):
            name, _path, _builder, produces_wav = pa.recorder_tool()
        self.assertEqual(name, "termux-microphone-record")
        self.assertFalse(produces_wav, "Termux records compressed, not WAV")

    def test_arecord_is_preferred_when_available(self):
        with FakeBinaries(["arecord", "termux-microphone-record"]):
            name, _path, _builder, produces_wav = pa.recorder_tool()
        self.assertEqual(name, "arecord")
        self.assertTrue(produces_wav)


class RecordTests(unittest.TestCase):
    def test_arecord_writes_a_wav_directly(self):
        with FakeBinaries(["arecord"]) as bins, tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "out.wav")
            written = pa.record(1, target)
            self.assertEqual(written, target)
            self.assertTrue(os.path.exists(target))

    def test_a_compressed_recording_is_converted_and_the_temporary_removed(self):
        """This is the Termux path: capture m4a, convert to WAV with ffmpeg."""
        with FakeBinaries(["termux-microphone-record", "ffmpeg"]), \
                tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "out.wav")
            written = pa.record(1, target)
            # assert while the directory still exists
            self.assertEqual(written, target)
            self.assertTrue(os.path.exists(written))
            leftovers = [n for n in os.listdir(tmp) if n != "out.wav"]
            self.assertEqual(leftovers, [], "the capture file should be cleaned up")

    def test_without_ffmpeg_the_termux_path_explains_itself(self):
        with FakeBinaries(["termux-microphone-record"]), \
                tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ,
                                {"PATH": os.environ.get("PATH", "")}):
            # ffmpeg is genuinely absent from the fake PATH
            with self.assertRaises(pa.PlatformAudioError) as ctx:
                pa.record(1, os.path.join(tmp, "out.wav"))
        self.assertIn("ffmpeg", str(ctx.exception))

    def test_no_recorder_says_how_to_get_one(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            with self.assertRaises(pa.PlatformAudioError) as ctx:
                pa.record(1, "/tmp/x.wav")
        self.assertIn("Termux:API", str(ctx.exception))

    def test_nonsense_durations_are_refused(self):
        for value in (0, -1, 10_000, "soon"):
            with self.subTest(seconds=value):
                with self.assertRaises(pa.PlatformAudioError):
                    pa.record(value, "/tmp/x.wav")

    def test_a_failing_recorder_is_reported_not_ignored(self):
        directory = tempfile.mkdtemp(prefix="silica-failbin-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "arecord")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\necho 'device busy' >&2\nexit 1\n")
        os.chmod(path, 0o755)
        with mock.patch.dict(os.environ,
                             {"PATH": directory + os.pathsep + "/usr/bin:/bin"}):
            with self.assertRaises(pa.PlatformAudioError) as ctx:
                pa.record(1, "/tmp/x.wav")
        self.assertIn("device busy", str(ctx.exception))


class PlayTests(unittest.TestCase):
    def test_play_uses_the_detected_tool(self):
        with FakeBinaries(["paplay"]), tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "x.wav")
            open(target, "wb").write(WAV_BYTES)
            used = pa.play(target)
        self.assertEqual(used, "paplay")

    def test_play_refuses_a_missing_file(self):
        with self.assertRaises(pa.PlatformAudioError) as ctx:
            pa.play("/nonexistent/x.wav")
        self.assertIn("not found", str(ctx.exception))

    def test_play_without_a_player_explains_itself(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            target = os.path.join(tmp, "x.wav")
            open(target, "wb").write(WAV_BYTES)
            with self.assertRaises(pa.PlatformAudioError) as ctx:
                pa.play(target)
        self.assertIn("no audio player", str(ctx.exception))


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

    def test_record_needs_the_listen_capability(self):
        for module in ("voice", "speech"):
            with self.subTest(module=module):
                error = self.run_source('use %s\nsfn main() {\n'
                                        '    %s.record(1, "/tmp/x.wav")\n}\n'
                                        % (module, module))
                self.assertIn("speech.listen", str(error))

    def test_listen_needs_the_listen_capability(self):
        error = self.run_source('use voice\nsfn main() {\n    voice.listen(1)\n}\n')
        self.assertIn("speech.listen", str(error))

    def test_platform_is_available_without_a_capability(self):
        output = self.run_source('use voice\nsfn main() {\n'
                                 '    sprint(str(voice.platform()["termux"]))\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        self.assertIn(output.strip(), ("oui", "nein"))

    def test_listen_records_then_transcribes(self):
        """Both halves are exercised, with the platform and engine stubbed."""
        from silica import voice
        recorded = {}

        def fake_record(seconds=5, path=None):
            recorded["seconds"] = seconds
            recorded["path"] = path or "/tmp/fake.wav"
            return recorded["path"]

        def fake_transcribe(path, model=None, language=None, engine=None):
            recorded["transcribed"] = path
            return {"text": "hello", "language": language or "en"}

        with mock.patch.object(voice, "record", fake_record), \
                mock.patch.object(voice, "transcribe", fake_transcribe):
            result = voice.listen(2, language="en")
        self.assertEqual(recorded["seconds"], 2)
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["audio"], recorded["path"])


if __name__ == "__main__":
    unittest.main()
