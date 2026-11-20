"""End-to-end test of the window; skipped where no display is available."""

import time

import numpy as np
import pytest
import soundfile as sf

tk = pytest.importorskip("tkinter")

from songstructurer.player import Player  # noqa: E402
from tests.test_export_audio_player import FakeBackend  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def app():
    try:
        from songstructurer.app import App

        window = App(player=Player(backend=FakeBackend()))
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    yield window
    if not window._closing:
        window.quit_app()


def pump(app, condition, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("timeout")


def test_open_analyze_edit_export(app, song, tmp_path):
    signal, sr, _ = song
    source = tmp_path / "song.wav"
    sf.write(source, signal, sr)

    app.open_file(source)
    pump(app, lambda: app.structure is not None and len(app.structure) > 1 and not app._busy)
    assert len(app.structure) == 4
    assert len(app.tree.get_children()) == 4
    assert "BPM" in app.info.get()

    app.seek(8.0)
    app.split_at_playhead()
    assert len(app.structure) == 5
    app.undo()
    assert len(app.structure) == 4
    app.select([0, 1])
    app.merge_selected()
    assert len(app.structure) == 3

    app.zoom(4.0, around=30.0)
    start, end = app.view
    assert end - start == pytest.approx(app.audio.duration / 4.0)
    app.zoom_all()
    assert app.view == (0.0, pytest.approx(app.audio.duration))

    app.seek(10.0)
    app.toggle_play()
    assert app.player.playing
    app.player._callback(np.zeros((2048, 1), dtype=np.float32), 2048, None, None)
    pump(app, lambda: app.playhead_time > 10.0, timeout=5)
    app.toggle_play()
    assert not app.player.playing

    app.analyze()
    pump(app, lambda: not app._busy and len(app.structure) == 4)
    app.undo()  # a re-analysis can be undone
    assert len(app.structure) == 3


def test_bad_file_reports_error(app, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(
        "songstructurer.app.messagebox.showerror", lambda *args, **kwargs: shown.append(args)
    )
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"nope")
    app.open_file(bad)
    pump(app, lambda: bool(shown), timeout=30)
    assert not app._busy and app.audio is None
