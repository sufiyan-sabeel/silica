"""Audio plumbing: WAV in, WAV out, and resampling for Whisper.

Kept dependency-light on purpose. Only numpy is required, because both engines
already need it and a pure-Python resampler would be too slow to be useful.

The engines speak different sample rates (Piper voices are 22.05 kHz or 16 kHz,
Whisper wants exactly 16 kHz), so the resampler is the seam between them.
"""

import wave

import numpy as np

WHISPER_RATE = 16000


class AudioError(ValueError):
    pass


def write_wav(path, samples, rate):
    """Write mono float32 samples in -1..1 as a 16-bit PCM WAV."""
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    clipped = np.clip(data, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm.tobytes())


def read_wav(path):
    """Read a mono/stereo 16-bit PCM WAV. Returns (float32 samples, rate)."""
    try:
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            raw = handle.readframes(frames)
    except FileNotFoundError:
        raise AudioError("no such audio file: %s" % path)
    except wave.Error as exc:
        raise AudioError(
            "%s is not a PCM WAV file (%s)" % (path, exc),
            )
    if width != 2:
        raise AudioError(
            "%s is %d-bit; only 16-bit PCM WAV is supported" % (path, width * 8))
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def resample(samples, rate, target=WHISPER_RATE):
    """Linear resampling. Good enough for speech recognition, and dependency-free."""
    if rate == target:
        return np.asarray(samples, dtype=np.float32)
    data = np.asarray(samples, dtype=np.float32)
    if data.size == 0:
        return data
    count = max(1, int(round(data.size * target / float(rate))))
    positions = np.linspace(0.0, data.size - 1.0, count)
    return np.interp(positions, np.arange(data.size), data).astype(np.float32)


def load_for_whisper(path):
    """Read any supported file and return 16 kHz mono float32."""
    samples, rate = read_wav(path)
    return resample(samples, rate, WHISPER_RATE)


def describe(path):
    """Duration, rate and level of a WAV — used by tests and by `voice info`."""
    samples, rate = read_wav(path)
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    rms = float(np.sqrt((samples ** 2).mean())) if samples.size else 0.0
    return {
        "path": path,
        "seconds": round(samples.size / float(rate), 3) if rate else 0.0,
        "rate": rate,
        "peak": round(peak, 4),
        "rms": round(rms, 4),
        "silent": rms < 0.001,
    }
