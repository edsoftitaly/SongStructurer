import json
import os
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf

from songstructurer import sonify
from songstructurer.analysis import SILENCE_GROUP, AnalysisError
from songstructurer.app_logic import click_boundaries
from songstructurer.model import Segment, Structure
from songstructurer.neural import (
    analyze_neural,
    check_python,
    find_python,
    result_from_payload,
    worker_path,
)
from songstructurer.settings import load_settings, save_settings

PAYLOAD = {
    "bpm": 120,
    "beats": [0.5, 1.0, 1.5, 2.0, 99.0],
    "downbeats": [0.5, 2.0],
    "segments": [
        {"start": 0.0, "end": 0.4, "label": "start"},
        {"start": 0.4, "end": 10.0, "label": "intro"},
        {"start": 10.0, "end": 20.0, "label": "verse"},
        {"start": 20.0, "end": 30.0, "label": "chorus"},
        {"start": 30.0, "end": 40.0, "label": "verse"},
        {"start": 40.0, "end": 41.0, "label": "end"},
    ],
}

FAKE_ALLIN1 = """
__version__ = "0.0-fake"
import json, os
from types import SimpleNamespace

def analyze(path, **options):
    if os.environ.get("FAKE_ALLIN1_FAIL"):
        raise RuntimeError("model exploded")
    data = json.loads(os.environ["FAKE_ALLIN1_PAYLOAD"])
    assert options["multiprocess"] is False
    return SimpleNamespace(
        bpm=data["bpm"], beats=data["beats"], downbeats=data["downbeats"],
        segments=[SimpleNamespace(**s) for s in data["segments"]],
    )
"""


def test_payload_becomes_contiguous_result():
    result = result_from_payload(PAYLOAD, duration=42.0)
    assert result.engine == "neural" and result.tempo == 120
    assert [s.label for s in result.sections] == [
        "Silence", "Intro", "Verse", "Chorus", "Verse", "Silence",
    ]  # fmt: skip
    assert result.sections[0].start == 0.0 and result.sections[-1].end == 42.0
    assert all(a.end == b.start for a, b in zip(result.sections, result.sections[1:]))
    groups = [s.group for s in result.sections]
    assert groups[0] == groups[-1] == SILENCE_GROUP and groups[2] == groups[4] != groups[3]
    assert result.beat_times == [0.5, 1.0, 1.5, 2.0]  # 99.0 is past the end
    assert result.downbeat_times == [0.5, 2.0]
    with pytest.raises(AnalysisError):
        result_from_payload({"error": "boom"}, 10.0)
    with pytest.raises(AnalysisError):
        result_from_payload({"segments": []}, 10.0)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """An interpreter in which ``import allin1`` finds a stand-in module."""
    package = tmp_path / "site"
    package.mkdir()
    (package / "allin1.py").write_text(FAKE_ALLIN1, encoding="utf-8")
    (package / "torch.py").write_text('__version__ = "0.0-fake"\n', encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(package))
    monkeypatch.setenv("FAKE_ALLIN1_PAYLOAD", json.dumps(PAYLOAD))
    return tmp_path


def test_worker_runs_in_external_interpreter(fake_env, monkeypatch):
    assert worker_path().is_file()
    ok, detail = check_python(sys.executable)
    assert ok and "fake" in detail

    seen = []
    result = analyze_neural(
        fake_env / "song.wav", 42.0, sys.executable, progress=lambda f, m: seen.append(f)
    )
    assert len(result.sections) == 6 and seen[-1] == 1.0

    monkeypatch.setenv("FAKE_ALLIN1_FAIL", "1")
    with pytest.raises(AnalysisError, match="model exploded"):
        analyze_neural(fake_env / "song.wav", 42.0, sys.executable)


