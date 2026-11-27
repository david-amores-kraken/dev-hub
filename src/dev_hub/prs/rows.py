"""The index table: one row per PR, whether it is waiting for a brief, being briefed or done."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dev_hub.prs.config import load
from dev_hub.prs.store import (
    RUNS,
    all_requests,
    brief_runs,
    read_history,
    read_marks,
    read_queue,
    read_report,
)

# Status -> the group the filter on the page works with.
GROUPS = {
    "waiting": "todo",
    "queued": "todo",
    "running": "todo",
    "failed": "todo",
    "briefed": "briefed",
    "reviewed": "done",
    "skipped": "done",
    "archived": "done",
}
EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass
class Row:
    number: int
    title: str
    author: str
    status: str
    activity: datetime
    created: datetime | None = None
    updated: datetime | None = None
    core: bool = False
    url: str | None = None
    via: list[str] = field(default_factory=list)
    size: str | None = None
    size_note: str = ""
    suggested: str | None = None
    tier: str | None = None
    latest_run: str | None = None
    older_runs: list[str] = field(default_factory=list)
    error: str | None = None
    focus: str = ""
    brief_removed: bool = False

    @property
    def group(self) -> str:
        return GROUPS[self.status]

    @property
    def busy(self) -> bool:
        return self.status in ("queued", "running")

    @property
    def in_queue(self) -> bool:
        return bool(self.via)


def build_rows() -> list[Row]:
    """Every PR we know about: ready briefs first, then the rest, most recently active first."""
    queue = {item["number"]: item for item in read_queue()["items"]}
    history = read_history()
    marks = read_marks()
    requests = {r["pr"]: r for r in all_requests()}
    team = {name.lower() for name in load().get("team", [])}
    on_disk = {int(p.name[2:]) for p in RUNS.glob("pr*") if p.name[2:].isdigit()}

    rows = [
        _row(n, queue.get(n), history.get(n), marks.get(n), requests.get(n))
        for n in queue.keys() | history.keys() | on_disk
    ]
    for row in rows:
        row.core = row.author.lower() in team
    rows.sort(key=lambda row: row.activity, reverse=True)
    rows.sort(key=lambda row: row.status != "briefed")  # stable, so each part keeps its order
    return rows


def _row(
    number: int,
    item: dict[str, Any] | None,
    past: dict[str, Any] | None,
    mark: dict[str, str] | None,
    request: dict[str, Any] | None,
) -> Row:
    runs = brief_runs(number)
    report = read_report(number, runs[-1].name) if runs else None
    meta = report["meta"] if report else {}

    if request and request["status"] in ("queued", "running"):
        status = request["status"]
    elif mark:
        status = mark["state"]
    elif runs:
        status = "briefed"
    elif request and request["status"] == "failed" and item:
        status = "failed"
    elif item:
        status = "waiting"
    else:
        status = "archived"

    source = item or past or {}
    seen = [
        _when(item["updated_at"]) if item else EPOCH,
        _when(report["assembled"]) if report else EPOCH,
        _when(past["briefed_at"]) if past else EPOCH,
    ]
    return Row(
        number=number,
        title=meta.get("title") or source.get("title", ""),
        author=meta.get("author") or source.get("author", ""),
        status=status,
        activity=max(seen),
        created=_date((item or {}).get("created_at") or meta.get("pr_created")),
        updated=_date(item["updated_at"]) if item else None,
        url=meta.get("url") or source.get("url"),
        via=item["requested_via"] if item else [],
        size=_size(item) if item else None,
        size_note=item["reason"] if item else "",
        suggested=item["suggested"] if item else None,
        tier=(request or {}).get("tier") or meta.get("tier") or (past or {}).get("tier"),
        latest_run=runs[-1].name if runs else None,
        older_runs=[run.name for run in reversed(runs[:-1])],
        error=request.get("error") if request and request["status"] == "failed" else None,
        brief_removed=not runs and past is not None,
        focus=(request or {}).get("focus") or meta.get("focus") or "",
    )


def counts(rows: list[Row]) -> dict[str, int]:
    return {group: sum(row.group == group for row in rows) for group in ("todo", "briefed", "done")}


def _size(item: dict[str, Any]) -> str | None:
    if item["additions"] is None:
        return None
    return f"+{item['additions']} −{item['deletions']} · {item['changed_files']} files"


def _when(stamp: str) -> datetime:
    """Parse 2026-11-10T01:02:03Z (queue) or 20261110T010203Z (run names, reports)."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return EPOCH


def _date(stamp: str | None) -> datetime | None:
    """A date shown in the table, or None when we don't know it (old rows, removed briefs)."""
    when = _when(stamp) if stamp else EPOCH
    return None if when == EPOCH else when
