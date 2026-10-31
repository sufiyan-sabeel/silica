# Speech: text to speech and speech to text

Silica can speak and listen. Both run locally: no API key, no network at runtime,
and nothing you say or type leaves the machine.

```silica
use speech

sfn main() {
    speech.save("Silica can talk.", "out/hello.wav")
    sprint(speech.transcribe("out/hello.wav"))
}
```

---

## What it actually is

| Direction | Engine | Runs on |
|---|---|---|
| Speaking | Piper voices — an ONNX model driven by espeak-ng phonemes | Linux, macOS, Termux |
| Listening | Whisper via `faster-whisper` (CTranslate2) | Linux, macOS, Termux |

Neither engine is bundled. They are optional dependencies, and every failure path
names the missing piece and how to install it instead of producing silence.

**Why not `pip install piper-tts`?** Because it ships glibc-only wheels and a
compiled phonemiser, so it cannot be installed in Termux. Piper's voices are
plain ONNX files and espeak-ng is a small C library that Termux packages, so the
pieces are loaded separately here and one implementation runs everywhere. The
output was compared against `piper-tts` itself: both render the same sentence to
audio that transcribes identically.

---

## Install

### Debian / Ubuntu

```bash
pip install onnxruntime faster-whisper espeakng-loader
```

`espeakng-loader` bundles `libespeak-ng.so` and the language data, which is what
makes this work with pip alone. If you prefer the system library:
`sudo apt install libespeak-ng1` and skip `espeakng-loader`.

### Termux

```bash
pkg install python onnxruntime espeak ctranslate2
pip install faster-whisper
```

No `proot`, no `sudo`. `espeak` provides `libespeak-ng.so` and the language data,
`onnxruntime` runs the voice model, and `ctranslate2` runs Whisper — this is
exactly why the engines were chosen. **This path is not verified on a device**:
no Termux environment was available. The code paths it depends on are the same
ones tested on Linux, but treat Termux as expected-to-work rather than proven.

### Voices

One 63 MB download per voice:

```bash
silica voice install en_US-lessac-medium
silica voice list          # what exists, and what is installed
```

They land in `$SILICA_HOME/voices` (`~/.local/share/silica/voices`), the same
directory the installer creates, so `uninstall.sh` cleans them up too.

---

## Using it from Silica

There are two namespaces and they are the same code: **`voice`** is the preferred
name, **`speech`** stays fully supported for programs written against 0.4.0.
Neither is deprecated. `voice.speak` and `speech.speak` are literally the same
function object, so there is one implementation, one registry and one set of
permission requirements — a test asserts that identity.

```silica
use voice

sfn main() {
    # say something out loud (needs a system player)
    speech.speak("Hello from Silica")

    # or write a file
    speech.save("नमस्ते, मैं सिलिका हूँ।", "out/hi.wav",
                {voice: "hi_IN-pratham-medium"})

    # and listen
    let heard: Map = speech.transcribe("out/hi.wav", {language: "hi"})
    sprint(heard["text"])
    sprint(heard["language"])
}
```

Run with the capabilities it needs:

```bash
silica run hello.sc --allow-speech-speak out --allow-speech-listen out
```

The capability names did not change with the namespace: `speech.speak` and
`speech.listen` still guard both `voice.*` and `speech.*`, because the grant is
on the capability, not on the spelling.

---

## Engines

Speech out and speech in each sit behind an interface, so the engine can be
swapped without touching the API:

| Direction | Engines | Selected by |
|---|---|---|
| speech out | `piper` (default), `sherpa` | `SILICA_VOICE_TTS` |
| speech in | `whisper` (default), `sherpa` | `SILICA_VOICE_STT` |

```bash
SILICA_VOICE_TTS=auto      # default: piper, falling back to sherpa
SILICA_VOICE_STT=sherpa    # force one engine
```

`auto` prefers the engines Silica has shipped and tested — Piper and Whisper —
and only falls back when they cannot run. That keeps existing behaviour identical
while making the alternative reachable.

