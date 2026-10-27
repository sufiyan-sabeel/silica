"""Phonemisation through espeak-ng, loaded with ctypes.

Why not the `piper-tts` package? Because it ships glibc-only wheels and depends
on a compiled phonemiser, so it cannot be installed in Termux. Piper's voices are
plain ONNX files and espeak-ng is a small C library that Termux *does* package
(`pkg install espeak`), so the two pieces are loaded separately here and the same
code runs on a desktop Linux and on Android.

Library discovery, in order:

1. `espeakng_loader` — a pip package that bundles `libespeak-ng.so` and the
   language data. This is what makes the feature installable with pip alone.
2. A system `libespeak-ng.so` (Debian/Ubuntu: `libespeak-ng1`; Termux: `espeak`),
   with data under `/usr/lib/*/espeak-ng-data` or `$PREFIX/lib/espeak-ng-data`.
3. The `espeak-ng` command line binary, used as a subprocess. Slowest, but it is
   what a Termux install without the shared library would fall back to.

If none of the three is present, phonemisation is unavailable and TTS reports
that clearly instead of producing noise.
"""

import ctypes
import ctypes.util
import glob
import os
import shutil
import subprocess

# espeak_AUDIO_OUTPUT: 0 is playback, which blocks when there is no audio device.
# Synchronous output does not touch the sound card at all.
_AUDIO_OUTPUT_SYNCHRONOUS = 2
_CHARS_UTF8 = 0x01
_PHONEMES_IPA = 0x02

_DATA_DIR_CANDIDATES = (
    "/usr/lib/x86_64-linux-gnu/espeak-ng-data",
    "/usr/lib/aarch64-linux-gnu/espeak-ng-data",
    "/usr/lib/espeak-ng-data",
    "/usr/local/lib/espeak-ng-data",
)


class EspeakError(RuntimeError):
    pass


class EspeakPhonemizer:
    """Wraps one of the three espeak backends behind a single `phonemes()` call."""

    def __init__(self):
        self.backend = None
        self._lib = None
        self._cli = None
        self.detail = ""
        self._load()

    # -- discovery ------------------------------------------------------------
    def _load(self):
        if self._try_loader():
            return
        if self._try_system_library():
            return
        if self._try_cli():
            return
        raise EspeakError(
            "espeak-ng was not found, so text cannot be turned into phonemes",
            )

    def _try_loader(self):
        try:
            import espeakng_loader
        except ModuleNotFoundError:
            return False
        try:
            library = espeakng_loader.get_library_path()
            data = espeakng_loader.get_data_path()
        except Exception:  # pragma: no cover - broken install
            return False
        return self._initialise(library, data, "espeakng-loader")

    def _try_system_library(self):
        candidates = []
        found = ctypes.util.find_library("espeak-ng")
        if found:
            candidates.append(found)
        for pattern in ("/usr/lib/*/libespeak-ng.so*", "/usr/lib/libespeak-ng.so*",
                        "/usr/local/lib/libespeak-ng.so*",
                        "/data/data/com.termux/files/usr/lib/libespeak-ng.so*"):
            candidates.extend(sorted(glob.glob(pattern)))
        data = self._system_data_dir()
        for library in candidates:
            if data and self._initialise(library, data, "system libespeak-ng"):
                return True
        return False

    def _system_data_dir(self):
        for path in _DATA_DIR_CANDIDATES:
            if os.path.isdir(path):
                return path
        prefix = os.environ.get("PREFIX")
        if prefix:
            candidate = os.path.join(prefix, "lib", "espeak-ng-data")
            if os.path.isdir(candidate):
                return candidate
        return None

    def _try_cli(self):
        for name in ("espeak-ng", "espeak"):
            binary = shutil.which(name)
            if binary:
                self.backend = "cli"
                self._cli = binary
                self.detail = binary
                return True
        return False

    def _initialise(self, library, data_dir, label):
        try:
            lib = ctypes.CDLL(library)
            lib.espeak_Initialize.restype = ctypes.c_int
            lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int,
                                              ctypes.c_char_p, ctypes.c_int]
            lib.espeak_SetVoiceByName.restype = ctypes.c_int
            lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
            lib.espeak_TextToPhonemes.restype = ctypes.c_void_p
            lib.espeak_TextToPhonemes.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                                  ctypes.c_int, ctypes.c_int]
            rate = lib.espeak_Initialize(_AUDIO_OUTPUT_SYNCHRONOUS, 0,
                                         str(data_dir).encode("utf-8"), 0)
        except (OSError, AttributeError):
            return False
        if rate <= 0:
            return False
        self._lib = lib
        self.backend = "library"
        self.detail = "%s (%s)" % (library, label)
        return True

    # -- use ------------------------------------------------------------------
    def phonemes(self, text, voice="en-us"):
        """IPA phonemes for `text`, or "" when the text has none."""
        if not text or not text.strip():
            return ""
        if self.backend == "cli":
            return self._phonemes_cli(text, voice)
        return self._phonemes_library(text, voice)

    def _phonemes_library(self, text, voice):
        lib = self._lib
        lib.espeak_SetVoiceByName(str(voice).encode("utf-8"))
        buffer = ctypes.c_char_p(text.encode("utf-8"))
        pointer = ctypes.cast(buffer, ctypes.c_void_p)
        parts = []
        # espeak returns one clause per call and NULL when finished. The bound is
        # a guard against a malformed return value looping forever.
        for _ in range(500):
            result = lib.espeak_TextToPhonemes(ctypes.byref(pointer), _CHARS_UTF8,
                                               _PHONEMES_IPA)
            if not result:
                break
            parts.append(ctypes.string_at(result).decode("utf-8"))
        return "".join(parts)

    def _phonemes_cli(self, text, voice):
        try:
            completed = subprocess.run(
                [self._cli, "-q", "--ipa", "-v", str(voice), text],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            raise EspeakError("espeak-ng failed: %s" % exc)
        if completed.returncode != 0:
            raise EspeakError(
                "espeak-ng exited %d: %s"
                % (completed.returncode, completed.stderr.decode("utf-8", "replace")[:200]))
        return completed.stdout.decode("utf-8", "replace").strip()


_CACHE = {}


def phonemizer():
    """One shared phonemizer per process; loading the library is not free."""
    if "instance" not in _CACHE:
        _CACHE["instance"] = EspeakPhonemizer()
    return _CACHE["instance"]


def available():
    try:
        phonemizer()
        return True
    except EspeakError:
        return False


def describe():
    try:
        engine = phonemizer()
    except EspeakError as exc:
        return {"available": False, "reason": str(exc)}
    return {"available": True, "backend": engine.backend, "detail": engine.detail}
