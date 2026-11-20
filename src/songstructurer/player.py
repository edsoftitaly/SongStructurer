"""Audio playback from memory with exact position and real seeking.

Version 1 wrote every segment to a temporary WAV and played it through
``pygame.mixer.music``, whose seek does not work on WAV files and whose
position counter ignores seeks. Here the decoded samples are streamed straight
to the sound card, so the position is the index of the next sample to play.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np


class PlaybackError(Exception):
    """Raised when the audio device cannot be used."""


def _default_backend() -> Any:
    try:
        import sounddevice
    except Exception as exc:  # ImportError, or OSError when PortAudio is missing
        raise PlaybackError(f"Nessun dispositivo audio disponibile: {exc}") from exc
    return sounddevice


class Player:
    """Plays a ``(n, channels)`` float32 array through an output stream.

    ``backend`` only needs an ``OutputStream(samplerate, channels, dtype,
    callback)`` factory returning an object with ``start``, ``stop`` and
    ``close``; it defaults to :mod:`sounddevice` and is injectable for tests.
    """

    def __init__(self, backend: Any | None = None):
        self._backend = backend
        self._lock = threading.Lock()
        self._samples: np.ndarray | None = None
        self._sr = 0
        self._pos = 0
        self._end = 0
        self._playing = False
        self._stream: Any | None = None

    # ------------------------------------------------------------- lifecycle

    def load(self, samples: np.ndarray, sr: int) -> None:
        """Replace the audio. Any current playback is stopped."""
        self.close()
        data = np.ascontiguousarray(samples, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, np.newaxis]
        with self._lock:
            self._samples = data
            self._sr = int(sr)
            self._pos = 0
            self._end = len(data)

    def close(self) -> None:
        with self._lock:
            self._playing = False
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001 - nothing useful to do at teardown
                pass

    # -------------------------------------------------------------- transport

    @property
    def loaded(self) -> bool:
        return self._samples is not None

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        """Seconds from the start of the file."""
        return self._pos / self._sr if self._sr else 0.0

    @property
    def duration(self) -> float:
        return len(self._samples) / self._sr if self._samples is not None else 0.0

    def seek(self, seconds: float) -> None:
        if self._samples is None:
            return
        frame = int(round(seconds * self._sr))
        with self._lock:
            self._pos = min(max(frame, 0), len(self._samples))
            if self._pos >= self._end:
                self._end = len(self._samples)

    def play(self, start: float | None = None, end: float | None = None) -> None:
        """Play from ``start`` (default: current position) up to ``end``."""
        if self._samples is None:
            return
        total = len(self._samples)
        with self._lock:
            if start is not None:
                self._pos = min(max(int(round(start * self._sr)), 0), total)
            self._end = total if end is None else min(max(int(round(end * self._sr)), 0), total)
            if self._pos >= self._end:
                if start is not None or end is not None or total == 0:
                    return
                # Plain "play" at the end of the file starts over.
                self._pos = 0
            self._playing = True
        try:
            if self._stream is None:
                backend = self._backend or _default_backend()
                self._backend = backend
                self._stream = backend.OutputStream(
                    samplerate=self._sr,
                    channels=self._samples.shape[1],
                    dtype="float32",
                    callback=self._callback,
                )
            self._stream.start()
        except PlaybackError:
            self._playing = False
            raise
        except Exception as exc:
            self._playing = False
            self._stream = None
            raise PlaybackError(f"Impossibile avviare la riproduzione: {exc}") from exc

    def pause(self) -> None:
        with self._lock:
            self._playing = False
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:
                raise PlaybackError(f"Errore del dispositivo audio: {exc}") from exc

    def stop(self) -> None:
        """Pause and release the device."""
        self.close()

    # ---------------------------------------------------------------- stream

    def _callback(self, outdata: np.ndarray, frames: int, _time: Any, _status: Any) -> None:
        with self._lock:
            samples = self._samples
            count = 0
            if self._playing and samples is not None:
                count = max(0, min(frames, self._end - self._pos))
                outdata[:count] = samples[self._pos : self._pos + count]
                self._pos += count
                if count < frames:
                    self._playing = False
        outdata[count:] = 0.0
