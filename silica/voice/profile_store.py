"""Voice profiles: consent records and reference recordings, kept locally.

What this is, and what it deliberately is not
---------------------------------------------
This module stores *who consented to what, when, and with which recording*. It
does not clone a voice, because no engine Silica can ship does that acceptably:

* **XTTS-v2** clones from a six-second clip and sounds good, but it is under the
  Coqui Public Model License, which permits **non-commercial use only** — and
  Coqui shut down in January 2024, so a commercial licence can no longer be
  bought from anyone. Shipping it as a general feature would put every user who
  sells their work in breach.
* **Piper's multi-speaker models** (`libritts_r`, `vctk`) take a speaker *id*.
  That is choosing a voice that was trained in, not cloning the person in front
  of the microphone. Presenting it as cloning would be a lie.
* **sherpa-onnx ZipVoice** is genuine zero-shot cloning, but the model is ~605 MB
  and covers Chinese and English only; its licence has not been verified here.

So the machinery is real and tested, and the engine is absent on purpose. When a
cloning engine is configured, `synthesize(profile=...)` will use it; until then
it refuses and says why.

Consent
-------
A profile cannot be created without an explicit consent statement naming the
speaker and the purpose. That record is stored beside the reference audio and is
never sent anywhere. Deleting the profile deletes both.

Impersonation is out of scope and out of bounds: Silica has no interest in
helping anyone imitate a person who has not agreed to it.
"""

import hashlib
import json
import os
import shutil
import time

PROFILE_VERSION = 1
PROFILE_FILE = "profile.json"
REFERENCE = "reference.wav"

# What a caller must be able to say truthfully before a profile is created.
CONSENT_PROMPT = (
    "I am the speaker in this recording, or I have their explicit permission to "
    "use it, and I consent to a voice profile being created from it for the "
    "purpose I have stated.")


class ProfileError(RuntimeError):
    pass


def profiles_dir():
    from . import catalogue
    return os.path.join(catalogue.home(), "voice-profiles")


def _profile_path(name):
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")
    if not safe or safe != name:
        raise ProfileError(
            "profile names may contain only letters, digits, '-' and '_': %r" % name)
    return os.path.join(profiles_dir(), safe)


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_profiles():
    """Every profile on this machine, newest first. Metadata only."""
    root = profiles_dir()
    if not os.path.isdir(root):
        return []
    rows = []
    for entry in sorted(os.listdir(root)):
        meta = _read(os.path.join(root, entry, PROFILE_FILE))
        if meta:
            rows.append(meta)
    rows.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return rows


def profile(name):
    """One profile's metadata, or a clear error."""
    meta = _read(os.path.join(_profile_path(name), PROFILE_FILE))
    if not meta:
        raise ProfileError("no voice profile named %r" % name)
    return meta


def create(name, reference, consent, speaker=None, purpose=None):
    """Create a profile from a reference recording. Consent is not optional.

    `consent` must be the speaker's own statement (see CONSENT_PROMPT). It is
    recorded with a timestamp, the speaker's name and the stated purpose, and
    stored only in the profile directory.
    """
    if not consent or not str(consent).strip():
        raise ProfileError(
            "a voice profile needs the speaker's consent. Pass a statement such "
            "as: %r" % CONSENT_PROMPT)
    if len(str(consent).strip()) < 20:
        raise ProfileError(
            "the consent statement is too short to mean anything. It should say "
            "who consented and to what.")
    if not speaker or not str(speaker).strip():
        raise ProfileError(
            "say whose voice this is: pass the speaker's name, so the consent "
            "record identifies a person")
    if not os.path.exists(reference):
        raise ProfileError("reference recording not found: %s" % reference)

    from . import audio
    try:
        info = audio.describe(reference)
    except Exception as exc:  # noqa: BLE001
        raise ProfileError("cannot read the reference recording: %s" % exc)
    if not info.get("seconds"):
        raise ProfileError("the reference recording is empty")

    directory = _profile_path(name)
    if os.path.exists(directory):
        raise ProfileError("a profile named %r already exists" % name)
    os.makedirs(directory, exist_ok=True)

    target = os.path.join(directory, REFERENCE)
    shutil.copyfile(reference, target)
    meta = {
        "version": PROFILE_VERSION,
        "name": name,
        "speaker": str(speaker).strip(),
        "purpose": (str(purpose).strip() if purpose else None),
        "consent": str(consent).strip(),
        "consent_prompt": CONSENT_PROMPT,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reference": REFERENCE,
        "reference_sha256": _sha256(target),
        "reference_bytes": os.path.getsize(target),
        "reference_seconds": info.get("seconds"),
        "local_only": True,
    }
    with open(os.path.join(directory, PROFILE_FILE), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=1, sort_keys=True)
    return meta


def delete(name):
    """Remove a profile and its reference recording. Returns bytes freed."""
    directory = _profile_path(name)
    if not os.path.isdir(directory):
        raise ProfileError("no voice profile named %r" % name)
    freed = 0
    for entry in os.listdir(directory):
        path = os.path.join(directory, entry)
        if os.path.isfile(path):
            freed += os.path.getsize(path)
    shutil.rmtree(directory)
    return freed


def reference_path(name):
    """Where a profile's recording lives, for an engine that can use it."""
    path = os.path.join(_profile_path(name), REFERENCE)
    if not os.path.exists(path):
        raise ProfileError("profile %r has no reference recording" % name)
    return path


def verify(name):
    """Has the reference recording changed since the profile was created?"""
    meta = profile(name)
    path = reference_path(name)
    actual = _sha256(path)
    return {"name": name, "verified": actual == meta.get("reference_sha256"),
            "sha256": actual, "recorded": meta.get("reference_sha256")}
