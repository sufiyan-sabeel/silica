"""Speech to text with faster-whisper (Whisper running on CTranslate2).

Two details worth knowing, both found by running it rather than reading docs:

* `transcribe()` accepts a numpy array, and that is what is passed here. Handing
  it a file path routes through PyAV, whose `open()` signature varies by version
  and raises `TypeError: unexpected keyword argument 'metadata_errors'` on some
  installs. Decoding WAV ourselves sidesteps that entirely and removes a
  dependency from the audio path.
* Whisper wants exactly 16 kHz mono float32. Piper voices are 22.05 kHz, so the
  round trip between the two engines needs the resampler in `audio.py`.

Whisper is multilingual, which matters here: it understands Tamil and Kannada
even though no Piper voice exists for them, so listening covers more languages
than speaking does. The docs say so rather than implying symmetry.
"""

import os


# "tiny" is the default because "base" needs ~1 GB free and phones do not
# have it. Set SILICA_WHISPER_MODEL=base for better accuracy on a desktop.
DEFAULT_MODEL = "tiny"


class STTError(RuntimeError):
    pass


def _faster_whisper():
    try:
        import faster_whisper
    except ModuleNotFoundError:
        raise STTError(
            "faster-whisper is not installed, so audio cannot be transcribed. "
            "Install it with `pip install faster-whisper`.")
    return faster_whisper


_MODELS = {}


def load_model(size=None, model_dir=None):
    """Load and cache a Whisper model. `size` is tiny/base/small/medium/large-v3."""
    size = size or os.environ.get("SILICA_WHISPER_MODEL", DEFAULT_MODEL)
    key = (size, model_dir)
    if key in _MODELS:
        return _MODELS[key]
    faster_whisper = _faster_whisper()
    kwargs = {"device": "cpu", "compute_type": "int8", "cpu_threads": 1}
    if model_dir:
        kwargs["download_root"] = model_dir
    try:
        model = faster_whisper.WhisperModel(size, **kwargs)
    except Exception as exc:
        raise STTError(
            "cannot load the Whisper model %r: %s\n"
            "The first run downloads it (~75 MB for 'tiny', ~150 MB for 'base'); "
            "if there is no network, install a model directory first." % (size, exc))
    _MODELS[key] = model
    return model


def transcribe(path, size=None, language=None, model_dir=None):
    """Transcribe an audio file. Returns a dict with text, language and segments."""
    from . import audio  # imports numpy; only needed once we actually decode

    if not os.path.exists(path):
        raise STTError("no such audio file: %s" % path)
    samples = audio.load_for_whisper(path)
    if samples.size == 0:
        raise STTError("%s contains no audio" % path)

    model = load_model(size=size, model_dir=model_dir)
    try:
        segments, info = model.transcribe(
            samples, beam_size=1, language=language or None, vad_filter=False)
        pieces = list(segments)
    except Exception as exc:
        raise STTError("transcription failed: %s" % exc)

    text = " ".join(piece.text.strip() for piece in pieces).strip()
    return {
        "text": text,
        "language": getattr(info, "language", None),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "seconds": round(samples.size / 16000.0, 3),
        "segments": [{"start": round(s.start, 2), "end": round(s.end, 2),
                      "text": s.text.strip()} for s in pieces],
    }


def available():
    try:
        _faster_whisper()
    except STTError:
        return False
    return True


def describe():
    try:
        import faster_whisper
        version = getattr(faster_whisper, "__version__", "unknown")
    except ModuleNotFoundError:
        return {"available": False}
    try:
        import ctranslate2
        ct2 = ctranslate2.__version__
    except ModuleNotFoundError:  # pragma: no cover
        ct2 = None
    return {"available": True, "faster_whisper": version, "ctranslate2": ct2,
            "default_model": os.environ.get("SILICA_WHISPER_MODEL", DEFAULT_MODEL)}
