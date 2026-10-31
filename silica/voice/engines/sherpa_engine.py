"""sherpa-onnx, behind the same interfaces. Optional, and opt-in.

Why this exists: Piper's and Whisper's wheels are glibc-only, so neither installs
on Termux. sherpa-onnx publishes Termux/Android builds, and covers both
directions — speech out and speech in — in one dependency.

Two things learned in the Phase 0 spike are encoded here rather than left for the
user to rediscover:

1. **sherpa-onnx >= 2.0.0 ignores `data_dir` for Piper-style VITS models.** It
   wants phoneme code points from an external phonemizer instead, and without
   them synthesis fails with "no lexicon, and no frontend available". This engine
   therefore refuses a Piper-style model on 2.x with that explanation, instead of
   failing deep inside the C++ layer.
2. **Nothing is downloaded here.** The model directories must already exist and
   are named by the caller through the environment. Silent downloads are exactly
   what the offline guarantee forbids.

Configuration:

    SILICA_SHERPA_TTS_MODEL=/path/to/vits-piper-...     (model.onnx, tokens.txt,
                                                         espeak-ng-data/)
    SILICA_SHERPA_ASR_MODEL=/path/to/whisper-...        (encoder, decoder, tokens)
    SILICA_SHERPA_THREADS=2
"""

import os

from . import EngineError, STTEngine, TTSEngine


def _sherpa():
    try:
        import sherpa_onnx
    except ModuleNotFoundError:
        raise EngineError(
            "sherpa-onnx is not installed. Install it with:\n"
            "    pip install sherpa-onnx")
    return sherpa_onnx


def _version(sherpa_onnx):
    return str(getattr(sherpa_onnx, "__version__", "") or "")


def _major(sherpa_onnx):
    text = _version(sherpa_onnx).split(".")
    try:
        return int(text[0])
    except (IndexError, ValueError):
        return 0


def _threads():
    try:
        return max(1, int(os.environ.get("SILICA_SHERPA_THREADS", "2")))
    except ValueError:
        return 2


def _numpy():
    try:
        import numpy
    except ModuleNotFoundError:
        raise EngineError(
            "numpy is required by the sherpa-onnx engine. Install it with:\n"
            "    pip install numpy")
    return numpy


