"""Speech for Silica: text to speech and speech to text, offline.

Both directions run locally. Nothing here uploads your text or your audio, and
neither engine needs an API key.

    from silica.voice import synthesize, transcribe

    synthesize("Hello from Silica", out="hello.wav")
    print(transcribe("hello.wav")["text"])

Engines
-------
* **Speaking** — Piper voices: an ONNX model driven by espeak-ng phonemes. It
  needs `onnxruntime` and an espeak-ng library, both of which Termux packages,
  and it deliberately does not depend on the `piper-tts` wheel (glibc only).
* **Listening** — Whisper through `faster-whisper` (CTranslate2). Needs
  `faster-whisper`, which pulls CTranslate2; Termux packages `ctranslate2` too.

Both are optional, and importing this package pulls in neither. Every heavy
import happens inside the function that needs it, so `import silica` — and a
program that never speaks — costs nothing and needs no numpy. The installer test
caught that the eager version made a plain `pip install` unusable on a machine
without numpy.

Quality, stated plainly
-----------------------
Piper is a neural model and sounds like a synthetic voice — clearly better than
formant synthesis, not as natural as a large cloud model. The English voice was
verified by round trip: synthesise, then transcribe with Whisper, and the text
comes back word for word. That is an intelligibility check, not a listening test.
"""

__all__ = [
    "synthesize", "speak", "transcribe", "available", "status", "voices",
    "languages", "install", "VoiceError", "TTSError", "STTError", "AudioError",
]


class VoiceError(RuntimeError):
    """Base class for the errors this package raises."""


def _catalogue():
    from . import catalogue
    return catalogue


def _piper():
    from . import piper
    return piper


def _whisper():
    from . import whisper
    return whisper


def _espeak():
    from . import espeak
    return espeak


def _audio():
    from . import audio
    return audio


def _engines():
    from . import engines
    return engines


def __getattr__(name):
    """Expose the submodules and their error types without importing them eagerly."""
    if name in ("audio", "catalogue", "espeak", "piper", "whisper",
                "platform_audio"):
        import importlib
        return importlib.import_module("." + name, __name__)
    aliases = {
        "AudioError": ("audio", "AudioError"),
        "TTSError": ("piper", "TTSError"),
        "STTError": ("whisper", "STTError"),
    }
    if name in aliases:
        module_name, attribute = aliases[name]
        import importlib
        module = importlib.import_module("." + module_name, __name__)
        return getattr(module, attribute)
    if name == "VoiceError":
        return _catalogue().VoiceError
    raise AttributeError(name)


def licence(name=None):
    """The licence recorded for a voice (the default voice when none is given).

    Always a dict, never None: `verified` says whether the terms were actually
    read, and `commercial` is False for non-commercial voices. Callers can
    therefore refuse a voice without having to know which ones are risky.
    """
    catalogue = _catalogue()
    return catalogue.licence(name or catalogue.DEFAULT_VOICE)


def platform():
    """What this machine can play and record with, and why when it cannot."""
    return _platform_audio().describe()


def record(seconds=5, path=None):
    """Record audio to a WAV file. Returns the path written.

    Recording is never automatic: something has to call this. The microphone is
    the user's, and a library that starts listening on its own is not one to
    trust.
    """
    import os as _os
    import tempfile as _tempfile
    platform_audio = _platform_audio()
    if path is None:
        handle = _tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        path = handle.name
    return platform_audio.record(seconds, path)


def listen(seconds=5, language=None, engine=None, model=None, path=None):
    """Record and transcribe in one step. Returns the transcription dict."""
    spoken = record(seconds=seconds, path=path)
    result = transcribe(spoken, model=model, language=language, engine=engine)
    result["audio"] = spoken
    return result


def _platform_audio():
    from . import platform_audio
    return platform_audio


def available():
    """Which half of the feature works here, according to the engine layer."""
    engines = _engines()
    result = {"tts": False, "stt": False}
    for kind, select in (("tts", engines.select_tts), ("stt", engines.select_stt)):
        try:
            select()
            result[kind] = True
        except engines.EngineError:
            result[kind] = False
    return result


