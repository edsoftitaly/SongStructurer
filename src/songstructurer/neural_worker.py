"""Runs the All-In-One structure model and writes its result as JSON.

This file is executed by an *external* Python interpreter, the one where
``allin1`` (with torch and demucs) is installed:

    python neural_worker.py AUDIO OUTPUT.json [--device cpu|cuda] [--model NAME]

It must therefore depend on nothing but the standard library and ``allin1``.
"""

import json
import sys
import tempfile
import traceback
from pathlib import Path


def run(audio, output, device=None, model=None):
    import allin1

    options = {}
    if device:
        options["device"] = device
    if model:
        options["model"] = model
    with tempfile.TemporaryDirectory(prefix="songstructurer-") as scratch:
        result = allin1.analyze(
            audio,
            demix_dir=str(Path(scratch) / "demix"),
            spec_dir=str(Path(scratch) / "spec"),
            keep_byproducts=False,
            multiprocess=False,
            **options,
        )
    payload = {
        "allin1_version": getattr(allin1, "__version__", ""),
        "bpm": result.bpm,
        "beats": [float(t) for t in result.beats],
        "downbeats": [float(t) for t in result.downbeats],
        "segments": [
            {"start": float(s.start), "end": float(s.end), "label": str(s.label)}
            for s in result.segments
        ],
    }
    Path(output).write_text(json.dumps(payload), encoding="utf-8")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    audio, output = argv[1], argv[2]
    extra = argv[3:]
    device = extra[extra.index("--device") + 1] if "--device" in extra else None
    model = extra[extra.index("--model") + 1] if "--model" in extra else None
    try:
        run(audio, output, device, model)
    except Exception as exc:  # the caller needs the reason, whatever it is
        traceback.print_exc()
        message = f"{type(exc).__name__}: {exc}"
        Path(output).write_text(json.dumps({"error": message}), encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
