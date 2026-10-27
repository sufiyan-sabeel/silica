"""The voice catalogue: what exists, where it comes from, and where it is kept.

Voices are Piper's. They are plain files, downloaded on demand and cached under
the same home directory the installer uses (`$SILICA_HOME`, default
`~/.local/share/silica`), so `uninstall.sh` already knows about that directory
and nothing is written outside it.

The language table is the honest part. Piper has Hindi, Telugu, Bengali,
Malayalam and Marathi; it has **no** Tamil, Kannada, Gujarati or Punjabi voices.
Speech *recognition* covers those languages because Whisper is multilingual, so
the two directions are not symmetric. Anything that claims otherwise would be
the sort of thing this project keeps trying not to do.
"""

import os
import urllib.error
import urllib.request

BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# name -> (language code, human label, quality, path under the voice repository)
VOICES = {
    "en_US-lessac-medium": ("en_US", "English (US), lessac", "medium",
                            "en/en_US/lessac/medium"),
    "en_US-amy-medium": ("en_US", "English (US), amy", "medium",
                         "en/en_US/amy/medium"),
    "en_GB-alba-medium": ("en_GB", "English (GB), alba", "medium",
                          "en/en_GB/alba/medium"),
    "hi_IN-pratham-medium": ("hi_IN", "Hindi, pratham (male)", "medium",
                             "hi/hi_IN/pratham/medium"),
    "hi_IN-priyamvada-medium": ("hi_IN", "Hindi, priyamvada (female)", "medium",
                                "hi/hi_IN/priyamvada/medium"),
    "hi_IN-rohan-medium": ("hi_IN", "Hindi, rohan", "medium", "hi/hi_IN/rohan/medium"),
    "te_IN-maya-medium": ("te_IN", "Telugu, maya", "medium", "te/te_IN/maya/medium"),
    "te_IN-padmavathi-medium": ("te_IN", "Telugu, padmavathi", "medium",
                                "te/te_IN/padmavathi/medium"),
    "ml_IN-meera-medium": ("ml_IN", "Malayalam, meera", "medium",
                           "ml/ml_IN/meera/medium"),
    "bn_BD-google-medium": ("bn_BD", "Bengali, google", "medium",
                            "bn/bn_BD/google/medium"),
    "mr_IN-google-medium": ("mr_IN", "Marathi, google", "medium",
                            "mr/mr_IN/google/medium"),
}

DEFAULT_VOICE = "en_US-lessac-medium"

# Languages where Piper has no voice at all, and why it is worth saying so.
NO_VOICE = {
    "ta_IN": "Tamil",
    "kn_IN": "Kannada",
    "gu_IN": "Gujarati",
    "pa_IN": "Punjabi",
}

# Languages Whisper can transcribe. Not exhaustive — Whisper lists 99 — but the
# ones this project has reason to care about.
LISTENING_LANGUAGES = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "bn": "Bengali", "ml": "Malayalam", "mr": "Marathi", "kn": "Kannada",
    "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "ne": "Nepali",
}


class VoiceError(RuntimeError):
    pass


def home():
    """The Silica data directory, matching install.sh's convention."""
    explicit = os.environ.get("SILICA_HOME")
    if explicit:
        return explicit
    return os.path.join(os.path.expanduser("~"), ".local", "share", "silica")


def voices_dir():
    path = os.environ.get("SILICA_VOICES") or os.path.join(home(), "voices")
    return path


def model_path(name):
    return os.path.join(voices_dir(), name + ".onnx")


def is_installed(name):
    return (os.path.exists(model_path(name))
            and os.path.exists(model_path(name) + ".json"))


def installed():
    directory = voices_dir()
    if not os.path.isdir(directory):
        return []
    names = []
    for entry in sorted(os.listdir(directory)):
        if entry.endswith(".onnx"):
            name = entry[:-5]
            if is_installed(name):
                names.append(name)
    return names


def catalogue():
    """Every known voice, with whether it is installed here."""
    rows = []
    for name in sorted(VOICES):
        code, label, quality, _path = VOICES[name]
        rows.append({
            "name": name,
            "language": code,
            "label": label,
            "quality": quality,
            "installed": is_installed(name),
            "path": model_path(name) if is_installed(name) else None,
        })
    return rows


def languages():
    """Speaking coverage, and what is missing, stated as data rather than prose."""
    available = {}
    for name, (code, _label, _quality, _path) in VOICES.items():
        available.setdefault(code, []).append(name)
    return {
        "speaking": {code: sorted(names) for code, names in sorted(available.items())},
        "speaking_missing": dict(sorted(NO_VOICE.items())),
        "listening": dict(sorted(LISTENING_LANGUAGES.items())),
    }


def resolve(name=None):
    """Turn a voice name into a path, preferring an installed voice."""
    name = name or os.environ.get("SILICA_VOICE") or DEFAULT_VOICE
    if is_installed(name):
        return name, model_path(name)
    if name not in VOICES:
        raise VoiceError(
            "unknown voice %r. Known voices: %s"
            % (name, ", ".join(sorted(VOICES))))
    raise VoiceError(
        "voice %r is not installed. Install it with:\n"
        "    silica voice install %s" % (name, name))


def default_installed():
    """The voice to use when none was named: any installed one, else the default."""
    have = installed()
    if not have:
        return None
    for preferred in (DEFAULT_VOICE,):
        if preferred in have:
            return preferred
    return have[0]


def download(name, progress=None):
    """Fetch a voice into the cache. Returns the model path."""
    if name not in VOICES:
        raise VoiceError(
            "unknown voice %r. Known voices: %s" % (name, ", ".join(sorted(VOICES))))
    _code, _label, _quality, path = VOICES[name]
    directory = voices_dir()
    os.makedirs(directory, exist_ok=True)

    target = model_path(name)
    for suffix in (".onnx", ".onnx.json"):
        url = "%s/%s/%s%s" % (BASE_URL, path, name, suffix)
        destination = target + suffix if suffix == ".onnx" else target + ".json"
        partial = destination + ".part"
        if progress:
            progress("downloading %s" % os.path.basename(destination))
        try:
            with urllib.request.urlopen(url, timeout=120) as response, \
                    open(partial, "wb") as handle:
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    handle.write(chunk)
        except urllib.error.HTTPError as exc:
            if os.path.exists(partial):
                os.unlink(partial)
            raise VoiceError("cannot download %s: HTTP %s" % (url, exc.code))
        except (urllib.error.URLError, OSError) as exc:
            if os.path.exists(partial):
                os.unlink(partial)
            raise VoiceError("cannot download %s: %s" % (url, exc))
        os.replace(partial, destination)
        if os.path.getsize(destination) < 1024:
            raise VoiceError("downloaded %s looks truncated" % destination)
    return target
