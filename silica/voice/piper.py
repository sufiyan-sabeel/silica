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

import numpy as np

from . import espeak

# Piper's special tokens, as they appear in every voice config.
BOS, EOS, PAD = "^", "$", "_"


class TTSError(RuntimeError):
    pass


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
        phonemes = self.phonemes(text)
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

    # -- synthesis ------------------------------------------------------------
    def synthesize(self, text, length_scale=None, noise_scale=None):
        """Return (float32 samples in -1..1, sample rate)."""
        ids = self.ids(text)
        if not ids:
            raise TTSError("nothing to say: %r produced no phonemes" % text)
        length = float(length_scale if length_scale is not None else self.length_scale)
        noise = float(noise_scale if noise_scale is not None else self.noise_scale)
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
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        return samples, self.rate


_LOADED = {}


def load_voice(model_path, name=None):
    """Cache loaded voices: reading a 60 MB model per sentence would be silly."""
    key = (os.path.abspath(model_path), name)
    if key not in _LOADED:
        _LOADED[key] = PiperVoice(model_path, name=name)
    return _LOADED[key]


def available():
    """True when onnxruntime and espeak-ng are both usable."""
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
