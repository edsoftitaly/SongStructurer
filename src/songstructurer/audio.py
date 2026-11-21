"""Audio file loading and waveform envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

SUPPORTED_EXTENSIONS = (".mp3", ".wav", ".flac", ".ogg", ".aiff", ".aif")

#: Samples per bucket of the pre-computed min/max envelope.
ENVELOPE_BLOCK = 256


class AudioLoadError(Exception):
    """Raised when a file cannot be decoded."""


@dataclass(frozen=True)
class Audio:
    """Decoded audio: ``samples`` is float32, shape ``(n, channels)``."""

    samples: np.ndarray
    sr: int
    path: Path | None = None

    @property
    def n_samples(self) -> int:
        return int(self.samples.shape[0])

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration(self) -> float:
        return self.n_samples / float(self.sr)

    def mono(self) -> np.ndarray:
        return self.samples.mean(axis=1)


def load_audio(path: str | Path) -> Audio:
    """Decode ``path`` at its native sample rate, keeping up to two channels."""
    import librosa

    path = Path(path)
    if not path.is_file():
        raise AudioLoadError(f"File non trovato: {path}")
    try:
        data, sr = librosa.load(str(path), sr=None, mono=False)
    except Exception as exc:  # decoders raise a zoo of unrelated exception types
        raise AudioLoadError(f"Impossibile leggere {path.name}: {exc}") from exc
    data = np.asarray(data, dtype=np.float32)
    samples = data[:, np.newaxis] if data.ndim == 1 else data.T
    if samples.shape[0] == 0:
        raise AudioLoadError(f"{path.name} non contiene audio.")
    if samples.shape[1] > 2:
        samples = samples[:, :2]
    samples = np.nan_to_num(np.ascontiguousarray(samples), nan=0.0, posinf=0.0, neginf=0.0)
    return Audio(samples=samples, sr=int(sr), path=path)


class WaveformEnvelope:
    """Min/max envelope of a mono signal, for drawing at any zoom level.

    Averaging samples to decimate a waveform (what version 1 did) cancels the
    signal out; drawing needs the minimum and maximum of each pixel column.
    """

    def __init__(self, mono: np.ndarray, sr: int, block: int = ENVELOPE_BLOCK):
        self._mono = np.asarray(mono, dtype=np.float32)
        self._sr = int(sr)
        self._block = int(block)
        usable = (len(self._mono) // block) * block
        if usable:
            blocks = self._mono[:usable].reshape(-1, block)
            self._lo = blocks.min(axis=1)
            self._hi = blocks.max(axis=1)
        else:
            self._lo = np.zeros(0, dtype=np.float32)
            self._hi = np.zeros(0, dtype=np.float32)

    @property
    def duration(self) -> float:
        return len(self._mono) / float(self._sr)

    def view(
        self, start: float, end: float, columns: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(times, minimum, maximum)`` for ``[start, end]`` seconds."""
        columns = max(1, int(columns))
        first = max(0, int(start * self._sr))
        last = min(len(self._mono), int(np.ceil(end * self._sr)))
        if last <= first:
            empty = np.zeros(0, dtype=np.float32)
            return empty, empty, empty
        span = last - first
        if span >= columns * self._block * 2 and len(self._lo):
            lo_src = self._lo[
                first // self._block : max(first // self._block + 1, last // self._block)
            ]
            hi_src = self._hi[
                first // self._block : max(first // self._block + 1, last // self._block)
            ]
            unit = self._block
            origin = (first // self._block) * self._block
        else:
            lo_src = hi_src = self._mono[first:last]
            unit = 1
            origin = first
        count = len(lo_src)
        columns = min(columns, count)
        bounds = np.linspace(0, count, columns + 1).astype(int)
        starts = bounds[:-1]
        lo = np.minimum.reduceat(lo_src, starts)
        hi = np.maximum.reduceat(hi_src, starts)
        centers = (bounds[:-1] + bounds[1:]) / 2.0
        times = (origin + centers * unit) / float(self._sr)
        return times, lo, hi
