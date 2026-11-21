"""Command line entry point.

songstructurer [FILE]                 open the editor (optionally on FILE)
songstructurer analyze FILE [-o OUT]  analyse without the GUI
songstructurer --selftest [REPORT]    check that the bundled engine works
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def synthetic_song(sr: int = 22050, seed: int = 0):
    """A 64 s test signal with a known A B A B form (16 s per section).

    Section A is a quiet C major arpeggio, section B a louder, brighter F#
    pattern with noise: enough contrast for the analysis to find the three
    boundaries. Used by ``--selftest`` and by the test-suite.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    beat = 0.5
    section_beats = 32

    def tone(freq: float, length: int, harmonics: int, amp: float):
        t = np.arange(length) / sr
        wave = sum(np.sin(2 * np.pi * freq * (h + 1) * t) / (h + 1) for h in range(harmonics))
        return amp * wave * np.exp(-3.0 * t)

    def section(notes: list[float], harmonics: int, amp: float, noise: float):
        n = int(beat * sr)
        out = []
        for index in range(section_beats):
            chunk = tone(notes[index % len(notes)], n, harmonics, amp)
            chunk[: n // 8] += noise * rng.standard_normal(n // 8) * np.linspace(1, 0, n // 8)
            out.append(chunk)
        return np.concatenate(out)

    part_a = [261.63, 329.63, 392.00, 329.63]
    part_b = [369.99, 466.16, 554.37, 739.99]
    parts = [
        section(part_a, 2, 0.25, 0.02),
        section(part_b, 8, 0.6, 0.25),
        section(part_a, 2, 0.25, 0.02),
        section(part_b, 8, 0.6, 0.25),
    ]
    signal = np.concatenate(parts).astype(np.float32)
    boundaries = [beat * section_beats * k for k in (1, 2, 3)]
    return signal / max(1.0, float(np.abs(signal).max())), sr, boundaries


def selftest(report_path: str | None) -> int:
    """Run the analysis on a synthetic song; exit code 0 means it works."""
    report: dict = {"version": __version__, "ok": False}
    try:
        from .analysis import analyze
        from .neural import worker_path
        from .sonify import sonify

        signal, sr, expected = synthetic_song()
        result = analyze(signal, sr)
        found = [round(s.start, 2) for s in result.sections[1:]]
        hits = [any(abs(b - e) <= 1.5 for b in found) for e in expected]
        groups = [s.group for s in result.sections]
        report.update(
            expected=expected,
            found=found,
            labels=[s.label for s in result.sections],
            tempo=result.tempo,
            neural_worker=worker_path().is_file(),
        )
        mixed = sonify(signal, sr, result.beat_times, boundaries=found)
        report["click_track"] = bool(mixed.shape[0] == len(signal))
        from .harmony import analyze_harmony
        from .transcribe import transcribe

        report["chords"] = len(analyze_harmony(signal, sr, result.beat_times)[1])
        report["notes"] = len(transcribe(signal[: 4 * sr], sr, "vocals"))
        report["ok"] = (
            all(hits)
            and len(found) <= 5
            and len(set(groups)) < len(groups)
            and report["neural_worker"]
            and report["click_track"]
            and report["chords"] > 0
            and report["notes"] > 0
        )
    except Exception as exc:  # noqa: BLE001 - the report must say what broke
        report["error"] = f"{type(exc).__name__}: {exc}"
    text = json.dumps(report, indent=2)
    if report_path:
        Path(report_path).write_text(text + "\n", encoding="utf-8")
    elif sys.stdout is not None:
        print(text)
    return 0 if report["ok"] else 1


def _python(engine: str, python: str | None, required: bool) -> str | None:
    from .neural import find_python
    from .settings import load_settings

    if engine != "neural" and not required:
        return None
    interpreter = find_python(python or load_settings()["neural_python"])
    if interpreter is None:
        raise SystemExit("Nessun Python con allin1/demucs. Usa --python o SONGSTRUCTURER_PYTHON.")
    return interpreter


def _analyze(source: str, engine: str, python: str | None):
    from .audio import load_audio
    from .pipeline import full_analysis

    audio = load_audio(source)
    return audio, full_analysis(audio, _python(engine, python, required=False))


def _structure(audio, result):
    from .model import Segment, Structure

    return Structure(
        audio.duration, [Segment(s.start, s.end, s.label, s.group) for s in result.sections]
    )


def analyze_command(source: str, output: str | None, engine: str, python: str | None) -> int:
    from .export import to_json, write_export

    audio, result = _analyze(source, engine, python)
    structure = _structure(audio, result)
    metadata = {
        "file": Path(source).name,
        "tempo_bpm": result.tempo,
        "key": result.key,
        "engine": result.engine,
        "chords": [
            {"start": round(c.start, 3), "end": round(c.end, 3), "name": c.name}
            for c in result.chords
        ],
    }
    if output:
        write_export(output, structure, metadata)
    elif sys.stdout is not None:
        sys.stdout.write(to_json(structure, metadata))
    return 0


def click_command(source: str, output: str, engine: str, python: str | None) -> int:
    from .app_logic import click_boundaries
    from .sonify import sonify, write_click_track

    audio, result = _analyze(source, engine, python)
    boundaries = click_boundaries(_structure(audio, result))
    mixed = sonify(audio.samples, audio.sr, result.beat_times, result.downbeat_times, boundaries)
    write_click_track(output, mixed, audio.sr)
    return 0


def stems_command(source: str, output: str, model: str, python: str | None) -> int:
    from .stems import separate

    stems = separate(source, output, _python("neural", python, required=True), model=model)
    if sys.stdout is not None:
        for name, path in stems.items():
            print(f"{name}\t{path}")
    return 0


def midi_command(source: str, output: str, engine: str, python: str | None) -> int:
    from .pipeline import export_midi

    audio, result = _analyze(source, engine, python)
    interpreter = _python("neural", python, required=True)
    _saved, counts = export_midi(output, audio, result.tempo, interpreter)
    if sys.stdout is not None:
        print(", ".join(f"{name}: {count} note" for name, count in counts.items()))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--selftest":
        return selftest(args[1] if len(args) > 1 else None)
    if args and args[0] in ("analyze", "click", "midi", "stems"):
        command = args[0]
        parser = argparse.ArgumentParser(prog=f"songstructurer {command}")
        parser.add_argument("file")
        outputs = {
            "analyze": (False, "file .json, .csv o .txt (Audacity)"),
            "click": (True, "file .mp3, .wav o .flac"),
            "midi": (True, "file .mid"),
            "stems": (True, "cartella di destinazione"),
        }
        required, text = outputs[command]
        parser.add_argument("-o", "--output", required=required, help=text)
        if command == "stems":
            parser.add_argument("--model", default="htdemucs", help="htdemucs o htdemucs_6s")
        else:
            parser.add_argument("--engine", choices=("classic", "neural"), default="classic")
        parser.add_argument("--python", help="interprete con allin1 e demucs")
        options = parser.parse_args(args[1:])
        if command == "stems":
            return stems_command(options.file, options.output, options.model, options.python)
        handler = {"analyze": analyze_command, "click": click_command, "midi": midi_command}
        return handler[command](options.file, options.output, options.engine, options.python)
    parser = argparse.ArgumentParser(prog="songstructurer", description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", help="file audio da aprire")
    parser.add_argument("--version", action="version", version=f"SongStructurer {__version__}")
    options = parser.parse_args(args)

    from .app import run

    return run(options.file)


if __name__ == "__main__":
    sys.exit(main())
