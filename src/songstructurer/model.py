"""Editable song structure: contiguous, labelled segments with undo."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

#: Segments can never be made shorter than this by editing (seconds).
MIN_SEGMENT_LENGTH = 0.25


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    label: str
    group: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start


class Structure:
    """Segments that always tile ``[0, duration]`` without gaps or overlaps.

    Version 1 stored independent ``[start, end]`` pairs and kept them apart
    with 10 ms "safety margins", which left holes in the timeline. Here two
    neighbours share one boundary by construction.
    """

    def __init__(self, duration: float, segments: Iterable[Segment] | None = None):
        if duration <= 0:
            raise ValueError("duration must be positive")
        self.duration = float(duration)
        items = sorted(segments or [], key=lambda s: s.start)
        self._segments: list[Segment] = self._normalise(items)
        self._undo: list[list[Segment]] = []
        self._redo: list[list[Segment]] = []

    def _normalise(self, items: list[Segment]) -> list[Segment]:
        if not items:
            return [Segment(0.0, self.duration, "Section A", 0)]
        out: list[Segment] = []
        cursor = 0.0
        for index, seg in enumerate(items):
            last = index == len(items) - 1
            end = self.duration if last else min(max(seg.end, cursor), self.duration)
            if end - cursor <= 1e-9:
                continue
            out.append(replace(seg, start=cursor, end=end))
            cursor = end
        if not out:
            return [Segment(0.0, self.duration, items[0].label, items[0].group)]
        if out[-1].end < self.duration:
            out[-1] = replace(out[-1], end=self.duration)
        return out

    # ---------------------------------------------------------------- access

    @property
    def segments(self) -> tuple[Segment, ...]:
        return tuple(self._segments)

    def __len__(self) -> int:
        return len(self._segments)

    def __getitem__(self, index: int) -> Segment:
        return self._segments[index]

    def labels(self) -> list[str]:
        """Distinct labels in order of first appearance."""
        seen: dict[str, None] = {}
        for seg in self._segments:
            seen.setdefault(seg.label, None)
        return list(seen)

    def index_at(self, time: float) -> int:
        """Index of the segment containing ``time`` (clamped to the song)."""
        time = min(max(time, 0.0), self.duration)
        for index, seg in enumerate(self._segments):
            if time < seg.end:
                return index
        return len(self._segments) - 1

    def boundary_near(self, time: float, tolerance: float) -> int | None:
        """Index ``i`` of the boundary between segments ``i-1`` and ``i``."""
        best = None
        best_distance = tolerance
        for index in range(1, len(self._segments)):
            distance = abs(self._segments[index].start - time)
            if distance <= best_distance:
                best, best_distance = index, distance
        return best

    # ------------------------------------------------------------------ undo

    def checkpoint(self) -> None:
        """Remember the current state; call before a (group of) edit(s)."""
        self._undo.append(list(self._segments))
        del self._undo[:-200]
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(list(self._segments))
        self._segments = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(list(self._segments))
        self._segments = self._redo.pop()
        return True

    # ----------------------------------------------------------------- edits

    def replace_all(self, segments: Iterable[Segment]) -> None:
        """Replace every segment (undoable), e.g. after a new analysis."""
        self.checkpoint()
        self._segments = self._normalise(sorted(segments, key=lambda s: s.start))

    def move_boundary(self, index: int, time: float) -> float:
        """Move the boundary before segment ``index``; returns where it landed."""
        if not 1 <= index < len(self._segments):
            raise IndexError("no such boundary")
        left, right = self._segments[index - 1], self._segments[index]
        low = left.start + MIN_SEGMENT_LENGTH
        high = right.end - MIN_SEGMENT_LENGTH
        if low > high:
            return right.start
        time = min(max(time, low), high)
        self._segments[index - 1] = replace(left, end=time)
        self._segments[index] = replace(right, start=time)
        return time

    def split(self, time: float) -> int | None:
        """Split the segment at ``time``; returns the index of the new half."""
        index = self.index_at(time)
        seg = self._segments[index]
        if time - seg.start < MIN_SEGMENT_LENGTH or seg.end - time < MIN_SEGMENT_LENGTH:
            return None
        self._segments[index : index + 1] = [replace(seg, end=time), replace(seg, start=time)]
        return index + 1

    def merge(self, first: int, last: int, label: str | None = None) -> int:
        """Merge segments ``first..last`` (inclusive) into one."""
        if not 0 <= first < last < len(self._segments):
            raise IndexError("invalid merge range")
        head = self._segments[first]
        merged = Segment(head.start, self._segments[last].end, label or head.label, head.group)
        self._segments[first : last + 1] = [merged]
        return first

    def remove_boundary(self, index: int) -> int:
        """Delete the boundary before segment ``index`` (merge with previous)."""
        return self.merge(index - 1, index)

    def rename(self, index: int, label: str, whole_group: bool = False) -> None:
        label = label.strip()
        if not label:
            raise ValueError("empty label")
        target = self._segments[index]
        for i, seg in enumerate(self._segments):
            same = i == index or (
                whole_group and seg.group == target.group and seg.label == target.label
            )
            if same:
                self._segments[i] = replace(seg, label=label)
