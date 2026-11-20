import numpy as np
import pytest

from songstructurer import analysis
from songstructurer.analysis import (
    LABEL_CHORUS,
    LABEL_INTRO,
    LABEL_OUTRO,
    LABEL_PRE_CHORUS,
    LABEL_SILENCE,
    LABEL_VERSE,
    SILENCE_GROUP,
    assign_labels,
)


def test_centered_stack_has_no_delay():
    x = np.zeros((1, 9))
    x[0, 4] = 1.0
    stacked = analysis.centered_stack(x, 3)
    assert stacked.shape == (3, 9)
    # The impulse must spread symmetrically around column 4.
    assert np.flatnonzero(stacked.sum(axis=0)).tolist() == [3, 4, 5]


def test_novelty_peaks_at_block_change():
    features = np.zeros((2, 60))
    features[0, :30] = 1.0
    features[1, 30:] = 1.0
    novelty = analysis.novelty_curve(analysis.self_similarity(features), 8)
    assert abs(int(np.argmax(novelty)) - 30) <= 1
    assert novelty.min() >= 0.0 and novelty.max() == pytest.approx(1.0)


def test_cluster_sections_groups_repetitions():
    sim = np.array(
        [
            [1.0, 0.1, 0.9, 0.1],
            [0.1, 1.0, 0.1, 0.8],
            [0.9, 0.1, 1.0, 0.1],
            [0.1, 0.8, 0.1, 1.0],
        ]
    )
    assert analysis.cluster_sections(sim, 0.4) == [0, 1, 0, 1]
    assert analysis.cluster_sections(np.ones((1, 1)), 0.4) == [0]


def test_section_letter():
    assert [analysis.section_letter(i) for i in (0, 1, 25, 26)] == ["A", "B", "Z", "AA"]


def test_labels_for_pop_form():
    # intro, verse, pre, chorus, verse, pre, chorus, bridge, chorus, outro
    groups = [0, 1, 2, 3, 1, 2, 3, 4, 3, 5]
    energy = [-20, -14, -12, -8, -14, -12, -8, -13, -8, -22]
    labels = assign_labels(groups, energy, [10, 20, 8, 20, 20, 8, 20, 15, 20, 10])
    assert labels[0] == LABEL_INTRO
    assert labels[-1] == LABEL_OUTRO
    assert [labels[i] for i in (3, 6, 8)] == [LABEL_CHORUS] * 3
    assert [labels[i] for i in (1, 4)] == [LABEL_VERSE] * 2
    assert [labels[i] for i in (2, 5)] == [LABEL_PRE_CHORUS] * 2
    assert labels[7] == "Bridge"


def test_labels_without_repetition_and_with_silence():
    labels = assign_labels(
        [SILENCE_GROUP, 0, 1, 2, SILENCE_GROUP], [-80, -10, -10, -10, -80], [2, 10, 10, 10, 2]
    )
    assert labels == [LABEL_SILENCE, LABEL_INTRO, "Section A", LABEL_OUTRO, LABEL_SILENCE]


def test_estimate_key():
    c_major = np.zeros(12)
    c_major[[0, 2, 4, 5, 7, 9, 11]] = 1.0
    c_major[[0, 4, 7]] += 2.0
    assert analysis.estimate_key(c_major) == "C"
    assert analysis.estimate_key(np.zeros(12)) == ""


def test_analyze_synthetic_song(song):
    signal, sr, expected = song
    seen = []
    result = analysis.analyze(signal, sr, progress=lambda f, m: seen.append(f))
    starts = [s.start for s in result.sections]
    assert starts[0] == 0.0
    assert result.sections[-1].end == pytest.approx(len(signal) / sr)
    for a, b in zip(result.sections, result.sections[1:]):
        assert a.end == pytest.approx(b.start)
    for boundary in expected:
        assert min(abs(boundary - s) for s in starts[1:]) <= 1.0
    assert len(result.sections) == 4
    groups = [s.group for s in result.sections]
    assert groups[0] == groups[2] and groups[1] == groups[3] and groups[0] != groups[1]
    assert 100 <= result.tempo <= 130
    assert seen == sorted(seen) and seen[-1] == 1.0


def test_analyze_handles_silence_and_stereo(song):
    signal, sr, _ = song
    silent = analysis.analyze(np.zeros(sr * 20, dtype=np.float32), sr)
    assert [s.label for s in silent.sections] == [LABEL_SILENCE]

    padded = np.concatenate([np.zeros(3 * sr, dtype=np.float32), signal])
    stereo = np.stack([padded, padded], axis=1)
    result = analysis.analyze(stereo, sr)
    assert result.sections[0].label == LABEL_SILENCE
    assert result.sections[0].end == pytest.approx(3.0, abs=0.6)


def test_analyze_short_and_empty():
    sr = 22050
    short = analysis.analyze(0.1 * np.ones(sr * 2, dtype=np.float32), sr)
    assert len(short.sections) == 1
    with pytest.raises(analysis.AnalysisError):
        analysis.analyze(np.zeros(0, dtype=np.float32), sr)
