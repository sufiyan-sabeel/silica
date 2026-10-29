"""Native functions for the `speech` module.

Silica programs get speech through ordinary calls:

    use speech

    sfn main() {
        speech.save("Hello from Silica", "out/hello.wav")
    }

Privileged operations are declared here and authorised by the VM before the body
runs, exactly like the filesystem module:

    speech.speak      synthesise, and play through the system player
    speech.save       synthesise and write a WAV (path scoped to a speech.speak root)
    speech.transcribe read an audio file and transcribe it (speech.listen root)

`speech.voices`, `speech.languages` and `speech.status` are read-only queries and
need no capability; they only report what is installed.

Downloading a voice is deliberately *not* a Silica function. A program that
silently pulls 60 MB from the network would be a surprise, so installation lives
in the CLI: `silica voice install <name>`.
"""

import os

from ..capabilities import SPEECH_LISTEN, SPEECH_SPEAK
from ..errors import SilicaRuntimeError
from ..natives import type_name


def _fail(message, hint=None):
    raise SilicaRuntimeError(message, hint=hint)


def _need_string(name, value):
    if not isinstance(value, str):
        _fail("%s expects a String, got %s" % (name, type_name(value)))
    return value


def _options(args, index, name):
    if len(args) <= index:
        return {}
    value = args[index]
    if not isinstance(value, dict):
        _fail("%s expects a Map of options, got %s" % (name, type_name(value)))
    return dict(value)


def _engine_error(exc, name):
    """Engine failures are runtime errors with the reason intact."""
    from ..voice import AudioError, STTError, TTSError, VoiceError
    if isinstance(exc, (TTSError, STTError, VoiceError, AudioError)):
        _fail("%s: %s" % (name, exc))
    raise exc


def _voice_options(options, name):
    for key in options:
        if key not in ("voice", "length_scale", "noise_scale", "model", "language"):
            _fail("%s: unknown option '%s'" % (name, key),
                  hint="options: voice, length_scale, noise_scale, model, language")
    return options


def _speak(ctx, args):
    text = _need_string("speech.speak", args[0])
    options = _voice_options(_options(args, 1, "speech.speak"), "speech.speak")
    from .. import voice
    try:
        result = voice.speak(text, voice=options.get("voice"))
    except Exception as exc:
        _engine_error(exc, "speech.speak")
    if not result["played"]:
        _fail("speech.speak could not play the audio: %s" % result["detail"],
              hint="use speech.save(text, path) to write a WAV instead")
    return None


def _save(ctx, args):
    text = _need_string("speech.save", args[0])
    path = _need_string("speech.save", args[1])
    options = _voice_options(_options(args, 2, "speech.save"), "speech.save")
    from .. import voice
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        _fail("speech.save: directory does not exist: %s" % directory,
              hint="Silica does not create directories; create it first")
    try:
        voice.synthesize(text, out=path, voice=options.get("voice"),
                         length_scale=options.get("length_scale"),
                         noise_scale=options.get("noise_scale"))
    except Exception as exc:
        _engine_error(exc, "speech.save")
    return None


def _transcribe(ctx, args):
    path = _need_string("speech.transcribe", args[0])
    options = _voice_options(_options(args, 1, "speech.transcribe"),
                             "speech.transcribe")
    from .. import voice
    if not os.path.exists(path):
        _fail("speech.transcribe: no such audio file: %s" % path)
    try:
        result = voice.transcribe(path, model=options.get("model"),
                                  language=options.get("language"))
    except Exception as exc:
        _engine_error(exc, "speech.transcribe")
    return {
        "text": result["text"],
        "language": result["language"] or "",
        "seconds": result["seconds"],
    }


def _voices(ctx, args):
    from .. import voice
    rows = []
    for entry in voice.voices():
        rows.append({
            "name": entry["name"],
            "language": entry["language"],
            "label": entry["label"],
            "installed": entry["installed"],
            # licence travel with the voice so a caller cannot pick one without
            # being able to see what it is licensed under
            "licence": entry["licence"],
            "licence_url": entry["licence_url"],
            "licence_verified": entry["licence_verified"],
            "commercial_use": entry["commercial_use"],
            "attribution_required": entry["attribution_required"],
            # "" rather than Unit: Silica code can then use len(...) > 0
            "licence_risk": entry["licence_risk"] or "",
        })
    return rows


def _record(ctx, args):
    from .. import voice
    seconds = args[0] if args else 5
    path = _need_string("voice.record", args[1]) if len(args) > 1 else None
    try:
        return voice.record(seconds=seconds, path=path)
    except Exception as exc:  # noqa: BLE001
        _fail("voice.record: %s" % exc)


def _listen(ctx, args):
    from .. import voice
    seconds = args[0] if args else 5
    options = _options(args, 1, "voice.listen")
    try:
        return voice.listen(seconds=seconds,
                            language=options.get("language"),
                            engine=options.get("engine"),
                            model=options.get("model"),
                            path=options.get("path"))
    except Exception as exc:  # noqa: BLE001
        _fail("voice.listen: %s" % exc)


def _platform(ctx, args):
    from .. import voice
    return voice.platform()


def _licence(ctx, args):
    """Licence details for one voice, or for the default when no name is given."""
    from .. import voice
    name = _need_string("voice.licence", args[0]) if args else None
    return voice.licence(name)


def _languages(ctx, args):
    from .. import voice
    return voice.languages()


def _status(ctx, args):
    from .. import voice
    info = voice.status()
    available = voice.available()
    return {
        "can_speak": available["tts"],
        "can_listen": available["stt"],
        "voices_installed": info["voices_installed"],
        "default_voice": info["default_voice"],
        "voices_dir": info["voices_dir"],
    }


# (name, params, ret, fn, min_args, max_args, requires, path_arg)
FUNCTIONS = (
    ("speak", ["String", "Map"], "Unit", _speak, 1, 2, SPEECH_SPEAK, None),
    ("save", ["String", "String", "Map"], "Unit", _save, 2, 3, SPEECH_SPEAK, 1),
    ("transcribe", ["String", "Map"], "Map", _transcribe, 1, 2,
     SPEECH_LISTEN, 0),
    ("voices", [], "List", _voices, 0, 0, None, None),
    ("licence", ["String"], "Map", _licence, 0, 1, None, None),
    ("platform", [], "Map", _platform, 0, 0, None, None),
    ("record", ["Int", "String"], "String", _record, 0, 2, SPEECH_LISTEN, None),
    ("listen", ["Int", "Map"], "Map", _listen, 0, 2, SPEECH_LISTEN, None),
    ("languages", [], "Map", _languages, 0, 0, None, None),
    ("status", [], "Map", _status, 0, 0, None, None),
)