`voice.status()["engines"]` reports every engine and, when one is unavailable,
the reason. Nothing is guessed:

```
tts  piper   available=False  needs onnxruntime=... and espeak-ng available=False
tts  sherpa  available=False  sherpa-onnx is not installed. Install it with: pip install sherpa-onnx
```

### The sherpa-onnx engine

Optional and opt-in; it is not a dependency of Silica. It exists because Piper's
and Whisper's wheels are glibc-only and do not install on Termux, where
sherpa-onnx publishes builds.

```bash
pip install sherpa-onnx numpy

export SILICA_SHERPA_TTS_MODEL=/path/to/vits-piper-voice   # model.onnx, tokens.txt, espeak-ng-data/
export SILICA_SHERPA_ASR_MODEL=/path/to/whisper-model      # encoder/decoder .onnx + tokens
export SILICA_VOICE_TTS=sherpa SILICA_VOICE_STT=sherpa
```

Two things this engine will tell you rather than let you discover:

* **sherpa-onnx 2.x cannot run Piper-style voices.** It ignores `data_dir` and
  wants phoneme code points from an external phonemizer. Pin `sherpa-onnx<2`
  (1.13.x) for Piper voices; the engine refuses on 2.x with that explanation.
* **Nothing is downloaded.** The model directories must already exist. That is
  the offline guarantee, and an engine that fetched its own models would break it.

Measured on Linux x86_64 with sherpa-onnx 1.13.8 and a Piper `lessac` int8 voice:
synthesis RTF 0.99, transcription RTF 0.42, peak RSS 438 MB. **Android and Termux
remain untested** — see `docs/VOICE.md` limits.

---

## Offline guarantees

Speech runs on the machine it is on. No account, no API key, no telemetry, and no
silent fallback to a cloud service — because there is no cloud path to fall back
to: nothing in the speech code can reach a network except the download function.

That is a claim, so it ships with a way to check it:

```bash
python tools/offline_check.py
```

```json
{
  "network_events": [],
  "synthesis": "ok: 132682 bytes",
  "transcription": "ok: 'A flying check. Nothing here should reach the network.'",
  "voice": "en_GB-alba-medium",
  "model_verified": true,
  "offline": true
}
```

The tool installs an audit hook that records every socket and URL event Python
can report, *before* importing Silica, then synthesises and transcribes. Any
network attempt makes it exit non-zero.

**What it proves:** inference through Python opens no sockets — including from C
extensions that go through the socket module. That is stronger than stubbing
`socket.socket`, which a module holding its own reference can bypass.

**What it does not prove:** that no other process on the machine used the network,
or that a native library opening a socket outside Python's socket module would be
seen. The stronger test is a real network namespace:

```bash
unshare -n python tools/offline_check.py     # needs privileges
```

That is not permitted in the environment this was built in, so it has not been
run — say so rather than imply otherwise.

### Four rules the code actually follows

1. **Downloads are explicit.** `voice.download_model` / `silica voice install`
   run because someone asked. Nothing fetches in the background, and inference
   never triggers a fetch.
2. **Inference never downloads.** faster-whisper used to ask the Hugging Face Hub
   whether a newer revision existed *on every load*, opening sockets during what
   was meant to be an offline transcription. Models are now loaded with
   `local_files_only=True`; fetching one takes a deliberate
   `SILICA_WHISPER_ALLOW_DOWNLOAD=1`.
3. **Checksums are recorded and enforced.** Every download stores its SHA-256 in
   `manifest.json`, and a model whose contents changed is **refused at load
   time** — a voice file is loaded into an inference session, so a silent
   substitution is not something to shrug at. `SILICA_VOICE_SKIP_VERIFY=1`
   bypasses it deliberately.
4. **Deletion and usage are visible.** `voice.storage()` and
   `silica voice models` show what is on disk; `silica voice remove` frees it.

---

## Managing models

