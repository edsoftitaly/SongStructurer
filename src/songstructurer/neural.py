"""Optional neural analysis engine: the All-In-One model (``allin1``).

``allin1`` needs PyTorch and Demucs, several gigabytes that do not belong in a
portable executable. The model therefore runs in a separate Python interpreter
chosen by the user (the one where ``allin1`` is installed, typically with a
CUDA build of torch); SongStructurer starts :mod:`neural_worker` there and
reads back a JSON file. The classic engine stays the built-in default.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analysis import (
    LABEL_SILENCE,
    SILENCE_GROUP,
    AnalysisError,
    AnalysisResult,
    ProgressCallback,
    Section,
)

ENV_PYTHON = "SONGSTRUCTURER_PYTHON"

#: Names used by the model (Harmonix label set) -> names shown to the user.
LABEL_NAMES = {
    "start": LABEL_SILENCE,
    "end": LABEL_SILENCE,
    "intro": "Intro",
    "outro": "Outro",
    "break": "Break",
    "bridge": "Bridge",
    "inst": "Instrumental",
    "solo": "Solo",
    "verse": "Verse",
    "chorus": "Chorus",
}


def worker_path() -> Path:
    return Path(__file__).with_name("neural_worker.py")


def _hidden_window() -> dict[str, Any]:
    """Keep a console window from flashing up under the windowed executable."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def find_python(configured: str = "") -> str | None:
    """Interpreter to run the model with, or ``None`` if none is known.

    Order: explicit setting, ``SONGSTRUCTURER_PYTHON``, then the current
    interpreter when SongStructurer runs from source next to ``allin1``.
    """
    for candidate in (configured, os.environ.get(ENV_PYTHON, "")):
        if candidate and Path(candidate).is_file():
            return candidate
    frozen = getattr(sys, "frozen", False)
    if not frozen and importlib.util.find_spec("allin1") is not None:
        return sys.executable
    return None


def check_python(python: str, timeout: float = 180.0) -> tuple[bool, str]:
    """Whether ``python`` can import ``allin1``; returns ``(ok, detail)``."""
    code = "import allin1, torch; print(allin1.__version__, torch.__version__)"
    try:
        done = subprocess.run(
            [python, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_hidden_window(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        return False, lines[-1] if lines else f"exit code {done.returncode}"
    return True, done.stdout.strip()


def result_from_payload(payload: dict[str, Any], duration: float) -> AnalysisResult:
    """Convert the worker's JSON into an :class:`AnalysisResult`.

    The sections are made to tile ``[0, duration]`` exactly and get one group
    per label.
    """
    if payload.get("error"):
        raise AnalysisError(f"Il motore neurale ha restituito un errore: {payload['error']}")
    raw = sorted(payload.get("segments") or [], key=lambda s: float(s["start"]))
    groups: dict[str, int] = {}
    sections: list[Section] = []
    cursor = 0.0
    for index, seg in enumerate(raw):
        last = index == len(raw) - 1
        end = duration if last else min(max(float(seg["end"]), cursor), duration)
        if end - cursor < 1e-3:
            continue
        name = str(seg["label"])
        label = LABEL_NAMES.get(name, name.capitalize() or "Section")
        group = SILENCE_GROUP if label == LABEL_SILENCE else groups.setdefault(label, len(groups))
        sections.append(Section(cursor, end, label, group))
        cursor = end
    if not sections:
        raise AnalysisError("Il motore neurale non ha trovato sezioni.")

    def times(key: str) -> list[float]:
        return sorted(float(t) for t in payload.get(key) or [] if 0.0 <= float(t) <= duration)

    return AnalysisResult(
        duration=duration,
        tempo=float(payload.get("bpm") or 0.0),
        key="",
        sections=sections,
        beat_times=times("beats"),
        downbeat_times=times("downbeats"),
        engine="neural",
    )


def analyze_neural(
    audio_path: str | Path,
    duration: float,
    python: str,
    progress: ProgressCallback | None = None,
    device: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> AnalysisResult:
    """Analyse ``audio_path`` with ``allin1`` running under ``python``."""
    if progress:
        progress(0.1, "Analisi neurale in corso (può richiedere alcuni minuti)")
    with tempfile.TemporaryDirectory(prefix="songstructurer-") as scratch:
        output = Path(scratch) / "result.json"
        command = [python, str(worker_path()), str(audio_path), str(output)]
        if device:
            command += ["--device", device]
        try:
            done = runner(command, capture_output=True, text=True, **_hidden_window())
        except OSError as exc:
            raise AnalysisError(f"Impossibile avviare {python}: {exc}") from exc
        payload: dict[str, Any] | None = None
        if output.is_file():
            try:
                payload = json.loads(output.read_text(encoding="utf-8"))
            except ValueError:
                payload = None
        if payload is None:
            lines = (getattr(done, "stderr", "") or "").strip().splitlines()
            detail = lines[-1] if lines else f"exit code {getattr(done, 'returncode', '?')}"
            raise AnalysisError(f"Il motore neurale non ha prodotto un risultato: {detail}")
    result = result_from_payload(payload, duration)
    if progress:
        progress(1.0, "Analisi completata")
    return result
