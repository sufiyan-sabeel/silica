"""faster-whisper, behind the STTEngine interface.

A thin adapter over `silica.voice.whisper`, which is what Silica has shipped
since 0.4.0. Behaviour must not change.
"""

from . import EngineError, STTEngine


class STT(STTEngine):
    name = "whisper"

    def __init__(self):
        self._whisper = None

    def _module(self):
        if self._whisper is None:
            from .. import whisper
            self._whisper = whisper
        return self._whisper

    def available(self):
        try:
            return bool(self._module().available())
        except Exception:  # noqa: BLE001
            return False

    def describe(self):
        try:
            detail = dict(self._module().describe())
        except Exception as exc:  # noqa: BLE001
            return {"engine": self.name, "available": False,
                    "reason": "cannot inspect faster-whisper: %s" % exc}
        detail["engine"] = self.name
        detail["available"] = bool(detail.get("faster_whisper")) \
            and bool(detail.get("ctranslate2"))
        if not detail["available"]:
            detail["reason"] = ("needs faster-whisper=%r and ctranslate2=%r"
                                % (detail.get("faster_whisper"),
                                   detail.get("ctranslate2")))
        return detail

    def transcribe(self, path, language=None, model=None):
        return self._module().transcribe(path, size=model, language=language)