Voices are files, and the API treats them that way — you can see what you have,
check it has not rotted, and remove it.

```silica
use voice

sfn main() {
    per model in voice.models() {
        sprint(model["name"] + "  " + model["licence"] + "  " + str(model["bytes"]))
    }

    let disk = voice.storage()
    sprint(str(disk["model_megabytes"]) + " MB of voices")

    let check = voice.verify("en_GB-alba-medium")
    sprint(str(check["verified"]))
}
```

| Function | What it does | Capability |
|---|---|---|
| `voice.models()` | installed models with size, checksum and licence | none |
| `voice.storage()` | bytes used, split into models and bookkeeping | none |
| `voice.verify(name)` | re-hash and compare with the checksum recorded at download | none |
| `voice.set_voice(name)` | choose the voice later calls use; `""` clears it | none |
| `voice.current_voice()` | which voice a call without a name would use | none |
| `voice.download_model(name)` | fetch a voice | **`speech.models`** |
| `voice.delete_model(name)` | remove a voice, returning bytes freed | **`speech.models`** |

Downloading and deleting get their own capability because they reach the network
and the disk — a different act from speaking, and one that should be asked for:

```bash
silica run manage.sc --allow-speech-models
```

**Nothing downloads by itself.** There is no automatic fetch anywhere in Silica;
`download_model` runs only because a program called it.

### Checksums

Every download records the file's SHA-256 and size in
`$SILICA_HOME/voices/manifest.json`. `voice.verify(name)` re-hashes the file and
compares. A voice installed before the manifest existed reports
`verified: false` with the reason `no checksum was recorded for this voice` —
rather than pretending it is fine.

### Choosing a voice

`voice.set_voice(name)` persists to `$SILICA_HOME/voices/selection`, so it
survives between runs. Precedence when a call does not name a voice:

1. an explicit argument
2. `SILICA_VOICE`
3. the saved selection
4. whatever is installed

---

## Playback and recording

Playback and the microphone belong to the operating system, so one module decides
which program to use — by looking, never by assuming:

```silica
use voice

sfn main() {
    # what this machine can actually do
    let here = voice.platform()
    sprint(here["playback"])        # e.g. "paplay", or unit
    sprint(here["recording"])       # e.g. "arecord", or unit

    # record three seconds, then transcribe
    let heard = voice.listen(3, {language: "en"})
    sprint(heard["text"])
}
```

```bash
silica run listen.sc --allow-speech-listen /tmp --allow-speech-speak /tmp
```

`voice.record(seconds, path)` captures a WAV and returns the path;
`voice.listen(seconds, options)` records and transcribes in one step. Recording
never starts on its own — something has to call it, and it needs the
`speech.listen` capability.

### What gets detected

| | Order tried |
|---|---|
| playback | `termux-media-player`, `paplay`, `aplay`, `afplay`, `play` (sox) |
| recording | `arecord`, `rec`, `termux-microphone-record`, `ffmpeg` |

Termux is recognised from `TERMUX_VERSION`, a `$PREFIX` containing `com.termux`, or
the Termux data directory — **not** from `platform.system()` saying Linux, which
would be true of any desktop.

### The Termux microphone caveat

`termux-microphone-record` writes M4A/3GP, and every speech model Silica can drive
wants 16-bit PCM WAV. So recording on Termux is two steps: capture, then convert
with `ffmpeg`. If ffmpeg is missing, `voice.record` says so rather than handing
back a file nothing can read:

```
termux-microphone-record records in a compressed format and ffmpeg is not
installed to convert it to WAV
```

Install it with `pkg install ffmpeg`.

**None of the recording path has been tested on a device.** It is tested with
stand-in binaries that behave like the real ones; see the limits below.

---

## Licensing — read this before shipping anything

Every voice is trained on a dataset whose licence governs redistribution and
commercial use. Those licences differ sharply, and **two of the voices this
project used to offer are non-commercial**. Nothing below is inferred: each entry
was read from the voice's own model card.

