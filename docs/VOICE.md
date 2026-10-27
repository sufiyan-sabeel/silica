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

```silica
use speech

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
* **Termux is untested on a device.**
* **Playback needs a system player.** `speech.speak` errors clearly if none of
  `paplay`, `aplay`, `play`, `afplay` or `termux-media-player` is present.
* **No streaming.** Synthesis and transcription are whole-utterance; there is no
  partial output.
* **No voice cloning, no emotion control**, and `length_scale`/`noise_scale` are
  the only prosody knobs.

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