def status():
    """Everything worth knowing before asking it to talk."""
    catalogue = _catalogue()
    return {
        "tts": _piper().describe(),
        "stt": _whisper().describe(),
        "espeak": _espeak().describe(),
        "engines": _engines().report(),
        "voices_installed": catalogue.installed(),
        "voices_dir": catalogue.voices_dir(),
        "default_voice": catalogue.default_installed() or catalogue.DEFAULT_VOICE,
    }


def voices():
    return _catalogue().catalogue()


def languages():
    return _catalogue().languages()


def install(name=None):
    """Download a voice into the cache. Returns its path."""
    catalogue = _catalogue()
    return catalogue.download(name or catalogue.DEFAULT_VOICE)


def synthesize(text, out=None, voice=None, length_scale=None, noise_scale=None,
               engine=None):
    """Render `text` to speech.

    With `out`, writes a WAV there and returns the path. Without it, returns
    (samples, rate) so the caller can play or process the audio.
    """
    piper = _piper()
    engines = _engines()
    if not isinstance(text, str):
        raise piper.TTSError("synthesize expects a String, got %s" % type(text).__name__)
    if not text.strip():
        raise piper.TTSError("nothing to say: the text is empty")

    try:
        chosen = engines.select_tts(preferred=engine)
    except engines.EngineError as exc:
        raise piper.TTSError("text to speech is unavailable: %s" % exc)

    try:
        samples, rate = chosen.synthesize(
            text, voice=voice, length_scale=length_scale, noise_scale=noise_scale)
    except engines.EngineError as exc:
        # the piper engine raises for a missing voice; keep that error type so
        # callers that catch VoiceError keep working
        catalogue = _catalogue()
        if "no voice is installed" in str(exc):
            raise catalogue.VoiceError(str(exc))
        raise piper.TTSError(str(exc))
    if out is None:
        return samples, rate
    _audio().write_wav(out, samples, rate)
    return out


def speak(text, out=None, voice=None, player=None):
    """Synthesize and, when a player exists, play it. Returns what happened."""
    audio = _audio()
    if out is None:
        samples, rate = synthesize(text, voice=voice)
        written = None
    else:
        written = synthesize(text, out=out, voice=voice)
        samples, rate = audio.read_wav(written)

    import os
    import subprocess
    import tempfile

    platform_audio = _platform_audio()

    # One place knows about audio players: platform_audio. This used to keep its
    # own copy of the list, which is how the two drift apart.
    if player is None:
        name, binary, extra = platform_audio.playback_tool()
        command = [binary] + list(extra) if binary else None
    else:
        name = player[0] if isinstance(player, (list, tuple)) else str(player)
        command = list(player) if isinstance(player, (list, tuple)) else [player]

    played = False
    detail = platform_audio.describe()["playback_reason"] or "no audio player found"
    if command:
        path = written
        temporary = None
        if path is None:
            handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            handle.close()
            temporary = handle.name
            audio.write_wav(temporary, samples, rate)
            path = temporary
        try:
            completed = subprocess.run(list(command) + [path],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, timeout=300)
            played = completed.returncode == 0
            detail = ("played with %s" % name if played
                      else "%s exited %d" % (name, completed.returncode))
        except (OSError, subprocess.SubprocessError) as exc:
            detail = "player failed: %s" % exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return {"wav": written, "played": played, "detail": detail,
            "seconds": round(len(samples) / float(rate), 3)}


def transcribe(path, model=None, language=None, engine=None):
    """Turn an audio file into text. Returns dict(text, language, segments…)."""
    import os

    whisper = _whisper()
    engines = _engines()
    try:
        chosen = engines.select_stt(preferred=engine)
    except engines.EngineError as exc:
        raise whisper.STTError("speech to text is unavailable: %s" % exc)
    try:
        return chosen.transcribe(path, language=language, model=model)
    except engines.EngineError as exc:
        raise whisper.STTError(str(exc))

