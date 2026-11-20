"""High-level operations shared by the window and the command line."""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from .analysis import AnalysisResult, ProgressCallback
from .audio import Audio, load_audio


def full_analysis(
    audio: Audio,
    python: str | None = None,
    progress: ProgressCallback | None = None,
) -> AnalysisResult:
    """Structure (neural when ``python`` is given, else classic) plus harmony."""
    from .harmony import analyze_harmony

    def scaled(fraction: float, message: str) -> None:
        if progress:
            progress(0.9 * fraction, message)

    if python is not None and audio.path is not None:
        from .neural import analyze_neural

        result = analyze_neural(audio.path, audio.duration, python, progress=scaled)
    else:
        from .analysis import analyze

        result = analyze(audio.mono(), audio.sr, progress=scaled)
    if progress:
        progress(0.92, "Stima degli accordi")
    key, chords = analyze_harmony(audio.mono(), audio.sr, result.beat_times)
    result = replace(result, key=result.key or key, chords=chords)
    if progress:
        progress(1.0, "Analisi completata")
    return result


def export_midi(
    path: str | Path,
    audio: Audio,
    bpm: float,
    python: str | None,
    stems: dict[str, Path] | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, dict[str, int]]:
    """Write melody (vocal stem) and bass as a two-track MIDI file.

    ``stems`` are reused when they exist; otherwise Demucs is run first with
    ``python``. Returns the path and the number of notes per track.
    """
    from .midi import write_midi
    from .stems import StemError, separate
    from .transcribe import transcribe

    def usable(found: dict[str, Path] | None) -> bool:
        return bool(found) and all(
            name in found and Path(found[name]).is_file() for name in ("vocals", "bass")
        )

    with tempfile.TemporaryDirectory(prefix="songstructurer-") as scratch:
        if not usable(stems):
            if python is None or audio.path is None:
                raise StemError(
                    "Per il MIDI servono gli stem: configura il Python del motore neurale."
                )
            stems = separate(audio.path, scratch, python, progress=None)
            if not usable(stems):
                raise StemError("Demucs non ha prodotto gli stem di voce e basso.")
        assert stems is not None
        tracks = []
        counts: dict[str, int] = {}
        for step, (name, stem, kind) in enumerate(
            (("Melody", "vocals", "vocals"), ("Bass", "bass", "bass"))
        ):
            if progress:
                progress(0.5 + 0.2 * step, f"Trascrizione di {name}")
            source = load_audio(stems[stem])
            notes = transcribe(source.mono(), source.sr, kind)
            tracks.append((name, notes))
            counts[name] = len(notes)
        saved = write_midi(path, tracks, bpm)
    if progress:
        progress(1.0, "MIDI pronto")
    return saved, counts
