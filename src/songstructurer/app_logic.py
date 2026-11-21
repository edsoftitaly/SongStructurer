"""Bits of application logic that do not need a window."""

from __future__ import annotations

from .model import Structure


def click_boundaries(structure: Structure) -> list[float]:
    """Section changes worth announcing: not the start, not into silence."""
    return [
        seg.start
        for seg in structure.segments[1:]
        if seg.start > 0.05 and seg.label.strip().lower() not in ("silence", "silenzio")
    ]
