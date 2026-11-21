import pytest

from songstructurer.model import MIN_SEGMENT_LENGTH, Segment, Structure


def make():
    return Structure(
        100.0, [Segment(0, 30, "A", 0), Segment(30, 60, "B", 1), Segment(60, 100, "A", 0)]
    )


def contiguous(structure):
    segs = structure.segments
    assert segs[0].start == 0.0 and segs[-1].end == structure.duration
    assert all(a.end == b.start for a, b in zip(segs, segs[1:]))
    assert all(s.duration > 0 for s in segs)


def test_normalises_gaps_and_overlaps():
    s = Structure(50.0, [Segment(5, 20, "A"), Segment(18, 30, "B"), Segment(35, 40, "C")])
    contiguous(s)
    assert [x.label for x in s.segments] == ["A", "B", "C"]
    assert len(Structure(10.0)) == 1


def test_move_boundary_is_clamped():
    s = make()
    assert s.move_boundary(1, 45.0) == 45.0
    assert s.move_boundary(1, 500.0) == pytest.approx(60 - MIN_SEGMENT_LENGTH)
    assert s.move_boundary(1, -5.0) == pytest.approx(MIN_SEGMENT_LENGTH)
    contiguous(s)
    with pytest.raises(IndexError):
        s.move_boundary(0, 1.0)


def test_split_merge_undo_redo():
    s = make()
    s.checkpoint()
    assert s.split(10.0) == 1
    assert s.split(10.1) is None
    contiguous(s)
    assert len(s) == 4
    s.checkpoint()
    assert s.merge(0, 2, "X") == 0
    assert [x.label for x in s.segments] == ["X", "A"]
    assert s.undo() and len(s) == 4
    assert s.undo() and len(s) == 3
    assert not s.undo()
    assert s.redo() and s.redo() and not s.redo()
    assert len(s) == 2


def test_rename_whole_group():
    s = make()
    s.rename(0, "Verse", whole_group=True)
    assert [x.label for x in s.segments] == ["Verse", "B", "Verse"]
    s.rename(2, "Outro")
    assert s.labels() == ["Verse", "B", "Outro"]
    with pytest.raises(ValueError):
        s.rename(0, "  ")


def test_lookup():
    s = make()
    assert s.index_at(-1) == 0 and s.index_at(30) == 1 and s.index_at(1e9) == 2
    assert s.boundary_near(30.4, 0.5) == 1
    assert s.boundary_near(33, 0.5) is None
    assert s.boundary_near(0.0, 0.5) is None


def test_replace_all_is_undoable():
    s = make()
    s.replace_all([Segment(0, 100, "Z")])
    assert len(s) == 1
    s.undo()
    assert len(s) == 3
