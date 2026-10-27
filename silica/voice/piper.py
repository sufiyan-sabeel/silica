"""Piper text-to-speech, without the `piper-tts` package.

A Piper voice is two files: an ONNX model and a JSON config. Synthesis is three
steps — espeak-ng turns text into IPA phonemes, the config maps phonemes to ids,
and the ONNX model turns ids into audio. That is all `piper-tts` does, and doing
it here means the feature needs only `onnxruntime` (available in Termux as a
package) plus an espeak-ng library, instead of a glibc-only wheel.

The output was checked against `piper-tts` itself: both render the same sentence
to audio that transcribes identically, so this is the same model doing the same
thing, not an approximation.
"""

import json
import os
import re

try:
    import numpy as np
except ModuleNotFoundError:  # status and availability must still work
    np = None

from . import espeak

# Piper's special tokens, as they appear in every voice config.
BOS, EOS, PAD = "^", "$", "_"

# Silence inserted between clauses and between sentences, in milliseconds. Without
# this the whole utterance is one unbroken run of phonemes and sounds rushed —
# espeak marks clause boundaries with a newline and they were being discarded.
CLAUSE_PAUSE_MS = 60
SENTENCE_PAUSE_MS = 140

# Sentence ends for Latin and for the Indic danda / double danda.
_SENTENCE_END = re.compile(r"(?<=[.!?\u0964\u0965])\s+")


class TTSError(RuntimeError):
    pass


def _numpy():
    if np is None:
        raise TTSError(
            "numpy is not installed, so audio cannot be assembled. "
            "Install it with `pip install numpy`.")
    return np


def _onnxruntime():
    try:
        import onnxruntime
    except ModuleNotFoundError:
        raise TTSError(
            "onnxruntime is not installed, so no voice can be synthesised. "
            "Install it with `pip install onnxruntime`, or on Termux "
            "`pkg install onnxruntime`.")
    return onnxruntime


class PiperVoice:
    """One voice: model + config, loaded once and reused."""

    def __init__(self, model_path, name=None):
        self.model_path = model_path
        self.config_path = model_path + ".json"
        if not os.path.exists(model_path):
            raise TTSError("voice model not found: %s" % model_path)
        if not os.path.exists(self.config_path):
            raise TTSError("voice config not found: %s" % self.config_path)
        try:
            with open(self.config_path, encoding="utf-8") as handle:
                self.config = json.load(handle)
        except (OSError, ValueError) as exc:
            raise TTSError("cannot read %s: %s" % (self.config_path, exc))

        try:
            self.id_map = self.config["phoneme_id_map"]
            self.rate = int(self.config["audio"]["sample_rate"])
        except (KeyError, TypeError) as exc:
            raise TTSError("voice config is missing %s" % exc)

        inference = self.config.get("inference", {})
        self.noise_scale = float(inference.get("noise_scale", 0.667))
        self.length_scale = float(inference.get("length_scale", 1.0))
        self.noise_w = float(inference.get("noise_w", 0.8))
        self.espeak_voice = self.config.get("espeak", {}).get("voice", "en-us")
        self.name = name or os.path.basename(model_path).split(".")[0]

        ort = _onnxruntime()
        try:
            self.session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"])
        except Exception as exc:
            raise TTSError("cannot load %s: %s" % (model_path, exc))
        self.input_names = {i.name for i in self.session.get_inputs()}

    # -- ids ------------------------------------------------------------------
    def phonemes(self, text):
        return espeak.phonemizer().phonemes(text, self.espeak_voice)

    def ids(self, text):
        """Phonemes to model ids, with the pad token between each — as Piper does."""
        return self.ids_for_phonemes(self.phonemes(text))

    def ids_for_phonemes(self, phonemes):
        if not phonemes:
            return []
        ids = list(self.id_map.get(BOS, [1]))
        for phoneme in phonemes:
            if phoneme not in self.id_map:
                continue
            ids.extend(self.id_map[phoneme])
            ids.extend(self.id_map.get(PAD, [0]))
        ids.extend(self.id_map.get(EOS, [2]))
        ids.extend(self.id_map.get(PAD, [0]))
        return ids

    def clauses(self, text):
        """Split into sentences, then into espeak's clause breaks within each.

        espeak separates clauses with a newline; keeping those boundaries is what
        turns a rushed stream of phonemes into speech with pauses in it.
        """
        sentences = [s for s in _SENTENCE_END.split(text.strip()) if s.strip()]
        if not sentences:
            return []
        out = []
        for sentence in sentences:
            for clause in self.phonemes(sentence).split("\n"):
                clause = clause.strip()
                if clause:
                    out.append(clause)
        return out

    # -- synthesis ------------------------------------------------------------
    def _run(self, ids, length, noise):
        feeds = {
            "input": np.array([ids], dtype=np.int64),
            "input_lengths": np.array([len(ids)], dtype=np.int64),
            "scales": np.array([noise, length, self.noise_w], dtype=np.float32),
        }
        feeds = {k: v for k, v in feeds.items() if k in self.input_names}
        try:
            audio = self.session.run(None, feeds)[0]
        except Exception as exc:
            raise TTSError("the voice model failed: %s" % exc)
        return np.asarray(audio, dtype=np.float32).reshape(-1)

    def synthesize(self, text, length_scale=None, noise_scale=None,
                   pause_scale=1.0):
        """Return (float32 samples in -1..1, sample rate).

        Each clause is synthesised separately and joined with silence, so the
        result has the pauses a listener expects at commas and full stops.
        """
        np = _numpy()
        length = float(length_scale if length_scale is not None else self.length_scale)
        noise = float(noise_scale if noise_scale is not None else self.noise_scale)
        scale = max(0.0, float(pause_scale))

        pieces = self.clauses(text)
        if not pieces:
            raise TTSError("nothing to say: %r produced no phonemes" % text)

        audio_parts = []
        for index, clause in enumerate(pieces):
            ids = self.ids_for_phonemes(clause)
            if not ids:
                continue
            if audio_parts:
                gap = CLAUSE_PAUSE_MS
                # a longer pause where the clause ended a sentence
                if clause is pieces[-1] or index and pieces[index - 1].endswith(
                        (".", "!", "?", "\u0964", "\u0965")):
                    gap = SENTENCE_PAUSE_MS
                silence = np.zeros(int(self.rate * gap * scale / 1000.0),
                                   dtype=np.float32)
                audio_parts.append(silence)
            audio_parts.append(self._run(ids, length, noise))

        if not audio_parts:
            raise TTSError("nothing to say: %r produced no audio" % text)
        return np.concatenate(audio_parts), self.rate


_LOADED = {}


def load_voice(model_path, name=None):
    """Cache loaded voices: reading a 60 MB model per sentence would be silly."""
    key = (os.path.abspath(model_path), name)
    if key not in _LOADED:
        _LOADED[key] = PiperVoice(model_path, name=name)
    return _LOADED[key]


def available():
    """True when onnxruntime and espeak-ng are both usable."""
    if np is None:
        return False
    try:
        _onnxruntime()
    except TTSError:
        return False
    return espeak.available()


def describe():
    info = {"onnxruntime": False, "espeak": espeak.describe()}
    try:
        import onnxruntime
        info["onnxruntime"] = onnxruntime.__version__
    except ModuleNotFoundError:
        info["onnxruntime"] = False
    return info
