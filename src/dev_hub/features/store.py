"""Group what the feature skill saved for each feature: its plan and its report.

A feature is a branch. The skill names the plan and the report after it, so the shared name (the
slug) is what ties them together. The hub stores nothing: it lists both folders and joins them.
A feature may have only a plan (not done yet) or only a report, and is still shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dev_hub.config import reports_dir
from dev_hub.plans.store import SLUG_RE, list_plans

INDEX_NAME = "index.html"
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class Feature:
    slug: str
    title: str
    has_plan: bool
    has_report: bool
    updated: str  # local time, YYYY-MM-DDTHH:MM


def list_features() -> list[Feature]:
    """Every feature that has a plan or a report, newest first."""
    plans = {plan.slug: plan for plan in list_plans()}
    reports = {path.stem: path for path in reports_dir().glob("*.html") if path.name != INDEX_NAME}
    features = []
    for slug in plans.keys() | reports.keys():
        plan, report = plans.get(slug), reports.get(slug)
        title = plan.title if plan else _report_title(report) or slug
        updated = max(plan.updated if plan else "", _modified(report) if report else "")
        features.append(Feature(slug, title, plan is not None, report is not None, updated))
    return sorted(features, key=lambda feature: feature.updated, reverse=True)


def get_feature(slug: str) -> Feature | None:
    return next((f for f in list_features() if f.slug == slug), None)


def report_file(slug: str) -> Path | None:
    """The report's HTML file, or None if the slug isn't a report we know."""
    if not SLUG_RE.match(slug) or slug == INDEX_NAME.removesuffix(".html"):
        return None
    path = reports_dir() / f"{slug}.html"
    return path if path.is_file() else None


def _report_title(path: Path | None) -> str | None:
    try:
        match = TITLE_RE.search(path.read_text()) if path else None
    except OSError:
        return None
    title = re.sub(r"<[^>]+>", "", match[1]).strip() if match else ""
    return title.removeprefix("Report:").strip() or None


def _modified(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M")
