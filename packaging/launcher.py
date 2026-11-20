"""PyInstaller entry point."""

import os
import sys

# A windowed executable has no console: give argparse and friends somewhere to
# write instead of crashing on ``None``.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

from songstructurer.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
