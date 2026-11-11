"""What I write about a branch: the title and body of the PR it will become, and my comments.

Each branch gets one JSON file in the reviews folder, named after the branch (with `/` written as
`%2F`). The file is `{"pr": {"title": ..., "body": ...}, "comments": [...], "reviews": [...]}`. A comment is
`{id, status, text, created, target}`, and `comments.py` says what a target is. Comments I write
have nothing more. A finding from a reviewer persona also has `persona`, `author` (its name),
`finding_id`, `severity`, and `triage` once I answer it ("address" or "dismiss"). Any comment can
have `replies` from the agent that addressed it. A review is a persona's summary of one pass over
the branch. Keys the hub doesn't know are kept when it saves, so later features can add to the
same file.
"""

from __future__ import annotations

import fcntl
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

# Requests are handled on several threads, and each change is read-modify-write. Other programs
# (the review commands that agents run) change the same files, so the file is locked as well.
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


def add_comment(branch: str, target: dict[str, Any], text: str, **more: Any) -> dict[str, Any]:
    """Save a comment. `more` adds the fields of a persona's finding."""
    comment = {
        "id": uuid.uuid4().hex[:12],
        "status": "open",
        "text": text,
        "created": _now(),
        "target": target,
        **more,
    }
    _change(branch, lambda data: data.setdefault("comments", []).append(comment))
    return comment


def set_triage(branch: str, comment_id: str, triage: str | None) -> dict[str, Any] | None:
    """Mark a finding "address" or "dismiss", or None to take the mark off."""

    def change(data: dict[str, Any]) -> dict[str, Any] | None:
        comment = _find(data, comment_id)
        if comment is not None:
            if triage is None:
                comment.pop("triage", None)
            else:
                comment["triage"] = triage
        return comment

    return _change(branch, change)


def add_reply(
    branch: str, comment_id: str, author: str, text: str, commit: str | None = None
) -> dict[str, Any] | None:
    """Answer a comment and mark it resolved, as the agent does when it has dealt with it."""

    def change(data: dict[str, Any]) -> dict[str, Any] | None:
        comment = _find(data, comment_id)
        if comment is not None:
            reply = {"author": author, "text": text, "commit": commit, "created": _now()}
            comment.setdefault("replies", []).append(reply)
            comment["status"] = "resolved"
        return comment

    return _change(branch, change)


def list_reviews(branch: str) -> list[dict[str, Any]]:
    """Every persona review of the branch, oldest first."""
    return list(_read(review_file(branch)).get("reviews", []))


def add_review(branch: str, review: dict[str, Any], resolved_findings: list[str]) -> dict[str, Any]:
    """Save a persona's review, and resolve the findings it says are fixed."""
    review = {"id": uuid.uuid4().hex[:12], "created": _now(), **review}

    def change(data: dict[str, Any]) -> None:
        data.setdefault("reviews", []).append(review)
        for comment in data.get("comments", []):
            if comment.get("finding_id") in resolved_findings:
                comment["status"] = "resolved"

    _change(branch, change)
    return review


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


def set_targets(branch: str, targets: dict[str, dict[str, Any]]) -> None:
    """Move comments (by id) to new targets. Comments that have gone since are skipped."""

    def change(data: dict[str, Any]) -> None:
        for comment in data.get("comments", []):
            if comment.get("id") in targets:
                comment["target"] = targets[comment["id"]]

    _change(branch, change)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _find(data: dict[str, Any], comment_id: str) -> dict[str, Any] | None:
    return next((c for c in data.get("comments", []) if c.get("id") == comment_id), None)


def _change[T](branch: str, change: Callable[[dict[str, Any]], T]) -> T:
    """Read the branch's file, let `change` edit it, and write it back."""
    path = review_file(branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path.with_name(path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read(path)
        result = change(data)
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
