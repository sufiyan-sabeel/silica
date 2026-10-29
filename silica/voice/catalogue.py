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

import hashlib
import json
import os
import time
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


# --- licensing -------------------------------------------------------------
#
# Every voice is trained on a dataset whose licence governs redistribution and
# commercial use. Those licences differ sharply, and two of the voices this
# project previously offered are **non-commercial**. Nothing here is inferred:
# each entry was read from the voice's own MODEL_CARD in rhasspy/piper-voices.
#
# "unverified" means the model card points somewhere we could not confirm — a
# dead link, a Kaggle page, or a licence PDF. An unverified voice is still
# usable, but a caller cannot assume it is safe to ship commercially.
#
# name -> dict(id, url, commercial, attribution, share_alike, verified)
LICENCES = {
    "en_GB-alba-medium": {
        "id": "CC-BY-4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "commercial": True, "attribution": True, "share_alike": False,
        "verified": True,
    },
    "te_IN-padmavathi-medium": {
        "id": "CC-BY-4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "commercial": True, "attribution": True, "share_alike": False,
        "verified": True,
    },
    "bn_BD-google-medium": {
        "id": "CC-BY-SA-4.0",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "commercial": True, "attribution": True, "share_alike": True,
        "verified": True,
    },
    "mr_IN-google-medium": {
        "id": "CC-BY-SA-4.0",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "commercial": True, "attribution": True, "share_alike": True,
        "verified": True,
    },
    # NonCommercial: usable for personal and research work, not for products.
    "hi_IN-pratham-medium": {
        "id": "CC-BY-NC-SA-4.0",
        "url": "http://creativecommons.org/licenses/by-nc-sa/4.0/",
        "commercial": False, "attribution": True, "share_alike": True,
        "verified": True,
    },
    "hi_IN-priyamvada-medium": {
        "id": "CC-BY-NC-SA-4.0",
        "url": "http://creativecommons.org/licenses/by-nc-sa/4.0/",
        "commercial": False, "attribution": True, "share_alike": True,
        "verified": True,
    },
    # Pointed at a licence we could not read.
    "en_US-lessac-medium": {
        "id": "Blizzard2013",
        "url": "https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html",
        "commercial": None, "attribution": None, "share_alike": None,
        "verified": False,
    },
    "en_US-amy-medium": {
        "id": "See-model-card",
        "url": "https://github.com/MycroftAI/mimic3-voices",
        "commercial": None, "attribution": None, "share_alike": None,
        "verified": False,
    },
    "ml_IN-meera-medium": {
        "id": "See-model-card",
        "url": "https://www.kaggle.com/code/mpwolke/indictts-malayalam-speech-corpus",
        "commercial": None, "attribution": None, "share_alike": None,
        "verified": False,
    },
    "hi_IN-rohan-medium": {
        "id": "IITM-IndicTTS",
        "url": "https://www.iitm.ac.in/donlab/indictts/downloads/license.pdf",
        "commercial": None, "attribution": None, "share_alike": None,
        "verified": False,
    },
    "te_IN-maya-medium": {
        "id": "IITM-IndicTTS",
        "url": "https://www.iitm.ac.in/donlab/indictts/downloads/license.pdf",
        "commercial": None, "attribution": None, "share_alike": None,
        "verified": False,
    },
}

UNKNOWN_LICENCE = {
    "id": "unknown", "url": None, "commercial": None, "attribution": None,
    "share_alike": None, "verified": False,
}


def licence(name):
    """The licence recorded for a voice. Never None, so callers can rely on it."""
    return dict(LICENCES.get(name, UNKNOWN_LICENCE))


def licence_risk(name):
    """None when the licence is verified and commercial, else a short reason."""
    entry = licence(name)
    if not entry["verified"]:
        return "licence not verified"
    if entry["commercial"] is False:
        return "licence is non-commercial"
    return None


def commercially_safe():
    """Voices whose licence is verified and allows commercial use."""
    return sorted(n for n in VOICES if licence_risk(n) is None)


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


MANIFEST = "manifest.json"


def manifest_path():
    return os.path.join(voices_dir(), MANIFEST)


