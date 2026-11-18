"""The pr-brief settings I edit: config.json in the data folder (~/pr-reviews).

It names machine paths and my team, so it stays out of the repo. `skills/pr-brief/config.example.json`
shows every key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dev_hub.prs import store

SKILL_DIR = Path(__file__).resolve().parents[3] / "skills" / "pr-brief"
EXAMPLE = SKILL_DIR / "config.example.json"


def config_path() -> Path:
    return store.HOME / "config.json"


def load() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        raise FileNotFoundError(f"no pr-brief config at {path}: copy {EXAMPLE} there and edit it")
    return json.loads(path.read_text())
