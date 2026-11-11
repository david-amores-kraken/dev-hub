"""What I write about a branch: the title and body of the PR it will become.

Each branch gets one JSON file in the reviews folder, named after the branch (with `/` written as
`%2F`). The file is `{"pr": {"title": ..., "body": ...}}`. Keys the hub doesn't know are kept when it
saves, so later features can add to the same file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dev_hub.config import reviews_dir

MAX_TITLE = 500
MAX_BODY = 100_000


@dataclass(frozen=True)
class Description:
    title: str = ""
    body: str = ""


def review_file(branch: str) -> Path:
    return reviews_dir() / f"{quote(branch, safe='')}.json"


def load_description(branch: str) -> Description:
    pr = _read(review_file(branch)).get("pr", {})
    return Description(title=str(pr.get("title", "")), body=str(pr.get("body", "")))


def save_description(branch: str, title: str, body: str) -> None:
    path = review_file(branch)
    data = _read(path)
    data["pr"] = {**data.get("pr", {}), "title": title, "body": body}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write a temporary file next to it and swap it in, so a crash can't leave half a file.
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w") as file:
        json.dump(data, file, indent=2)
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any]:
    """The file's contents. A missing file is empty; one that can't be read is an error, so saving
    never overwrites what I wrote with a blank page."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} isn't a JSON object")
    return data
