"""Score the structure analysis against JAMS reference annotations.

Usage:
    python tools/benchmark.py AUDIO_DIR REFERENCES_DIR

Every ``AUDIO_DIR/<name>.<ext>`` is matched with ``REFERENCES_DIR/<name>.jams``
(first ``segment_*`` annotation). Needs ``mir_eval`` on top of the runtime
dependencies. Prints boundary hit-rate F-measures (0.5 s and 3 s tolerance)
and the pairwise frame-clustering F-measure of the section groups.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mir_eval
import numpy as np

from songstructurer.analysis import analyze
from songstructurer.audio import load_audio

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg"}


def load_reference(path: Path) -> tuple[np.ndarray, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for annotation in data["annotations"]:
        if annotation["namespace"].startswith("segment"):
            rows = annotation["data"]
            intervals = np.array([[r["time"], r["time"] + r["duration"]] for r in rows])
            return intervals, [str(r["value"]) for r in rows]
    raise ValueError(f"no segment annotation in {path}")


def score(ref_iv, ref_lab, est_iv, est_lab) -> tuple[float, float, float]:
    ref_iv, ref_lab = mir_eval.util.adjust_intervals(ref_iv, ref_lab, t_min=0.0)
    est_iv, est_lab = mir_eval.util.adjust_intervals(est_iv, est_lab, t_min=0.0, t_max=ref_iv.max())
    f05 = mir_eval.segment.detection(ref_iv, est_iv, window=0.5, trim=True)[2]
    f3 = mir_eval.segment.detection(ref_iv, est_iv, window=3.0, trim=True)[2]
    pairwise = mir_eval.segment.pairwise(ref_iv, ref_lab, est_iv, est_lab)[2]
    return f05, f3, pairwise


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    audio_dir, ref_dir = Path(argv[1]), Path(argv[2])
    rows = []
    for audio_path in sorted(audio_dir.iterdir()):
        ref_path = ref_dir / (audio_path.stem + ".jams")
        if audio_path.suffix.lower() not in AUDIO_SUFFIXES or not ref_path.exists():
            continue
        audio = load_audio(audio_path)
        result = analyze(audio.samples, audio.sr)
        est_iv = np.array([[s.start, s.end] for s in result.sections])
        est_lab = [str(s.group) for s in result.sections]
        row = score(*load_reference(ref_path), est_iv, est_lab)
        rows.append(row)
        print(
            f"{audio_path.name:45s} HR.5F={row[0]:.3f} HR3F={row[1]:.3f} PWF={row[2]:.3f}"
            f"  sections={len(result.sections)} tempo={result.tempo} key={result.key}"
        )
    if not rows:
        print("no audio/reference pairs found")
        return 1
    mean = np.mean(rows, axis=0)
    print(f"{'MEAN':45s} HR.5F={mean[0]:.3f} HR3F={mean[1]:.3f} PWF={mean[2]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
