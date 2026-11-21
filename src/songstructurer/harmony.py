"""Chord and key estimation from chroma (classic template matching).

Beat-synchronous chroma is compared with major, minor and power-chord
templates; a Viterbi pass with a "stay on the same chord" bias removes the
flicker. It names plain triads and fifths only: no sevenths, no inversions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .analysis import ANALYSIS_SR, HOP_LENGTH, PITCH_NAMES, estimate_key

NO_CHORD = "N"
#: (suffix, semitones above the root, weight of each chord tone)
_QUALITIES = (
    ("", (0, 4, 7), (1.0, 0.8, 0.9)),
    ("m", (0, 3, 7), (1.0, 0.8, 0.9)),
    ("5", (0, 7), (1.0, 0.9)),
)


@dataclass(frozen=True)
class Chord:
    start: float
    end: float
    name: str


def chord_templates() -> tuple[list[str], np.ndarray]:
    """Names and unit-norm 12-bin templates of every chord the model knows."""
    names: list[str] = []
    rows = []
    for suffix, intervals, weights in _QUALITIES:
        for root in range(12):
            row = np.zeros(12)
            for interval, weight in zip(intervals, weights):
                row[(root + interval) % 12] = weight
            names.append(PITCH_NAMES[root] + suffix)
            rows.append(row / np.linalg.norm(row))
    return names, np.array(rows)


def decode_chords(
    chroma: np.ndarray, silent: np.ndarray | None = None, stay_bonus: float = 0.12
) -> list[str]:
    """Most likely chord name for each column of a ``(12, n)`` chroma."""
    names, templates = chord_templates()
    n = chroma.shape[1]
    if n == 0:
        return []
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    unit = chroma / np.maximum(norms, 1e-9)
    scores = templates @ unit  # (chords, n)
    # A fifth is a subset of both triads on its root: it must win only when
    # the third is really missing, so it pays a small price.
    penalty = np.array([0.0 if not name.endswith("5") else 0.03 for name in names])
    scores = scores - penalty[:, np.newaxis]
    quiet = norms[0] <= 1e-6 if silent is None else (np.asarray(silent) | (norms[0] <= 1e-6))

    best = scores[:, 0].copy()
    back = np.zeros((len(names), n), dtype=int)
    for t in range(1, n):
        stay = best + stay_bonus
        jump_from = int(np.argmax(best))
        jump = best[jump_from]
        choose_stay = stay >= jump
        back[:, t] = np.where(choose_stay, np.arange(len(names)), jump_from)
        best = np.where(choose_stay, stay, jump) + scores[:, t]
    path = np.zeros(n, dtype=int)
    path[-1] = int(np.argmax(best))
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[path[t], t]
    return [NO_CHORD if quiet[t] else names[path[t]] for t in range(n)]


def merge_chords(names: Sequence[str], edges: Sequence[float]) -> list[Chord]:
    """Collapse runs of equal names; ``edges`` has ``len(names) + 1`` times."""
    chords: list[Chord] = []
    for index, name in enumerate(names):
        start, end = float(edges[index]), float(edges[index + 1])
        if end <= start:
            continue
        if chords and chords[-1].name == name:
            chords[-1] = Chord(chords[-1].start, end, name)
        else:
            chords.append(Chord(start, end, name))
    return chords


def analyze_harmony(
    samples: np.ndarray, sr: int, beat_times: Sequence[float]
) -> tuple[str, list[Chord]]:
    """Key (e.g. ``"Em"``) and chord sequence of a signal.

    Chords change on the beats in ``beat_times``; without beats a 0.5 s grid
    is used.
    """
    import librosa

    y = np.asarray(samples, dtype=np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    duration = len(y) / float(sr)
    if y.size == 0 or not np.any(np.abs(y) > 1e-6):
        return "", []
    if sr != ANALYSIS_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=ANALYSIS_SR)
    chroma = librosa.feature.chroma_cqt(
        y=y, sr=ANALYSIS_SR, hop_length=HOP_LENGTH, bins_per_octave=36
    )
    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0][: chroma.shape[1]]
    chroma = chroma[:, : len(rms)]
    level = 20.0 * np.log10(np.maximum(rms, 1e-10) / max(float(rms.max()), 1e-10))
    active = level > -50.0
    key = estimate_key(chroma[:, active].mean(axis=1)) if np.any(active) else ""

    times = sorted(t for t in beat_times if 0.0 < t < duration)
    if len(times) < 4:
        times = list(np.arange(0.5, duration, 0.5))
    edges = np.array([0.0, *times, duration])
    frames = librosa.time_to_frames(edges[:-1], sr=ANALYSIS_SR, hop_length=HOP_LENGTH)
    frames = librosa.util.fix_frames(frames, x_min=0, x_max=None)
    frames = frames[frames < chroma.shape[1]]
    synced = librosa.util.sync(chroma, frames, aggregate=np.median)
    quiet = librosa.util.sync(level[np.newaxis, :], frames, aggregate=np.median)[0] <= -50.0
    count = min(synced.shape[1], len(edges) - 1)
    names = decode_chords(synced[:, :count], quiet[:count])
    span = np.concatenate([edges[:count], [duration]])
    return key, merge_chords(names, span)
