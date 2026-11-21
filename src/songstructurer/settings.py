"""Small persistent settings file (analysis engine, external interpreter)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {"engine": "classic", "neural_python": ""}


def settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "SongStructurer" / "settings.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "songstructurer" / "settings.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Settings merged over the defaults; a broken file means defaults."""
    values = dict(DEFAULTS)
    try:
        stored = json.loads((path or settings_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if isinstance(stored, dict):
        values.update({k: v for k, v in stored.items() if k in DEFAULTS})
    if values["engine"] not in ("classic", "neural"):
        values["engine"] = "classic"
    return values


def save_settings(values: dict[str, Any], path: Path | None = None) -> bool:
    target = path or settings_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True
