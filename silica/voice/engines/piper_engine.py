"""Piper, behind the TTSEngine interface.

This is a thin adapter: the work is done by `silica.voice.piper`, which is the
frontend Silica has shipped since 0.4.0. Keeping the adapter thin is the point —
the engine layer must not change how Piper behaves.
"""

from . import EngineError, TTSEngine


class TTS(TTSEngine):
    name = "piper"

    def __init__(self):
        self._piper = None

    def _module(self):
        if self._piper is None:
            from .. import piper
            self._piper = piper
        return self._piper

    def available(self):
        try:
            return bool(self._module().available())
        except Exception:  # noqa: BLE001 - availability must never raise
            return False

    def describe(self):
        try:
            detail = dict(self._module().describe())
        except Exception as exc:  # noqa: BLE001
            return {"engine": self.name, "available": False,
                    "reason": "cannot inspect piper: %s" % exc}
        detail["engine"] = self.name
        # espeak is reported as a nested dict, so truthiness of the dict is not
        # availability — the inner flag is.
        espeak = detail.get("espeak") or {}
        if isinstance(espeak, dict):
            espeak_ok = bool(espeak.get("available"))
        else:
            espeak_ok = bool(espeak)
        detail["available"] = bool(detail.get("onnxruntime")) and espeak_ok
        if not detail["available"]:
            detail["reason"] = ("needs onnxruntime=%r and espeak-ng available=%r"
                                % (detail.get("onnxruntime"), espeak_ok))
        return detail

    def synthesize(self, text, voice=None, length_scale=None, noise_scale=None):
        piper = self._module()
        catalogue = __import__("silica.voice.catalogue", fromlist=["x"])
        name = voice or catalogue.default_installed()
        if name is None:
            raise EngineError(
                "no voice is installed yet. Install one with:\n"
                "    silica voice install %s" % catalogue.DEFAULT_VOICE)
        # validate before loading: a model that changed on disk is not trusted
        catalogue.check_model(name)
        _name, path = catalogue.resolve(name)
        model = piper.load_voice(path, name=name)
        return model.synthesize(text, length_scale=length_scale,
                                noise_scale=noise_scale)

    def voices(self):
        from .. import catalogue
        return sorted(catalogue.VOICES)
