"""What I write about a branch: the title and body of the PR it will become, and my comments.

Each branch gets one JSON file in the reviews folder, named after the branch (with `/` written as
`%2F`). The file is `{"pr": {"title": ..., "body": ...}, "comments": [...]}`. A comment is
`{id, status, text, created, target}`, and `comments.py` says what a target is. Keys the hub doesn't
know are kept when it saves, so later features can add to the same file.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dev_hub.config import reviews_dir

MAX_TITLE = 500
MAX_BODY = 100_000

# Requests are handled on several threads, and each change is read-modify-write.
_lock = threading.Lock()


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
    def change(data: dict[str, Any]) -> None:
        data["pr"] = {**data.get("pr", {}), "title": title, "body": body}

    _change(branch, change)


def list_comments(branch: str) -> list[dict[str, Any]]:
    """Every comment on the branch, oldest first."""
    return list(_read(review_file(branch)).get("comments", []))


def add_comment(branch: str, target: dict[str, Any], text: str) -> dict[str, Any]:
    comment = {
        "id": uuid.uuid4().hex[:12],
        "status": "open",
        "text": text,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": target,
    }
    _change(branch, lambda data: data.setdefault("comments", []).append(comment))
    return comment


def update_comment(
    branch: str, comment_id: str, text: str | None = None, status: str | None = None
) -> dict[str, Any] | None:
    """Change a comment's text and/or status. None if there is no such comment."""

    def change(data: dict[str, Any]) -> dict[str, Any] | None:
        comment = _find(data, comment_id)
        if comment is not None:
            comment["text"] = comment["text"] if text is None else text
            comment["status"] = comment["status"] if status is None else status
        return comment

    return _change(branch, change)


def delete_comment(branch: str, comment_id: str) -> bool:
    def change(data: dict[str, Any]) -> bool:
        comment = _find(data, comment_id)
        if comment is not None:
            data["comments"].remove(comment)
        return comment is not None

    return _change(branch, change)


def _find(data: dict[str, Any], comment_id: str) -> dict[str, Any] | None:
    return next((c for c in data.get("comments", []) if c.get("id") == comment_id), None)


def _change[T](branch: str, change: Callable[[dict[str, Any]], T]) -> T:
    """Read the branch's file, let `change` edit it, and write it back."""
    with _lock:
        path = review_file(branch)
        data = _read(path)
        result = change(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write a temporary file next to it and swap it in, so a crash can't leave half a file.
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w") as file:
            json.dump(data, file, indent=2)
        os.replace(temporary, path)
        return result


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
