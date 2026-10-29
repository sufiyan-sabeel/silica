"""Playing and recording audio on whatever machine this is.

Playback and microphone capture are the parts of speech that belong to the
operating system, not to Silica. This module is the only place that knows which
program does either, and it decides by *looking*, never by assuming:

* Termux is detected from `TERMUX_VERSION`, `$PREFIX`, or the Termux data
  directory — not from the fact that `platform.system()` says Linux.
* A recorder is only reported when its binary is actually on `PATH`.

Nothing here downloads anything, and nothing records without being asked.

A note on Termux and microphones: `termux-microphone-record` writes M4A/3GP, not
WAV, and every speech model Silica can drive wants 16-bit PCM WAV. So recording
on Termux is a two-step job — capture, then convert with ffmpeg — and if ffmpeg is
missing this module says so instead of handing back a file nothing can read.
"""

import os
import shutil
import subprocess

# Playback tools, in preference order. The first one found wins.
PLAYBACK = (
    ("termux-media-player", ("play",)),      # Termux:API
    ("paplay", ()),                          # PulseAudio
    ("aplay", ("-q",)),                      # ALSA
    ("afplay", ()),                          # macOS
    ("play", ("-q",)),                       # sox
)

# Recorders, in preference order: (binary, argv builder, produces_wav)
RECORDERS = (
    ("arecord", lambda path, seconds: ["arecord", "-q", "-f", "S16_LE",
                                       "-r", "16000", "-c", "1",
                                       "-d", str(seconds), path], True),
    ("rec", lambda path, seconds: ["rec", "-q", "-r", "16000", "-c", "1",
                                   "-b", "16", path, "trim", "0",
                                   str(seconds)], True),
    ("termux-microphone-record",
     lambda path, seconds: ["termux-microphone-record", "-d", str(seconds),
                            "-f", path], False),
    ("ffmpeg", lambda path, seconds: ["ffmpeg", "-y", "-f", "alsa",
                                      "-i", "default", "-t", str(seconds),
                                      "-ar", "16000", "-ac", "1", path], True),
)


def is_termux():
    """True only when this really looks like Termux, not merely Linux."""
    if os.environ.get("TERMUX_VERSION"):
        return True
    prefix = os.environ.get("PREFIX") or ""
    if "com.termux" in prefix:
        return True
    return os.path.isdir("/data/data/com.termux/files/usr")


def _find(candidates):
    for name, extra in candidates:
        binary = shutil.which(name)
        if binary:
            return name, binary, extra
    return None, None, None


def playback_tool():
    """(name, path, extra args) for the first working player, or (None, ...)."""
    return _find(PLAYBACK)


def recorder_tool():
    """(name, path, builder, produces_wav) for the first working recorder."""
    for name, builder, produces_wav in RECORDERS:
        binary = shutil.which(name)
        if binary:
            return name, binary, builder, produces_wav
    return None, None, None, None


def describe():
    """What this machine can actually do, for `voice.status()` and errors."""
    player, player_path, _extra = playback_tool()
    recorder, recorder_path, _builder, produces_wav = recorder_tool()
    converter = shutil.which("ffmpeg")
    info = {
        "termux": is_termux(),
        "playback": player,
        "playback_path": player_path,
        "recording": recorder,
        "recording_path": recorder_path,
        "recording_is_wav": bool(recorder and produces_wav),
        "converter": converter,
    }
    if recorder and not produces_wav and not converter:
        info["recording_reason"] = (
            "%s records in a compressed format and ffmpeg is not installed to "
            "convert it to WAV" % recorder)
    elif not recorder:
        info["recording_reason"] = (
            "no recorder found: install Termux:API (termux-microphone-record) "
            "or alsa-utils (arecord)")
    else:
        info["recording_reason"] = None
    if not player:
        info["playback_reason"] = (
            "no audio player found: install Termux:API (termux-media-player), "
            "pulseaudio-utils (paplay) or alsa-utils (aplay)")
    else:
        info["playback_reason"] = None
    return info


class PlatformAudioError(RuntimeError):
    pass


def play(path):
    """Play a file. Returns the tool used. Raises when there is no player."""
    if not os.path.exists(path):
        raise PlatformAudioError("audio file not found: %s" % path)
    name, binary, extra = playback_tool()
    if binary is None:
        raise PlatformAudioError(describe()["playback_reason"])
    command = [binary] + list(extra) + [path]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PlatformAudioError("cannot run %s: %s" % (name, exc))
    if completed.returncode != 0:
        raise PlatformAudioError(
            "%s failed (exit %d): %s" % (name, completed.returncode,
                                         (completed.stderr or "").strip()[:200]))
    return name


def _to_wav(source, target):
    """Convert whatever the recorder produced into 16-bit PCM WAV."""
    converter = shutil.which("ffmpeg")
    if converter is None:
        raise PlatformAudioError(
            "the recorder produced %s and ffmpeg is not installed to convert it "
            "to WAV" % os.path.basename(source))
    command = [converter, "-y", "-loglevel", "error", "-i", source,
               "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", target]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0 or not os.path.exists(target):
        raise PlatformAudioError("ffmpeg could not convert %s: %s"
                                 % (source, (completed.stderr or "").strip()[:200]))
    return target


def record(seconds, path):
    """Record `seconds` of audio to `path` as 16-bit PCM WAV.

    Returns the path actually written, which may differ from `path` when the
    recorder produced a compressed file that had to be converted.
    """
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise PlatformAudioError("seconds must be a number")
    if seconds <= 0:
        raise PlatformAudioError("seconds must be greater than zero")
    if seconds > 600:
        raise PlatformAudioError("refusing to record more than 10 minutes")

    name, binary, builder, produces_wav = recorder_tool()
    if binary is None:
        raise PlatformAudioError(describe()["recording_reason"])

    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    if produces_wav:
        target = path
        temporary = None
    else:
        # record next to the target, then convert over it
        base, _ext = os.path.splitext(path)
        temporary = base + ".capture" + (".m4a" if "termux" in name else ".tmp")
        target = temporary

    command = builder(target, seconds)
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=int(seconds) + 120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PlatformAudioError("cannot run %s: %s" % (name, exc))
    if completed.returncode != 0 or not os.path.exists(target):
        raise PlatformAudioError(
            "%s failed (exit %d): %s"
            % (name, completed.returncode, (completed.stderr or "").strip()[:200]))

    if temporary is not None:
        try:
            _to_wav(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path
    return target