def test_missing_interpreter_and_missing_module(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    ok, detail = check_python(sys.executable)
    if ok:
        pytest.skip("allin1 is really installed here")
    assert detail
    assert check_python(str(tmp_path / "nope.exe"))[0] is False
    with pytest.raises(AnalysisError):
        analyze_neural(tmp_path / "x.wav", 1.0, str(tmp_path / "nope.exe"))
    monkeypatch.setenv("SONGSTRUCTURER_PYTHON", sys.executable)
    assert find_python("") == sys.executable
    assert find_python(str(tmp_path / "nope.exe")) == sys.executable


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "deep" / "settings.json"
    assert load_settings(path) == {"engine": "classic", "neural_python": ""}
    assert save_settings({"engine": "neural", "neural_python": "C:/py/python.exe"}, path)
    assert load_settings(path)["engine"] == "neural"
    path.write_text('{"engine": "quantum", "junk": 1}', encoding="utf-8")
    assert load_settings(path) == {"engine": "classic", "neural_python": ""}
    path.write_text("not json", encoding="utf-8")
    assert load_settings(path)["engine"] == "classic"


def test_riser_accelerates_towards_the_boundary():
    offsets = sonify.riser_offsets()
    assert len(offsets) == sonify.RISER_CLICKS
    assert offsets[0] == pytest.approx(-sonify.RISER_SECONDS) and offsets[-1] < 0
    gaps = np.diff(offsets)
    assert np.all(gaps > 0) and np.all(np.diff(gaps) < 0)  # closer and closer


def test_click_track_events():
    sr = 8000
    beats = [1.0, 1.5, 2.0, 2.5]
    track = sonify.click_track(sr * 12, sr, beats, downbeats=[1.0], boundaries=[8.0])

    def energy(start, seconds=0.05):
        chunk = track[int(start * sr) : int((start + seconds) * sr)]
        return float(np.sum(chunk**2))

    assert energy(1.5) > 1.0 and energy(1.0) > 1.0
    assert energy(0.2) == 0.0 and energy(3.2) == 0.0
    assert energy(8.0, 0.4) > energy(1.5)  # the drop
    assert energy(4.0) > 0.0 and energy(7.9, 0.1) > 0.0  # the riser
    # The downbeat click replaces the beat click instead of doubling it.
    assert np.max(np.abs(track[sr : sr + 400])) <= 1.0 + 1e-6


def test_sonify_mix_and_files(tmp_path):
    sr = 8000
    stereo = np.full((sr * 3, 2), 0.9, dtype=np.float32)
    mixed = sonify.sonify(stereo, sr, [1.0], boundaries=[2.0])
    assert mixed.shape == stereo.shape and mixed.max() <= 1.0 and mixed.min() >= -1.0
    assert not np.allclose(mixed[sr : sr + 100], 0.9)
    for name in ("c.wav", "c.flac", "c.mp3"):
        info = sf.info(str(sonify.write_click_track(tmp_path / name, mixed, sr)))
        assert info.channels == 2 and info.duration == pytest.approx(3.0, abs=0.1)
    with pytest.raises(ValueError):
        sonify.write_click_track(tmp_path / "c.xyz", mixed, sr)


def test_click_boundaries_skip_start_and_silence():
    structure = Structure(
        30.0,
        [Segment(0, 1, "Silence"), Segment(1, 10, "Intro"), Segment(10, 28, "Verse"),
         Segment(28, 30, "Silence")],
    )  # fmt: skip
    assert click_boundaries(structure) == [1.0, 10.0]


def test_command_line_click(song, tmp_path):
    signal, sr, _ = song
    source = tmp_path / "s.wav"
    sf.write(source, signal, sr)
    out = tmp_path / "s.click.wav"
    env = {**os.environ, "PYTHONPATH": ""}
    done = subprocess.run(
        [sys.executable, "-m", "songstructurer", "click", str(source), "-o", str(out)],
        capture_output=True, text=True, env=env,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    mixed, _ = sf.read(out)
    assert len(mixed) == len(signal) and not np.allclose(mixed, signal, atol=1e-3)
