"""Print the CHANGELOG.md section of a version: ``release_notes.py v2.0.0``."""

from __future__ import annotations

import sys
from pathlib import Path


def notes(version: str, changelog: str) -> str:
    version = version.lstrip("v")
    lines: list[str] = []
    inside = False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().startswith(f"[{version}]")
            continue
        if inside:
            lines.append(line)
    return "\n".join(lines).strip()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    text = notes(argv[1], path.read_text(encoding="utf-8"))
    print(text or f"SongStructurer {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