class TTS(TTSEngine):
    name = "sherpa"

    def __init__(self):
        self._tts = None
        self._loaded_from = None

    # -- configuration -------------------------------------------------------
    def model_dir(self):
        return os.environ.get("SILICA_SHERPA_TTS_MODEL") or None

    def _files(self):
        directory = self.model_dir()
        if not directory or not os.path.isdir(directory):
            return None
        # Piper voice archives name the model after the voice
        # (`en_US-lessac-medium.onnx`), not `model.onnx`, so any .onnx in the
        # directory is a candidate — preferring the int8 build when both exist.
        candidates = [os.path.join(directory, n) for n in sorted(os.listdir(directory))
                      if n.endswith(".onnx")]
        if not candidates:
            return None
        int8 = [p for p in candidates if "int8" in os.path.basename(p)]
        model = (int8 or candidates)[0]
        tokens = os.path.join(directory, "tokens.txt")
        if not os.path.exists(tokens):
            return None
        return {
            "model": model,
            "tokens": tokens,
            "data_dir": os.path.join(directory, "espeak-ng-data"),
            "directory": directory,
        }

    def available(self):
        try:
            files = self._files()
        except Exception:  # noqa: BLE001
            return False
        if files is None:
            return False
        try:
            sherpa_onnx = _sherpa()
        except EngineError:
            return False
        if _major(sherpa_onnx) >= 2:
            return False
        return True

    def describe(self):
        detail = {"engine": self.name, "available": False}
        try:
            _sherpa()
        except EngineError as exc:
            detail["reason"] = str(exc)
            return detail
        sherpa_onnx = _sherpa()
        detail["version"] = _version(sherpa_onnx)
        files = self._files()
        if files is None:
            detail["reason"] = ("SILICA_SHERPA_TTS_MODEL is not set to a directory "
                                "containing model.onnx, tokens.txt and "
                                "espeak-ng-data")
            return detail
        detail["model"] = files["model"]
        if _major(sherpa_onnx) >= 2:
            detail["reason"] = (
                "sherpa-onnx %s ignores data_dir for Piper-style models and needs "
                "phoneme code points from an external phonemizer; pin "
                "sherpa-onnx<2 (1.13.x) to use this voice" % _version(sherpa_onnx))
            return detail
        detail["available"] = True
        return detail

    # -- synthesis -----------------------------------------------------------
    def _build(self):
        files = self._files()
        if files is None:
            raise EngineError("SILICA_SHERPA_TTS_MODEL is not configured")
        sherpa_onnx = _sherpa()
        if _major(sherpa_onnx) >= 2:
            raise EngineError(self.describe().get("reason") or "unsupported version")
        try:
            return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=files["model"],
                        tokens=files["tokens"],
                        data_dir=files["data_dir"]),
                    num_threads=_threads()),
                max_num_sentences=1))
        except Exception as exc:  # noqa: BLE001
            raise EngineError("cannot load the sherpa-onnx voice model: %s" % exc)

    def synthesize(self, text, voice=None, length_scale=None, noise_scale=None):
        np = _numpy()
        files = self._files()
        if files is None:
            raise EngineError("SILICA_SHERPA_TTS_MODEL is not configured")
        if self._tts is None or self._loaded_from != files["directory"]:
            self._tts = self._build()
            self._loaded_from = files["directory"]
        speed = 1.0 if length_scale is None else max(0.1, 1.0 / float(length_scale))
        try:
            audio = self._tts.generate(text, sid=0, speed=speed)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("sherpa-onnx failed to synthesise: %s" % exc)
        samples = np.asarray(audio.samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            raise EngineError("sherpa-onnx returned no audio for %r" % text[:40])
        return samples, int(audio.sample_rate)

    def supports_cloning(self):
        """ZipVoice models clone from a reference clip; VITS/Piper models do not."""
        return bool(os.environ.get("SILICA_SHERPA_ZIPVOICE_MODEL"))

    def close(self):
        self._tts = None
        self._loaded_from = None


class STT(STTEngine):
    name = "sherpa"

    def __init__(self):
        self._recognizer = None
        self._loaded_from = None

    def model_dir(self):
        return os.environ.get("SILICA_SHERPA_ASR_MODEL") or None

    def _files(self):
        directory = self.model_dir()
        if not directory or not os.path.isdir(directory):
            return None
        encoder = decoder = tokens = None
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            # tokens are not .onnx files, so this must come before the filter
            if name.endswith("-tokens.txt") or name == "tokens.txt":
                tokens = path
                continue
            if not name.endswith(".onnx"):
                continue
            if "encoder" in name and (encoder is None or "int8" in name):
                encoder = path
            elif "decoder" in name and (decoder is None or "int8" in name):
                decoder = path
        tokens = tokens or os.path.join(directory, "tokens.txt")
        if not (encoder and decoder and os.path.exists(tokens)):
            return None
        return {"encoder": encoder, "decoder": decoder, "tokens": tokens,
                "directory": directory}

    def available(self):
        if self._files() is None:
            return False
        try:
            _sherpa()
        except EngineError:
            return False
        return True

    def describe(self):
        detail = {"engine": self.name, "available": False}
        try:
            sherpa_onnx = _sherpa()
        except EngineError as exc:
            detail["reason"] = str(exc)
            return detail
        detail["version"] = _version(sherpa_onnx)
        files = self._files()
        if files is None:
            detail["reason"] = ("SILICA_SHERPA_ASR_MODEL is not set to a directory "
                                "containing encoder/decoder .onnx files and tokens")
            return detail
        detail["model"] = os.path.basename(files["encoder"])
        detail["available"] = True
        return detail

    def _build(self):
        files = self._files()
        if files is None:
            raise EngineError("SILICA_SHERPA_ASR_MODEL is not configured")
        sherpa_onnx = _sherpa()
        try:
            return sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=files["encoder"], decoder=files["decoder"],
                tokens=files["tokens"], num_threads=_threads(),
                language="en", task="transcribe")
        except Exception as exc:  # noqa: BLE001
            raise EngineError("cannot load the sherpa-onnx speech model: %s" % exc)

    def transcribe(self, path, language=None, model=None):
        np = _numpy()
        files = self._files()
        if files is None:
            raise EngineError("SILICA_SHERPA_ASR_MODEL is not configured")
        if not os.path.exists(path):
            raise EngineError("audio file not found: %s" % path)
        if self._recognizer is None or self._loaded_from != files["directory"]:
            self._recognizer = self._build()
            self._loaded_from = files["directory"]

        import wave
        try:
            with wave.open(path) as handle:
                rate = handle.getframerate()
                channels = handle.getnchannels()
                width = handle.getsampwidth()
                frames = handle.readframes(handle.getnframes())
        except Exception as exc:  # noqa: BLE001
            raise EngineError("cannot read %s: %s" % (path, exc))
        if width != 2:
            raise EngineError("sherpa-onnx needs 16-bit PCM WAV, got %d-bit" % (width * 8))
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)

        stream = self._recognizer.create_stream()
        stream.accept_waveform(rate, data)
        try:
            self._recognizer.decode_stream(stream)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("sherpa-onnx failed to transcribe: %s" % exc)
        text = stream.result.text.strip()
        return {
            "text": text,
            "language": language or "en",
            "engine": self.name,
            "seconds": round(len(data) / float(rate), 2),
        }

    def close(self):
        self._recognizer = None
        self._loaded_from = None
