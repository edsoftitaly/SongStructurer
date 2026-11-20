"""Stem separation with Demucs, run in the external Python interpreter.

Demucs is installed together with ``allin1``, so the interpreter configured
for the neural engine can separate stems too.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analysis import ProgressCallback
from .neural import _hidden_window

#: Menu name -> Demucs model.
MODELS = {
    "4 stem (voce, basso, batteria, altro)": "htdemucs",
    "6 stem (+ chitarra e piano)": "htdemucs_6s",
}
DEFAULT_MODEL = "htdemucs"


class StemError(Exception):
    """Raised when Demucs cannot be run or produces nothing."""


def separate(
    audio_path: str | Path,
    out_dir: str | Path,
    python: str,
    model: str = DEFAULT_MODEL,
    progress: ProgressCallback | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Path]:
    """Separate ``audio_path``; returns ``{"vocals": path, "bass": path, ...}``.

    The stems are written as ``<song> - <stem>.wav`` inside ``out_dir``.
    """
    audio_path, out_dir = Path(audio_path), Path(out_dir)
    if progress:
        progress(0.1, "Separazione degli stem con Demucs (può richiedere alcuni minuti)")
    with tempfile.TemporaryDirectory(prefix="songstructurer-") as scratch:
        command = [python, "-m", "demucs", "-n", model, "-o", scratch, str(audio_path)]
        try:
            done = runner(command, capture_output=True, text=True, **_hidden_window())
        except OSError as exc:
            raise StemError(f"Impossibile avviare {python}: {exc}") from exc
        produced = sorted(Path(scratch).rglob("*.wav"))
        if getattr(done, "returncode", 1) != 0 or not produced:
            lines = (getattr(done, "stderr", "") or "").strip().splitlines()
            detail = lines[-1] if lines else f"exit code {getattr(done, 'returncode', '?')}"
            raise StemError(f"Demucs non ha prodotto gli stem: {detail}")
        out_dir.mkdir(parents=True, exist_ok=True)
        stems: dict[str, Path] = {}
        for source in produced:
            target = out_dir / f"{audio_path.stem} - {source.stem}.wav"
            shutil.move(str(source), target)
            stems[source.stem] = target
    if progress:
        progress(1.0, "Stem pronti")
    return stems
