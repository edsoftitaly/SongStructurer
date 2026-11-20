"""Minimal Standard MIDI File writer (format 1) for transcribed notes."""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

TICKS_PER_BEAT = 480


@dataclass(frozen=True)
class Note:
    start: float
    end: float
    pitch: int
    velocity: int = 90


def _varlen(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _chunk(data: bytes) -> bytes:
    return b"MTrk" + struct.pack(">I", len(data)) + data


def _meta(kind: int, payload: bytes) -> bytes:
    return b"\x00\xff" + bytes([kind]) + _varlen(len(payload)) + payload


def midi_bytes(tracks: Sequence[tuple[str, Sequence[Note]]], bpm: float = 120.0) -> bytes:
    """Encode ``[(track name, notes), ...]``; times are in seconds."""
    bpm = float(bpm) if bpm and bpm > 0 else 120.0
    ticks_per_second = TICKS_PER_BEAT * bpm / 60.0
    tempo = int(round(60_000_000 / bpm))
    conductor = _meta(0x51, struct.pack(">I", tempo)[1:]) + b"\x00\xff\x2f\x00"
    chunks = [_chunk(conductor)]
    for channel, (name, notes) in enumerate(tracks):
        channel = min(channel, 15)
        events: list[tuple[int, int, bytes]] = []
        for note in notes:
            pitch = min(max(int(note.pitch), 0), 127)
            velocity = min(max(int(note.velocity), 1), 127)
            on = int(round(max(note.start, 0.0) * ticks_per_second))
            off = max(on + 1, int(round(max(note.end, 0.0) * ticks_per_second)))
            events.append((on, 1, bytes([0x90 | channel, pitch, velocity])))
            events.append((off, 0, bytes([0x80 | channel, pitch, 0])))
        events.sort(key=lambda e: (e[0], e[1]))  # note-offs first on ties
        data = _meta(0x03, name.encode("utf-8"))
        clock = 0
        for tick, _order, message in events:
            data += _varlen(tick - clock) + message
            clock = tick
        data += b"\x00\xff\x2f\x00"
        chunks.append(_chunk(data))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), TICKS_PER_BEAT)
    return header + b"".join(chunks)


def write_midi(
    path: str | Path, tracks: Sequence[tuple[str, Sequence[Note]]], bpm: float = 120.0
) -> Path:
    path = Path(path)
    path.write_bytes(midi_bytes(tracks, bpm))
    return path
