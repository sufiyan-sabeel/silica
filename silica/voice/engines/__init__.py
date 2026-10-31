"""Speech engines behind one interface.

Silica started with exactly one engine per direction — Piper for speech, Whisper
for listening — and the voice layer called those modules directly. That was fine
while it was true. It stopped being true when sherpa-onnx turned out to run on
Termux, where neither Piper's nor Whisper's wheels install.

So the two directions each get an interface, and the engines implement it:

    TTSEngine.synthesize(text, ...) -> (samples, rate)
    STTEngine.transcribe(path, ...) -> {text, language, ...}

Nothing here decides *which* engine to use on vibes. Selection is explicit,
ordered, and can be overridden:

    SILICA_VOICE_TTS=piper|sherpa|auto      (default auto)
    SILICA_VOICE_STT=whisper|sherpa|auto    (default auto)

`auto` prefers the engine this project has shipped and tested — Piper and
Whisper — and only falls to sherpa-onnx when the default is genuinely
unavailable. That keeps existing behaviour identical while making the new engine
reachable.

Every engine must be able to say `available()` without raising, and `describe()`
must be honest about why it is not available.
"""

import os

# TTS selection order. The first available engine wins under "auto".
TTS_ORDER = ("piper", "sherpa")
# STT selection order.
STT_ORDER = ("whisper", "sherpa")


class EngineError(RuntimeError):
    """Raised by an engine that cannot do what was asked."""


class TTSEngine:
    """Speech out."""

    name = "none"
    kind = "tts"

    def available(self):
        """True when this engine could synthesise right now. Must not raise."""
        return False

    def describe(self):
        """A dict explaining availability, for `voice.status()` and errors."""
        return {"engine": self.name, "available": self.available()}

    def synthesize(self, text, voice=None, length_scale=None, noise_scale=None):
        """Return (float32 samples in -1..1, sample_rate)."""
        raise EngineError("%s cannot synthesise speech" % self.name)

    def voices(self):
        """Voice names this engine can use, or [] when it has no catalogue."""
        return []

    def supports_cloning(self):
        """True only if this engine can synthesise from a reference recording.

        A multi-speaker model taking a speaker *id* is not cloning, and must not
        report True.
        """
        return False

    def close(self):
        """Release anything held. Must be safe to call twice."""
        return None


class STTEngine:
    """Speech in."""

    name = "none"
    kind = "stt"

    def available(self):
        return False

    def describe(self):
        return {"engine": self.name, "available": self.available()}

    def transcribe(self, path, language=None, model=None):
        """Return {text, language, ...} for an audio file."""
        raise EngineError("%s cannot transcribe audio" % self.name)

    def close(self):
        return None


# --- built-in engines --------------------------------------------------------
#
# Imported lazily: importing sherpa-onnx costs seconds and a lot of memory, and
# most programs never touch speech at all.

_REGISTRY = {}


def _load(kind, name):
    key = (kind, name)
    if key in _REGISTRY:
        return _REGISTRY[key]
    module_name = {
        ("tts", "piper"): "piper_engine",
        ("tts", "sherpa"): "sherpa_engine",
        ("stt", "whisper"): "whisper_engine",
        ("stt", "sherpa"): "sherpa_engine",
    }.get(key)
    if module_name is None:
        raise EngineError("unknown %s engine %r" % (kind, name))
    import importlib
    module = importlib.import_module("." + module_name, __name__)
    engine = module.TTS() if kind == "tts" else module.STT()
    _REGISTRY[key] = engine
    return engine


def tts_names():
    return list(TTS_ORDER)


def stt_names():
    return list(STT_ORDER)


def get_tts(name):
    return _load("tts", name)


def get_stt(name):
    return _load("stt", name)


def _preferred(kind):
    variable = "SILICA_VOICE_TTS" if kind == "tts" else "SILICA_VOICE_STT"
    value = (os.environ.get(variable) or "auto").strip().lower()
    order = TTS_ORDER if kind == "tts" else STT_ORDER
    if value == "auto":
        return order
    if value not in order:
        raise EngineError(
            "%s=%r is not a known engine; choose one of %s or auto"
            % (variable, value, ", ".join(order)))
    return (value,) + tuple(n for n in order if n != value)


def select_tts(preferred=None):
    """The engine that should speak, or raise with every engine's reason."""
    order = (preferred,) if preferred else _preferred("tts")
    reasons = {}
    for name in order:
        try:
            engine = get_tts(name)
        except Exception as exc:  # noqa: BLE001 - a broken engine must not crash us
            reasons[name] = "failed to load: %s" % exc
            continue
        if engine.available():
            return engine
        reasons[name] = engine.describe().get("reason") or "unavailable"
    raise EngineError("no text-to-speech engine is available: %s"
                      % "; ".join("%s: %s" % (k, v) for k, v in reasons.items()))


def select_stt(preferred=None):
    """The engine that should listen, or raise with every engine's reason."""
    order = (preferred,) if preferred else _preferred("stt")
    reasons = {}
    for name in order:
        try:
            engine = get_stt(name)
        except Exception as exc:  # noqa: BLE001
            reasons[name] = "failed to load: %s" % exc
            continue
        if engine.available():
            return engine
        reasons[name] = engine.describe().get("reason") or "unavailable"
    raise EngineError("no speech-to-text engine is available: %s"
                      % "; ".join("%s: %s" % (k, v) for k, v in reasons.items()))


def report():
    """Every engine and its state, for `voice.status()`."""
    out = {"tts": {}, "stt": {}}
    for kind, order, getter in (("tts", TTS_ORDER, get_tts),
                                ("stt", STT_ORDER, get_stt)):
        for name in order:
            try:
                out[kind][name] = getter(name).describe()
            except Exception as exc:  # noqa: BLE001
                out[kind][name] = {"engine": name, "available": False,
                                   "reason": "failed to load: %s" % exc}
    return out


def reset():
    """Drop cached engines. Used by tests to isolate selection."""
    _REGISTRY.clear()