| Voice | Licence | Commercial use | Verified |
|---|---|---|---|
| `en_GB-alba-medium` | CC-BY-4.0 | **yes** (attribution) | yes |
| `te_IN-padmavathi-medium` | CC-BY-4.0 | **yes** (attribution) | yes |
| `bn_BD-google-medium` | CC-BY-SA-4.0 | **yes** (attribution + share-alike) | yes |
| `mr_IN-google-medium` | CC-BY-SA-4.0 | **yes** (attribution + share-alike) | yes |
| `hi_IN-pratham-medium` | CC-BY-NC-SA-4.0 | **no — non-commercial** | yes |
| `hi_IN-priyamvada-medium` | CC-BY-NC-SA-4.0 | **no — non-commercial** | yes |
| `en_US-lessac-medium` | Blizzard 2013 | unknown | **no** |
| `en_US-amy-medium` | "see model card" (mimic3) | unknown | **no** |
| `ml_IN-meera-medium` | "see model card" (Kaggle) | unknown | **no** |
| `hi_IN-rohan-medium` | IITM IndicTTS | unknown | **no** |
| `te_IN-maya-medium` | IITM IndicTTS | unknown | **no** |

Only **four** voices have a licence that is verified and permits commercial use.

The API exposes this rather than hiding it:

```silica
use voice

sfn main() {
    let entry = voice.licence("hi_IN-pratham-medium")
    sprint(entry["id"])          # CC-BY-NC-SA-4.0
    sprint(str(entry["commercial"]))   # nein

    # licence_risk is "" when the voice is safe to ship
    per row in voice.voices() {
        si len(row["licence_risk"]) > 0 {
            sprint(row["name"] + ": " + row["licence_risk"])
        }
    }
}
```

`voice.licence(name)` returns `id`, `url`, `verified`, `commercial`,
`attribution` and `share_alike`. An unknown voice reports `id = "unknown"` and
`verified = false` — it is never given a convenient default.

**The default voice is still `en_US-lessac-medium`, whose licence is unverified.**
That was kept for compatibility with 0.4.0 programs, not because it is safe. If
you are building something you intend to distribute, choose one of the four
verified voices above, or set `SILICA_VOICE=en_GB-alba-medium`.

The non-commercial voices are not blocked: personal and research use is exactly
what those licences permit, and Silica cannot know your use. They are marked, and
you are expected to read the marking.

### The functions

| Function | Capability | What it does |
|---|---|---|
| `speech.speak(text, opts?)` | `speech.speak` | Synthesise and play through the system player |
| `speech.save(text, path, opts?)` | `speech.speak` | Synthesise and write a 16-bit mono WAV |
| `speech.transcribe(path, opts?)` | `speech.listen` | Transcribe an audio file → `{text, language, seconds}` |
| `speech.voices()` | none | Every known voice and whether it is installed |
| `speech.languages()` | none | What can be spoken, what cannot, what can be heard |
| `speech.status()` | none | Which engines are present here |

Options: `voice`, `length_scale` (larger is slower), `noise_scale`, `model`,
`language`.

### Why capabilities

Audio output and audio input are privileged. They are named capabilities with
directory roots, checked by the VM before the function body runs — the same model
`fs.*` uses:

```
main.sc:5: capability error: capability 'speech.speak' (synthesise and play
speech) is not granted
  hint: grant it with --allow-speech-speak <dir>; Silica grants nothing by default
```

Downloading a voice is deliberately **not** a Silica function. A program that
silently pulls 60 MB over the network would be a surprise, so installation lives
in the CLI.

---

## Languages

`silica voice languages` prints this, and it is generated from the catalogue, not
written by hand:

| Language | Speaking | Listening |
|---|---|---|
| English (US, GB) | yes | yes |
| Hindi | yes | yes |
| Telugu | yes | yes |
| Bengali | yes | yes |
| Malayalam | yes | yes |
| Marathi | yes | yes |
| **Tamil** | **no voice exists** | yes |
| Kannada | no voice exists | yes |
| Gujarati | no voice exists | yes |
| Punjabi | no voice exists | yes |
| Urdu, Nepali | yes (Urdu, Nepali) | yes |

