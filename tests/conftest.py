import pytest

from songstructurer.__main__ import synthetic_song


@pytest.fixture(scope="session")
def song():
    """(signal, sr, expected boundaries) of a synthetic A B A B song."""
    return synthetic_song()
