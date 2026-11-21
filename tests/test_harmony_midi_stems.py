import struct
import sys

import numpy as np
import pytest
import soundfile as sf

from songstructurer.audio import load_audio
from songstructurer.export import chords_to_labels
from songstructurer.harmony import (
    Chord,
    analyze_harmony,
    chord_templates,
    decode_chords,
    merge_chords,
)
from songstructurer.midi import Note, midi_bytes, write_midi
from songstructurer.pipeline import export_midi, full_analysis
from songstructurer.stems import StemError, separate
from songstructurer.transcribe import notes_from_pitch, transcribe

SR = 22050
A4 = 440.0


def hz(midi):
    return A4 * 2 ** ((midi - 69) / 12)


def tone(midi, seconds, harmonics=4):
    t = np.arange(int(seconds * SR)) / SR
    wave = sum(np.sin(2 * np.pi * hz(midi) * (k + 1) * t) / (k + 1) for k in range(harmonics))
    fade = np.minimum(1.0, np.minimum(t * 50, (seconds - t) * 50))
    return (0.4 * wave * fade).astype(np.float32)


def chord(midis, seconds):
    return sum(tone(m, seconds) for m in midis) / len(midis)


def test_templates_and_decoding():
    names, templates = chord_templates()
    assert len(names) == 36 and {"C", "Am", "E5"} <= set(names)
    assert np.allclose(np.linalg.norm(templates, axis=1), 1.0)
    chroma = np.zeros((12, 6))
    chroma[[0, 4, 7], :3] = 1.0  # C major
    chroma[[9, 0, 4], 3:5] = 1.0  # A minor
    assert decode_chords(chroma) == ["C", "C", "C", "Am", "Am", "N"]
    # One noisy frame inside a held chord does not create a new chord.
    chroma = np.zeros((12, 7))
    chroma[[0, 4, 7], :] = 1.0
    chroma[:, 3] += 0.35
    assert set(decode_chords(chroma)) == {"C"}


def test_merge_chords():
    merged = merge_chords(["C", "C", "G", "N", "N"], [0, 1, 2, 3, 4, 5])
    assert merged == [Chord(0.0, 2.0, "C"), Chord(2.0, 3.0, "G"), Chord(3.0, 5.0, "N")]
    assert chords_to_labels(merged) == "0.000000\t2.000000\tC\n2.000000\t3.000000\tG\n"


def test_analyze_harmony_on_synthetic_progression():
    progression = [
        ([48, 52, 55, 60], "C"),
        ([45, 48, 52, 57], "Am"),
        ([41, 45, 48, 53], "F"),
        ([43, 47, 50, 55], "G"),
        ([40, 47, 52], "E5"),
    ]
    signal = np.concatenate([chord(m, 2.0) for m, _ in progression])
    key, chords = analyze_harmony(signal, SR, np.arange(0.5, 10.0, 0.5))
    assert [c.name for c in chords] == [name for _, name in progression]
    assert [round(c.start) for c in chords] == [0, 2, 4, 6, 8]
    assert key in ("C", "Am")
    assert analyze_harmony(np.zeros(SR, dtype=np.float32), SR, []) == ("", [])


def test_notes_from_pitch_bridges_gaps_and_drops_blips():
    frame = 0.01
    pitch = np.array([60.2] * 20 + [0] * 3 + [59.9] * 20 + [64.0] * 3 + [0] * 10 + [62.0] * 30)
    voiced = pitch > 0
    notes = notes_from_pitch(pitch, voiced, np.full(len(pitch), -6.0), frame)
    assert [(n.pitch, round(n.start, 2), round(n.end, 2)) for n in notes] == [
        (60, 0.0, 0.43),
        (62, 0.56, 0.86),
    ]
    assert all(30 <= n.velocity <= 120 for n in notes)


def test_transcribe_bass_and_voice():
    line = [40, 43, 45, 40]  # E2 G2 A2 E2
    gap = np.zeros(int(0.1 * SR), dtype=np.float32)
    bass = np.concatenate([np.concatenate([tone(m, 0.4, 6), gap]) for m in line])
    assert [n.pitch for n in transcribe(bass, SR, "bass")] == line
    melody = [57, 60, 64, 62]
    voice = np.concatenate([tone(m, 0.5, 3) for m in melody])
    notes = transcribe(voice, SR, "vocals")
    assert [n.pitch for n in notes] == melody
    assert notes[1].start == pytest.approx(0.5, abs=0.06)
    assert transcribe(np.zeros(SR, dtype=np.float32), SR, "bass") == []


