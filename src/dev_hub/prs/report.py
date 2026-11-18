"""Filters and view data for the brief page (templates/report.html).

All text from agents and from the PR is untrusted. Jinja escapes everything; the only markup
added here is `code` spans and links to line references that assemble.py resolved to GitHub.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from dev_hub.prs.text import CODE_RE, REF_RE

SEVERITY_LABELS = {
    "blocker": "blocker",
    "should-fix": "should fix",
    "question": "ask the author",
    "nit": "nit",
}
SEVERITY_CLASS = {
    "blocker": "blocker",
    "should-fix": "focus",
    "question": "skim",
    "nit": "plain",
}
STATUS_CLASS = {"new": "new", "still open": "plain"}
MATCH_LABELS = {
    "yes": "matches the ticket",
    "partly": "partly matches the ticket",
    "no": "doesn't match the ticket",
    "no-ticket": "no ticket linked",
    "unavailable": "ticket not checked",
}
TEMPLATE_GLOBALS = {
    "SEVERITY_LABELS": SEVERITY_LABELS,
    "SEVERITY_CLASS": SEVERITY_CLASS,
    "STATUS_CLASS": STATUS_CLASS,
    "MATCH_LABELS": MATCH_LABELS,
}


def rich(value: str, links: dict[str, str] | None = None) -> Markup:
    """Escaped text, with `backticks` shown as code and resolved line references as links."""
    text = CODE_RE.sub(r"<code>\1</code>", str(escape(value)))
    if links:
        text = REF_RE.sub(
            lambda m: f'<a href="{escape(links[m[0]])}">{m[0]}</a>' if m[0] in links else m[0],
            text,
        )
    return Markup(text)


def stamp(value: str) -> str:
    """20261010T211940Z -> 2026-10-11 08:19 AEDT (Sydney time, so AEST or AEDT as it applies)."""
    utc = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return utc.astimezone(ZoneInfo("Australia/Sydney")).strftime("%Y-%m-%d %H:%M %Z")


def pr_stamp(meta: dict[str, Any], fallback: str) -> str:
    """When the PR was opened; briefs made before this was recorded show the brief time."""
    if "pr_created" not in meta:
        return stamp(fallback)
    return stamp(meta["pr_created"].replace("-", "").replace(":", ""))


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def short_location(loc: dict[str, Any]) -> str:
    # The parent folder too, since many files share a name (queries.py, api.py).
    name = "/".join(loc["path"].rsplit("/", 2)[-2:])
    lines = f":{loc['start']}" + (f"-{loc['end']}" if loc["end"] else "") if loc["start"] else ""
    return f"{name}{lines}{' (base)' if loc['side'] == 'base' else ''}"


def report_view(report: dict[str, Any]) -> dict[str, Any]:
    """Facts the template shows that take more than a lookup to work out."""
    meta = report["meta"]
    return {
        "ci": _ci(meta["checks"]),
        "reviews": ", ".join(
            f"{r['author']} {r['state'].lower().replace('_', ' ')}" for r in meta["reviews"]
        ),
        "since": _since(report),
        "cost": _cost(report.get("cost")),
        "resume": _resume(meta),
    }


def _ci(checks: dict[str, Any]) -> str:
    if not checks.get("available"):
        return "CI unknown"
    return (
        ", ".join(f"{n} {bucket}" for bucket, n in sorted(checks["counts"].items())) or "no checks"
    )


def _since(report: dict[str, Any]) -> str:
    since = report["meta"]["since_previous"]
    if not since:
        return ""
    if since["same_head"]:
        return "same head as the last brief"
    if since["force_pushed"]:
        changed = sum(bool(c.get("new")) for c in report["commits"])
        return (
            f"force-pushed since the last brief at {since['sha'][:7]}, {changed} commit(s) changed"
        )
    return f"{len(since['new_commits'])} new commit(s) since the last brief"


def _cost(cost: dict[str, Any] | None) -> dict[str, Any] | None:
    """Estimated spend and time, per agent, from the session transcripts (see usage.py).

    Agents run side by side, so their times don't add up to the total.
    """
    if not cost:
        return None
    merged: dict[str, list[float]] = {}
    for item in [cost["session"], *cost["agents"]]:
        row = merged.setdefault(item["agent"], [0, 0])
        row[0] += item["usd"]
        row[1] += item.get("seconds") or 0
    prepare = cost.get("prepare_seconds")
    session = cost["session"].get("seconds")
    total = (prepare or 0) + (session or 0) if prepare is not None or session is not None else None
    return {
        "rows": [
            (name, usd, seconds)
            for name, (usd, seconds) in sorted(merged.items(), key=lambda kv: -kv[1][0])
        ],
        "total_usd": cost["total_usd"],
        "reported_usd": cost.get("cli_total_usd"),
        "total_seconds": total,
        "prepare_seconds": prepare,
        "session_seconds": session,
    }


def _resume(meta: dict[str, Any]) -> str | None:
    """The command that reopens the session that wrote the brief, if it was recorded."""
    try:
        session_id = json.loads((Path(meta["run_dir"]) / "session.json").read_text())["session_id"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id):
        return None
    return f"cd {meta['main_repo']} && claude --resume {session_id}"
