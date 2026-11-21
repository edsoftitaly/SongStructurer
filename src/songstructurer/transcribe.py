"""Monophonic transcription (pYIN) of an isolated vocal or bass stem.

Meant for stems, not for full mixes: on a mix the pitch tracker follows
whatever is loudest and the result is useless.
"""

from __future__ import annotations

import numpy as np

from .midi import Note

TRANSCRIBE_SR = 22050
HOP = 256
#: name -> (lowest note, highest note, analysis window)
RANGES = {
    "vocals": ("C2", "C6", 2048),
    "bass": ("B0", "G3", 4096),
}
MIN_NOTE_SECONDS = 0.08
MAX_GAP_SECONDS = 0.05


def notes_from_pitch(
    midi_pitch: np.ndarray,
    voiced: np.ndarray,
    level_db: np.ndarray,
    frame_seconds: float,
) -> list[Note]:
    """Turn a frame-wise pitch track into notes.

    ``midi_pitch`` may be fractional; frames are rounded to semitones, runs
    of the same semitone become notes, short gaps inside a note are bridged
    and notes shorter than ``MIN_NOTE_SECONDS`` are dropped.
    """
    semitone = np.where(voiced, np.round(np.nan_to_num(midi_pitch)), -1).astype(int)
    runs: list[list[int]] = []  # [first frame, last frame + 1, pitch]
    start = 0
    for frame in range(1, len(semitone) + 1):
        if frame == len(semitone) or semitone[frame] != semitone[start]:
            if semitone[start] >= 0:
                runs.append([start, frame, int(semitone[start])])
            start = frame
    merged: list[list[int]] = []
    max_gap = MAX_GAP_SECONDS / frame_seconds
    for run in runs:
        if merged and merged[-1][2] == run[2] and run[0] - merged[-1][1] <= max_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    notes = []
    for first, last, pitch in merged:
        if (last - first) * frame_seconds < MIN_NOTE_SECONDS:
            continue
        loudness = float(np.max(level_db[first:last])) if last > first else -60.0
        velocity = int(np.clip(110 + 1.5 * loudness, 30, 120))
        notes.append(Note(first * frame_seconds, last * frame_seconds, pitch, velocity))
    return notes


def transcribe(samples: np.ndarray, sr: int, kind: str = "vocals") -> list[Note]:
    """Notes of a monophonic stem; ``kind`` is ``"vocals"`` or ``"bass"``."""
    import librosa

    low, high, window = RANGES[kind]
    y = np.asarray(samples, dtype=np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    if y.size == 0 or not np.any(np.abs(y) > 1e-5):
        return []
    if sr != TRANSCRIBE_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=TRANSCRIBE_SR)
    f0, voiced, _prob = librosa.pyin(
        y,
        fmin=float(librosa.note_to_hz(low)),
        fmax=float(librosa.note_to_hz(high)),
        sr=TRANSCRIBE_SR,
        frame_length=window,
        hop_length=HOP,
    )
    rms = librosa.feature.rms(y=y, frame_length=window, hop_length=HOP)[0]
    count = min(len(f0), len(rms))
    level = 20.0 * np.log10(np.maximum(rms[:count], 1e-10) / max(float(rms.max()), 1e-10))
    # Pitch found in what is practically silence is bleed from other stems.
    voiced = np.asarray(voiced[:count], dtype=bool) & (level > -40.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        pitch = librosa.hz_to_midi(f0[:count])
    return notes_from_pitch(pitch, voiced, level, HOP / TRANSCRIBE_SR)