Piper simply has no Tamil, Kannada, Gujarati or Punjabi voices. Speaking those
would need a different engine — a large multilingual model, or a cloud API such
as Sarvam's Bulbul, which would bring back an API key and network access. Whisper
is multilingual, so listening covers them today.

The two directions are not symmetric, and the documentation says so rather than
implying a language "works" because half of it does.

---

## How good is it?

Piper is a neural voice. It is clearly better than formant synthesis (espeak
alone) and clearly not as natural as a large cloud model. "Talks like a real
voice" is a judgement about listening, and this project does not have ears.

What it does have is an objective check. The English voice is verified by round
trip: synthesise a sentence, transcribe it with Whisper, and compare.

```
$ silica voice speak "Silica can speak and listen now." --out en.wav
wrote en.wav (1.89s, 22050 Hz)

$ silica voice transcribe en.wav
Silica can speak and listen now.
(en, 0.96 confidence, 1.89s of audio)
```

Word for word, 0.96 confidence. That is evidence the audio is intelligible
speech and not noise. It is not evidence that it sounds pleasant.

Two honest caveats:

* The Hindi round trip through the `tiny` Whisper model is unreliable — it
  returned a garbled mix. That reflects the small recognition model, not
  necessarily the synthesis. Use `--model base` or better to judge Hindi.
* No audio device exists in the environment this was built in, so nothing was
  ever played aloud. Files were generated and measured (duration, sample rate,
  RMS, peak), and transcribed. Playback itself is untested here.

---

## Command line

```bash
silica voice list                     # catalogue and what is installed
silica voice languages                # speaking vs listening coverage
silica voice status                   # which engines are present
silica voice install [name]           # download a voice
silica voice speak "text" [--voice N] [--out PATH]
silica voice transcribe file.wav [--model tiny|base|small] [--language hi]
silica voice info file.wav            # duration, rate, level, silence
```

---

## Limits, stated plainly

* **No Tamil, Kannada, Gujarati or Punjabi voices.** Engine limitation, not a
  bug to be fixed by configuration.
* **`tiny` Whisper by default** because `base` needs about a gigabyte of RAM and
  phones do not have it. `SILICA_WHISPER_MODEL=base` for better accuracy.
* **16-bit PCM WAV only** for input. MP3 and M4A would need PyAV, whose file
  path is version-sensitive; WAV avoids that dependency entirely.
* **Termux is untested on a device.** Detection and command construction are
  covered by tests with stand-in binaries; nothing here has run on Android.
* **Microphone capture is untested on every platform.** No microphone exists in
  the environment this was built in.
* **Playback needs a system player.** `speech.speak` errors clearly if none of
  `paplay`, `aplay`, `play`, `afplay` or `termux-media-player` is present.
* **No streaming.** Synthesis and transcription are whole-utterance; there is no
  partial output.
* **No voice cloning, no emotion control**, and `length_scale`/`noise_scale` are
  the only prosody knobs.
* **Five of the eleven voices have an unverified licence**, and two are
  non-commercial. See the licensing section.
* **The default voice is one of the unverified ones**, kept for compatibility.

---

## Tests

`tests/test_voice.py` has two tiers. The default tier runs everywhere, with no
engine installed: the catalogue, the WAV plumbing, resampling, the capability
boundary, the CLI, and the "engine missing" errors.

The second tier needs real engines and a downloaded voice:

```bash
SILICA_VOICE_TESTS=1 SILICA_VOICES=~/.local/share/silica/voices \
  python -m pytest tests/test_voice.py
```

It synthesises a sentence, transcribes it and compares the text. On a machine
with under ~1.5 GB free RAM, run the two halves in separate processes — loading
onnxruntime and CTranslate2 together is what runs out of memory first.
