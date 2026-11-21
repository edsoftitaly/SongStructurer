import csv
import io
import json

import numpy as np
import pytest
import soundfile as sf

from songstructurer.audio import AudioLoadError, WaveformEnvelope, load_audio
from songstructurer.export import (
    format_timestamp,
    to_audacity_labels,
    to_csv,
    to_json,
    write_export,
)
from songstructurer.model import Segment, Structure
from songstructurer.player import PlaybackError, Player
from songstructurer.render import label_colors, render_png


def structure():
    return Structure(90.5, [Segment(0, 15.25, "Intro", 0), Segment(15.25, 90.5, "Strofa è", 1)])


def test_format_timestamp():
    assert format_timestamp(75.5) == "01:15.500"
    assert format_timestamp(59.9996) == "01:00.000"
    assert format_timestamp(3725, decimals=0) == "62:05"
    assert format_timestamp(-1) == "00:00.000"


def test_csv_keeps_millisecond_precision():
    rows = list(csv.DictReader(io.StringIO(to_csv(structure()))))
    assert rows[0]["end_s"] == "15.250" and rows[1]["start"] == "00:15.250"
    assert rows[1]["label"] == "Strofa è"


def test_json_and_audacity():
    data = json.loads(to_json(structure(), {"file": "x.mp3"}))
    assert data["file"] == "x.mp3" and len(data["segments"]) == 2
    lines = to_audacity_labels(structure()).splitlines()
    assert lines[1] == "15.250000\t90.500000\tStrofa è"


def test_write_export(tmp_path):
    for name in ("a.csv", "a.json", "a.txt"):
        assert write_export(tmp_path / name, structure()).stat().st_size > 0
    assert (tmp_path / "a.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(ValueError):
        write_export(tmp_path / "a.xyz", structure())


def test_load_audio_roundtrip(tmp_path):
    sr = 8000
    t = np.arange(sr) / sr
    stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.zeros(sr)], axis=1).astype(np.float32)
    path = tmp_path / "tone.wav"
    sf.write(path, stereo, sr)
    audio = load_audio(path)
    assert (audio.sr, audio.channels, audio.n_samples) == (sr, 2, sr)
    assert audio.mono().shape == (sr,)
    with pytest.raises(AudioLoadError):
        load_audio(tmp_path / "missing.wav")
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(AudioLoadError):
        load_audio(bad)


def test_envelope_keeps_peaks():
    sr = 1000
    mono = np.zeros(100 * sr, dtype=np.float32)
    mono[50_500] = 0.9
    mono[20_250] = -0.7
    env = WaveformEnvelope(mono, sr)
    # A plain average (version 1) would flatten both peaks to about zero.
    for view, columns in (((0, 100), 300), ((50, 51), 300), ((20.2, 20.3), 50)):
        times, low, high = env.view(*view, columns)
        assert len(times) == len(low) == len(high) <= columns
        assert np.all(low <= high)
    _, low, high = env.view(0, 100, 300)
    assert high.max() == pytest.approx(0.9) and low.min() == pytest.approx(-0.7)
    assert len(env.view(5, 5, 10)[0]) == 0


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def close(self):
        self.running = False


class FakeBackend:
    OutputStream = FakeStream


def pull(player, frames):
    out = np.full((frames, 1), 7.0, dtype=np.float32)
    player._callback(out, frames, None, None)
    return out[:, 0]


def test_player_position_seek_and_range():
    sr = 1000
    samples = np.arange(5000, dtype=np.float32) / 5000
    player = Player(backend=FakeBackend())
    player.load(samples, sr)
    assert player.duration == 5.0 and not player.playing

    player.play(start=1.0, end=1.5)
    assert player.playing
    np.testing.assert_allclose(pull(player, 300), samples[1000:1300])
    assert player.position == pytest.approx(1.3)
    tail = pull(player, 300)
    np.testing.assert_allclose(tail[:200], samples[1300:1500])
    assert np.all(tail[200:] == 0.0)
    assert not player.playing and player.position == pytest.approx(1.5)

    player.seek(4.9)
    player.play()
    pull(player, 200)
    assert not player.playing and player.position == pytest.approx(5.0)
    player.play()  # at the end: starts over
    assert player.playing and player.position == 0.0
    player.pause()
    assert np.all(pull(player, 10) == 0.0) and player.position == 0.0
    player.close()


def test_player_reports_device_errors():
    class Broken:
        def OutputStream(self, **_kwargs):  # noqa: N802
            raise RuntimeError("no device")

    player = Player(backend=Broken())
    player.load(np.zeros(100, dtype=np.float32), 1000)
    with pytest.raises(PlaybackError):
        player.play()
    assert not player.playing


def test_render_png(tmp_path):
    env = WaveformEnvelope(np.random.default_rng(0).uniform(-1, 1, 90_500).astype(np.float32), 1000)
    path = render_png(tmp_path / "s.png", env, structure(), title="t", width_px=600, height_px=200)
    assert path.read_bytes().startswith(b"\x89PNG")
    colors = label_colors(["Intro", "Verse", "Intro", "Silence"])
    assert len(colors) == 3 and colors["Intro"] != colors["Verse"]
