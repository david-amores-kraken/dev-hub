"""Find the plans the feature skill saved.

The skill writes one self-contained HTML file per plan into ~/Plans, named after the branch, and
keeps a JSON list of them (file, title, updated) inside ~/Plans/index.html. That list is the main
source. Any plan file missing from it is still shown, with its title read from the file, so the
hub never hides a plan because the list is out of date.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dev_hub.config import plans_dir

SLUG_RE = re.compile(r"^[\w][\w.-]*$")
INDEX_LIST_RE = re.compile(
    r'<script[^>]*\bid="plans"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
TITLE_RE = re.compile(r"<(?:h1|title)[^>]*>(.*?)</(?:h1|title)>", re.DOTALL | re.IGNORECASE)
INDEX_NAME = "index.html"


@dataclass(frozen=True)
class Plan:
    slug: str  # the file name without .html: the branch, with / written as -
    title: str
    updated: str  # local time, YYYY-MM-DDTHH:MM


def list_plans() -> list[Plan]:
    """Every plan, newest first."""
    folder = plans_dir()
    on_disk = {p.stem: p for p in folder.glob("*.html") if p.name != INDEX_NAME}
    listed = _listed(folder / INDEX_NAME)
    plans = [
        Plan(slug, title, updated) for slug, (title, updated) in listed.items() if slug in on_disk
    ]
    for slug, path in on_disk.items():
        if slug not in listed:
            plans.append(Plan(slug, _title(path) or slug, _modified(path)))
    return sorted(plans, key=lambda plan: plan.updated, reverse=True)


def plan_file(slug: str) -> Path | None:
    """The plan's HTML file, or None if the slug isn't a plan we know."""
    if not SLUG_RE.match(slug) or slug == INDEX_NAME.removesuffix(".html"):
        return None
    path = plans_dir() / f"{slug}.html"
    return path if path.is_file() else None


def title_of(slug: str) -> str:
    return next((p.title for p in list_plans() if p.slug == slug), slug)


def _listed(index: Path) -> dict[str, tuple[str, str]]:
    try:
        match = INDEX_LIST_RE.search(index.read_text())
        entries = json.loads(match[1]) if match else []
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        Path(e["file"]).stem: (e.get("title") or Path(e["file"]).stem, e.get("updated") or "")
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("file"), str)
    }


def _title(path: Path) -> str | None:
    try:
        match = TITLE_RE.search(path.read_text())
    except OSError:
        return None
    return re.sub(r"<[^>]+>", "", match[1]).strip() if match else None


def _modified(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M")
