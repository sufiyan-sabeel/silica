"""Prove that speech inference does not touch the network.

Run it after installing a voice:

    python tools/offline_check.py

It installs an audit hook that records every socket and URL event Python can
report, then synthesises speech and transcribes it. If any network event appears,
the check fails and prints what was attempted.

What this proves and what it does not
-------------------------------------
Python's audit hooks see socket creation and connection attempts made *through
Python*, including C extensions that go through the socket module. That is
stronger than replacing `socket.socket` with a stub, because a stub can be
bypassed by a module that kept its own reference.

It does not prove that no process on the machine made a connection, and it cannot
see inside a native library that opens a socket without going through Python's
socket module. The stronger test is to run with networking actually unavailable —
`unshare -n python tools/offline_check.py` on Linux — which this script does not
do for you because it needs privileges.

The audit hook is installed before Silica is imported, so an import-time network
call is caught too.
"""

import json
import os
import sys
import tempfile

NETWORK_EVENTS = ("socket.__new__", "socket.connect", "socket.getaddrinfo",
                  "socket.bind", "socket.sendto", "socket.gethostbyname",
                  "urllib.Request", "http.client.connect")

seen = []


def _hook(event, args):
    if event in NETWORK_EVENTS or event.startswith("socket."):
        seen.append(event)


sys.addaudithook(_hook)

# Imported after the hook, deliberately.
from silica import voice  # noqa: E402


def main():
    report = {"network_events": None, "synthesis": None, "transcription": None,
              "voice": None, "model_verified": None}

    if not voice.available()["tts"]:
        report["synthesis"] = "skipped: no TTS engine available"
    if not voice.available()["stt"]:
        report["transcription"] = "skipped: no STT engine available"

    name = voice.current_voice()
    report["voice"] = name
    check = voice.verify(name)
    report["model_verified"] = check["verified"]

    directory = tempfile.mkdtemp(prefix="silica-offline-")
    wav = os.path.join(directory, "check.wav")

    if voice.available()["tts"]:
        voice.synthesize("Offline check. Nothing here should reach the network.",
                         out=wav, voice=name)
        report["synthesis"] = "ok: %d bytes" % os.path.getsize(wav)

    if voice.available()["stt"] and os.path.exists(wav):
        heard = voice.transcribe(wav)
        report["transcription"] = "ok: %r" % heard["text"][:60]

    # the read-only surface must not reach out either
    voice.models()
    voice.storage()

    report["network_events"] = sorted(set(seen))
    report["offline"] = not seen
    print(json.dumps(report, indent=2))
    return 0 if not seen else 1


if __name__ == "__main__":
    sys.exit(main())
