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
            ok=all(hits) and len(found) <= 5 and len(set(groups)) < len(groups),
        )
    except Exception as exc:  # noqa: BLE001 - the report must say what broke
        report["error"] = f"{type(exc).__name__}: {exc}"
    text = json.dumps(report, indent=2)
    if report_path:
        Path(report_path).write_text(text + "\n", encoding="utf-8")
    elif sys.stdout is not None:
        print(text)
    return 0 if report["ok"] else 1


def analyze_command(source: str, output: str | None) -> int:
    from .analysis import analyze
    from .audio import load_audio
    from .export import to_json, write_export
    from .model import Segment, Structure

    audio = load_audio(source)
    result = analyze(audio.mono(), audio.sr)
    structure = Structure(
        audio.duration, [Segment(s.start, s.end, s.label, s.group) for s in result.sections]
    )
    metadata = {"file": Path(source).name, "tempo_bpm": result.tempo, "key": result.key}
    if output:
        write_export(output, structure, metadata)
    elif sys.stdout is not None:
        sys.stdout.write(to_json(structure, metadata))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--selftest":
        return selftest(args[1] if len(args) > 1 else None)
    if args and args[0] == "analyze":
        parser = argparse.ArgumentParser(prog="songstructurer analyze")
        parser.add_argument("file")
        parser.add_argument("-o", "--output", help="file .json, .csv o .txt (etichette Audacity)")
        options = parser.parse_args(args[1:])
        return analyze_command(options.file, options.output)
    parser = argparse.ArgumentParser(prog="songstructurer", description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", help="file audio da aprire")
    parser.add_argument("--version", action="version", version=f"SongStructurer {__version__}")
    options = parser.parse_args(args)

    from .app import run

    return run(options.file)


if __name__ == "__main__":
    sys.exit(main())