def parse_midi(data):
    """Tiny reader: returns (format, ticks, [[(tick, status, d1, d2)...] per track])."""
    assert data[:4] == b"MThd"
    _length, fmt, count, ticks = struct.unpack(">IHHH", data[4:14])
    pos, tracks = 14, []
    for _ in range(count):
        assert data[pos : pos + 4] == b"MTrk"
        size = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        body, pos = data[pos + 8 : pos + 8 + size], pos + 8 + size
        i, clock, events = 0, 0, []
        while i < len(body):
            delta = 0
            while True:
                byte = body[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if not byte & 0x80:
                    break
            clock += delta
            status = body[i]
            if status == 0xFF:
                size = body[i + 2]
                events.append((clock, status, body[i + 1], bytes(body[i + 3 : i + 3 + size])))
                i += 3 + size
            else:
                events.append((clock, status, body[i + 1], body[i + 2]))
                i += 3
        tracks.append(events)
    return fmt, ticks, tracks


def test_midi_file_structure(tmp_path):
    notes = [Note(0.0, 0.5, 60, 100), Note(0.5, 1.0, 62, 80), Note(1.0, 3.0, 200, 500)]
    data = midi_bytes([("Melody", notes), ("Bass", [Note(0.0, 1.0, 40)])], bpm=120)
    fmt, ticks, tracks = parse_midi(data)
    assert (fmt, ticks, len(tracks)) == (1, 480, 3)
    tempo = next(e for e in tracks[0] if e[1] == 0xFF and e[2] == 0x51)
    assert int.from_bytes(tempo[3], "big") == 500_000
    melody = [e for e in tracks[1] if e[1] in (0x90, 0x80)]
    # At 120 BPM half a second is one beat: 480 ticks. Note-off precedes note-on on ties.
    assert melody[:4] == [(0, 0x90, 60, 100), (480, 0x80, 60, 0), (480, 0x90, 62, 80),
                          (960, 0x80, 62, 0)]  # fmt: skip
    assert melody[4] == (960, 0x90, 127, 127)  # clamped
    assert [e for e in tracks[2] if e[1] == 0x91] == [(0, 0x91, 40, 90)]
    assert all(track[-1][1:3] == (0xFF, 0x2F) for track in tracks)
    assert write_midi(tmp_path / "x.mid", [("A", notes)], bpm=0).read_bytes()[:4] == b"MThd"


FAKE_DEMUCS = """
import sys
from pathlib import Path
import numpy as np, soundfile as sf

def tone(midi, seconds, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    return (0.4 * np.sin(2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t)).astype("float32")

args = sys.argv[1:]
model, out, track = args[args.index("-n") + 1], Path(args[args.index("-o") + 1]), Path(args[-1])
if "explode" in track.name:
    sys.exit("CUDA out of memory")
folder = out / model / track.stem
folder.mkdir(parents=True)
names = ["drums", "bass", "other", "vocals"] + (["guitar", "piano"] if model.endswith("6s") else [])
for name in names:
    midi = {"bass": 40, "vocals": 64}.get(name, 69)
    sf.write(folder / f"{name}.wav", np.concatenate([tone(midi, 0.5), tone(midi + 2, 0.5)]), 22050)
"""


@pytest.fixture
def fake_demucs(tmp_path, monkeypatch):
    package = tmp_path / "site" / "demucs"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(FAKE_DEMUCS, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))
    return tmp_path


def test_separate_runs_demucs_and_collects_stems(fake_demucs):
    song = fake_demucs / "My Song.wav"
    sf.write(song, tone(60, 1.0), SR)
    stems = separate(song, fake_demucs / "out", sys.executable, model="htdemucs_6s")
    assert sorted(stems) == ["bass", "drums", "guitar", "other", "piano", "vocals"]
    assert stems["vocals"].name == "My Song - vocals.wav" and stems["vocals"].is_file()

    bad = fake_demucs / "explode.wav"
    sf.write(bad, tone(60, 0.2), SR)
    with pytest.raises(StemError, match="out of memory"):
        separate(bad, fake_demucs / "out2", sys.executable)
    with pytest.raises(StemError):
        separate(song, fake_demucs / "out3", str(fake_demucs / "missing-python"))


def test_export_midi_end_to_end(fake_demucs):
    song = fake_demucs / "song.wav"
    sf.write(song, tone(60, 1.0), SR)
    audio = load_audio(song)
    with pytest.raises(StemError):
        export_midi(fake_demucs / "no.mid", audio, 120.0, python=None)

    path, counts = export_midi(fake_demucs / "song.mid", audio, 100.0, sys.executable)
    assert counts == {"Melody": 2, "Bass": 2}
    _fmt, _ticks, tracks = parse_midi(path.read_bytes())
    assert [e[2] for e in tracks[1] if e[1] == 0x90] == [64, 66]
    assert [e[2] for e in tracks[2] if e[1] == 0x91] == [40, 42]

    # Stems separated earlier are reused: no interpreter needed.
    stems = separate(song, fake_demucs / "stems", sys.executable)
    _path, counts = export_midi(fake_demucs / "again.mid", audio, 100.0, None, stems)
    assert counts == {"Melody": 2, "Bass": 2}


def test_full_analysis_adds_chords(song, tmp_path):
    signal, sr, _ = song
    source = tmp_path / "s.wav"
    sf.write(source, signal, sr)
    seen = []
    result = full_analysis(load_audio(source), progress=lambda f, m: seen.append(f))
    assert result.engine == "classic" and len(result.sections) == 4
    assert result.chords and result.chords[0].start == 0.0
    assert result.chords[-1].end == pytest.approx(len(signal) / sr)
    assert seen == sorted(seen) and seen[-1] == 1.0
