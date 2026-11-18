"""Everything pr-brief keeps under ~/pr-reviews, shared by the poller and the web app.

queue.json        PRs waiting for the user's review, written by the poller on every tick.
requests/N.json   One per click on Brief: the tier chosen and how the run is going
                  (queued, running, done or failed).
manual.json       PRs the user added by link, kept in the list while they are open.
marks.json        What the user decided about each PR: reviewed, or won't review.
history.json      A record of briefs that were made and since removed to save disk space.
runs/prN/<run>/   One folder per brief (report.json and what the personas wrote).
worktrees/prN     The PR's code, checked out for the personas to read.
state.json        The poller's retry counts. See poll.py.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev_hub.files import write_atomic

# PR_BRIEF_HOME lets the hub's tests keep their data apart from the real folder.
HOME = Path(os.environ.get("PR_BRIEF_HOME") or Path.home() / "pr-reviews")
RUNS = HOME / "runs"
WORKTREES = HOME / "worktrees"
QUEUE = HOME / "queue.json"
REQUESTS = HOME / "requests"
MARKS = HOME / "marks.json"
HISTORY = HOME / "history.json"
MANUAL = HOME / "manual.json"
STATE = HOME / "state.json"

MARK_STATES = ("reviewed", "skipped")
_marks_lock = threading.Lock()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, data: object) -> None:
    write_atomic(path, json.dumps(data, indent=1))


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


# --- the to-review queue


def read_queue() -> dict[str, Any]:
    return read_json(QUEUE, {"refreshed": None, "items": []})


# --- requests to brief a PR


def read_request(pr: int) -> dict[str, Any] | None:
    return read_json(REQUESTS / f"{pr}.json", None)


def all_requests() -> list[dict[str, Any]]:
    found = (read_request(int(p.stem)) for p in REQUESTS.glob("*.json") if p.stem.isdigit())
    return [r for r in found if r]


def write_request(request: dict[str, Any]) -> None:
    write_json(REQUESTS / f"{request['pr']}.json", request)


# --- PRs added by link


def read_manual() -> list[int]:
    return [int(pr) for pr in read_json(MANUAL, {})]


def add_manual(pr: int) -> None:
    with _marks_lock:
        manual = read_json(MANUAL, {})
        manual.setdefault(str(pr), {"at": now()})
        write_json(MANUAL, manual)


def drop_manual(pr: int) -> None:
    with _marks_lock:
        manual = read_json(MANUAL, {})
        if manual.pop(str(pr), None) is not None:
            write_json(MANUAL, manual)


# --- the user's decisions


def read_marks() -> dict[int, dict[str, str]]:
    return {int(pr): mark for pr, mark in read_json(MARKS, {}).items()}


def set_mark(pr: int, state: str | None) -> None:
    """Mark a PR reviewed or skipped, or clear its mark with None."""
    with _marks_lock:
        marks = read_json(MARKS, {})
        if state is None:
            marks.pop(str(pr), None)
        else:
            marks[str(pr)] = {"state": state, "at": now()}
        write_json(MARKS, marks)


# --- briefs, past and present


def read_history() -> dict[int, dict[str, Any]]:
    return {int(pr): entry for pr, entry in read_json(HISTORY, {}).items()}


def brief_runs(pr: int) -> list[Path]:
    """Folders of the PR's finished briefs, oldest first."""
    return sorted(
        report.parent
        for report in (RUNS / f"pr{pr}").glob("*/report.json")
        if not (report.parent / "FAILED").exists()
    )


def read_report(pr: int, run: str) -> dict[str, Any] | None:
    return read_json(RUNS / f"pr{pr}" / run / "report.json", None)
