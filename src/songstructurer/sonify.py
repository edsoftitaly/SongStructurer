"""Click track: the song with audible beats and section changes.

Same recipe as the sonification of the All-In-One analyzer (MIT, Taejun Kim):

* a short click on every beat (1500 Hz) and a higher one on every downbeat
  (3000 Hz);
* before each section change a "riser": 25 clicks over 4 seconds that get
  closer and closer together while their pitch climbs from 40 Hz to 4 kHz;
* on the change itself a half-second downward sweep.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

BEAT_FREQ = 1500.0
DOWNBEAT_FREQ = 3000.0
CLICK_SECONDS = 0.1
RISER_SECONDS = 4.0
RISER_CLICKS = 25
RISER_FREQ_START = 40.0
RISER_FREQ_END = 4000.0
DROP_SECONDS = 0.5
#: A downbeat and a beat closer than this are the same event.
SAME_EVENT_SECONDS = 0.03

CLICK_TRACK_FORMATS = {".mp3": "MP3", ".wav": "WAV", ".flac": "FLAC"}


def synthesize_click(sr: int, freq: float, seconds: float = CLICK_SECONDS) -> np.ndarray:
    """A sine burst whose level halves ten times over its length."""
    n = int(sr * seconds)
    envelope = np.logspace(0, -10, num=n, base=2.0)
    return (envelope * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)


def synthesize_drop(sr: int, seconds: float = DROP_SECONDS) -> np.ndarray:
    """Downward sweep from 4 kHz to 40 Hz marking the section change."""
    n = int(sr * seconds)
    freqs = np.geomspace(RISER_FREQ_END, RISER_FREQ_START, n)
    sweep = np.sin(2 * np.pi * np.cumsum(freqs) / sr)
    return (sweep * np.logspace(0, -4, num=n, base=2.0)).astype(np.float32)


def _add(track: np.ndarray, sound: np.ndarray, time: float, sr: int) -> None:
    start = int(round(time * sr))
    if start < 0 or start >= len(track):
        return
    end = min(len(track), start + len(sound))
    track[start:end] += sound[: end - start]


def riser_offsets() -> np.ndarray:
    """Click times of a riser, in seconds relative to the boundary (< 0)."""
    return -np.geomspace(RISER_SECONDS, CLICK_SECONDS, RISER_CLICKS, endpoint=False)


def click_track(
    n_samples: int,
    sr: int,
    beats: Sequence[float],
    downbeats: Sequence[float] = (),
    boundaries: Sequence[float] = (),
) -> np.ndarray:
    """Mono track of length ``n_samples`` with metronome, risers and drops."""
    track = np.zeros(n_samples, dtype=np.float32)
    down = np.asarray(sorted(downbeats), dtype=float)
    beat_click = synthesize_click(sr, BEAT_FREQ)
    down_click = synthesize_click(sr, DOWNBEAT_FREQ)
    for time in beats:
        if len(down) and np.min(np.abs(down - time)) <= SAME_EVENT_SECONDS:
            continue
        _add(track, beat_click, float(time), sr)
    for time in down:
        _add(track, down_click, float(time), sr)

    offsets = riser_offsets()
    riser = [
        synthesize_click(sr, freq)
        for freq in np.geomspace(RISER_FREQ_START, RISER_FREQ_END, RISER_CLICKS)
    ]
    drop = synthesize_drop(sr)
    for boundary in boundaries:
        for offset, click in zip(offsets, riser):
            if boundary + offset > 0:
                _add(track, click, float(boundary + offset), sr)
        _add(track, drop, float(boundary), sr)
    return track


def sonify(
    samples: np.ndarray,
    sr: int,
    beats: Sequence[float],
    downbeats: Sequence[float] = (),
    boundaries: Sequence[float] = (),
) -> np.ndarray:
    """``samples`` (``(n, channels)``) mixed with the click track, clipped."""
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]
    clicks = click_track(len(audio), sr, beats, downbeats, boundaries)
    return np.clip(audio + clicks[:, np.newaxis], -1.0, 1.0)


def write_click_track(path: str | Path, mixed: np.ndarray, sr: int) -> Path:
    """Save as MP3, WAV or FLAC depending on the extension of ``path``."""
    import soundfile as sf

    path = Path(path)
    fmt = CLICK_TRACK_FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"Formato audio non supportato: {path.suffix or path.name}")
    sf.write(str(path), mixed, sr, format=fmt)
    return path