def _read_manifest():
    try:
        with open(manifest_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(data):
    target = manifest_path()
    partial = target + ".part"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(partial, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(partial, target)


def sha256_of(path):
    """Hash a file, streaming, so a 74 MB voice does not land in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest():
    """What was recorded when each voice was downloaded."""
    return _read_manifest()


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


def models():
    """Installed models with their licence, size and recorded checksum."""
    recorded = _read_manifest()
    rows = []
    for name in installed():
        code, label, quality, _path = VOICES[name]
        entry = licence(name)
        model = model_path(name)
        rows.append({
            "name": name,
            "language": code,
            "label": label,
            "quality": quality,
            "path": model,
            "bytes": os.path.getsize(model) if os.path.exists(model) else 0,
            "sha256": (recorded.get(name) or {}).get("sha256"),
            "downloaded_at": (recorded.get(name) or {}).get("downloaded_at"),
            "licence": entry["id"],
            "licence_verified": entry["verified"],
            "commercial_use": entry["commercial"],
        })
    return rows


def catalogue():
    """Every known voice, with whether it is installed here."""
    rows = []
    for name in sorted(VOICES):
        code, label, quality, _path = VOICES[name]
        entry = licence(name)
        rows.append({
            "name": name,
            "language": code,
            "label": label,
            "quality": quality,
            "installed": is_installed(name),
            "path": model_path(name) if is_installed(name) else None,
            "licence": entry["id"],
            "licence_url": entry["url"],
            "licence_verified": entry["verified"],
            "commercial_use": entry["commercial"],
            "attribution_required": entry["attribution"],
            "licence_risk": licence_risk(name),
        })
    return rows


def delete(name):
    """Remove an installed voice and its manifest entry. Returns bytes freed."""
    if name not in VOICES:
        raise VoiceError(
            "unknown voice %r. Known voices: %s" % (name, ", ".join(sorted(VOICES))))
    if not is_installed(name):
        raise VoiceError("voice %r is not installed, so there is nothing to delete"
                         % name)
    freed = 0
    for path in (model_path(name), model_path(name) + ".json"):
        if os.path.exists(path):
            freed += os.path.getsize(path)
            os.unlink(path)
    data = _read_manifest()
    if name in data:
        del data[name]
        _write_manifest(data)
    return freed


def verify(name):
    """Re-hash an installed voice and compare with what was recorded."""
    if not is_installed(name):
        return {"name": name, "installed": False, "verified": False,
                "reason": "not installed"}
    recorded = _read_manifest().get(name)
    actual = sha256_of(model_path(name))
    if not recorded:
        return {"name": name, "installed": True, "verified": False,
                "sha256": actual,
                "reason": "no checksum was recorded for this voice"}
    ok = recorded.get("sha256") == actual
    return {"name": name, "installed": True, "verified": ok,
            "sha256": actual, "recorded": recorded.get("sha256"),
            "reason": None if ok else "the file has changed since it was downloaded"}


def storage():
    """How much disk the voices take, so deleting one is an informed choice."""
    total = 0
    model_bytes = 0
    files = []
    directory = voices_dir()
    # bookkeeping files are ours, not the user's models; count them separately so
    # "how much would deleting this voice free" has a clean answer
    bookkeeping = {MANIFEST, SELECTION, MANIFEST + ".part"}
    if os.path.isdir(directory):
        for entry in sorted(os.listdir(directory)):
            path = os.path.join(directory, entry)
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            total += size
            if entry not in bookkeeping:
                model_bytes += size
            files.append({"name": entry, "bytes": size,
                          "bookkeeping": entry in bookkeeping})
    return {"directory": directory, "bytes": total, "model_bytes": model_bytes,
            "megabytes": round(total / (1024.0 * 1024.0), 1),
            "model_megabytes": round(model_bytes / (1024.0 * 1024.0), 1),
            "files": files, "voices": installed()}


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


SELECTION = "selection"


def selection_path():
    return os.path.join(voices_dir(), SELECTION)


def selected():
    """The voice chosen with set_voice, if any. Not validated here."""
    try:
        with open(selection_path(), encoding="utf-8") as handle:
            name = handle.read().strip()
        return name or None
    except OSError:
        return None


def set_selected(name):
    """Remember a voice for later runs. Pass None or "" to clear it."""
    target = selection_path()
    if not name:
        if os.path.exists(target):
            os.unlink(target)
        return None
    if name not in VOICES:
        raise VoiceError(
            "unknown voice %r. Known voices: %s" % (name, ", ".join(sorted(VOICES))))
    if not is_installed(name):
        raise VoiceError("voice %r is not installed. Install it with:\n"
                         "    silica voice install %s" % (name, name))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(name + "\n")
    return name


def resolve(name=None):
    """Turn a voice name into a path, preferring an installed voice."""
    name = (name or os.environ.get("SILICA_VOICE") or selected()
            or DEFAULT_VOICE)
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

    target = model_path(name)          # already ends in .onnx
    for suffix in (".onnx", ".onnx.json"):
        url = "%s/%s/%s%s" % (BASE_URL, path, name, suffix)
        # the model file *is* the target; appending the suffix produced
        # "<name>.onnx.onnx", which is_installed() never found
        destination = target if suffix == ".onnx" else target + ".json"
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

    # record what was downloaded, so corruption can be detected later
    data = _read_manifest()
    data[name] = {
        "sha256": sha256_of(target),
        "bytes": os.path.getsize(target),
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_manifest(data)
    return target
