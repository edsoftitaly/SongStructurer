"""Export of a structure to CSV, JSON and Audacity label tracks."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from . import __version__
from .model import Structure

EXPORT_FORMATS = {
    ".csv": "CSV",
    ".json": "JSON",
    ".txt": "Etichette Audacity",
}


def format_timestamp(seconds: float, decimals: int = 3) -> str:
    """``75.5`` -> ``"01:15.500"`` (``decimals=0`` -> ``"01:15"``)."""
    seconds = max(0.0, float(seconds))
    scale = 10**decimals
    total = int(round(seconds * scale))
    whole, fraction = divmod(total, scale)
    minutes, secs = divmod(whole, 60)
    text = f"{minutes:02d}:{secs:02d}"
    return f"{text}.{fraction:0{decimals}d}" if decimals else text


def to_csv(structure: Structure) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["index", "start_s", "end_s", "duration_s", "start", "end", "label"])
    for index, seg in enumerate(structure.segments, start=1):
        writer.writerow(
            [
                index,
                f"{seg.start:.3f}",
                f"{seg.end:.3f}",
                f"{seg.duration:.3f}",
                format_timestamp(seg.start),
                format_timestamp(seg.end),
                seg.label,
            ]
        )
    return buffer.getvalue()


def to_json(structure: Structure, metadata: dict | None = None) -> str:
    payload = {
        "generator": f"SongStructurer {__version__}",
        **(metadata or {}),
        "duration": round(structure.duration, 3),
        "segments": [
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "label": seg.label,
                "group": seg.group,
            }
            for seg in structure.segments
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def to_audacity_labels(structure: Structure) -> str:
    """Tab-separated ``start<TAB>end<TAB>label`` lines, times in seconds."""
    lines = []
    for seg in structure.segments:
        label = seg.label.replace("\t", " ").replace("\n", " ")
        lines.append(f"{seg.start:.6f}\t{seg.end:.6f}\t{label}")
    return "\n".join(lines) + "\n"


def write_export(path: str | Path, structure: Structure, metadata: dict | None = None) -> Path:
    """Write ``structure`` in the format implied by the extension of ``path``."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = to_csv(structure)
    elif suffix == ".json":
        text = to_json(structure, metadata)
    elif suffix == ".txt":
        text = to_audacity_labels(structure)
    else:
        raise ValueError(f"Formato di esportazione non supportato: {suffix or path.name}")
    # utf-8-sig keeps accented labels intact when the CSV is opened in Excel.
    encoding = "utf-8-sig" if suffix == ".csv" else "utf-8"
    path.write_text(text, encoding=encoding, newline="")
    return path
