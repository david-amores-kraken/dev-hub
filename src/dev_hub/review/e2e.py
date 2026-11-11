"""Publish the results of an e2e-verify run as the e2e part of a feature.

The skill writes one HTML page with `{{IMG:<name>}}` where a screenshot goes. This inlines the
screenshots from the run folder, so the page is one self-contained file, and saves it as
`~/E2E/<slug>.html`, where the Features section shows it. Skill feedback (proposals to improve the
skill) is saved next to it as `<slug>.feedback.md`, for `/e2e-verify-apply`.

It refuses a page or feedback that contains the run's API token, as the old publish script did.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from pathlib import Path

from dev_hub.config import HOST, PORT, e2e_dir, repo_dir
from dev_hub.diffs import git
from dev_hub.features.store import slug_of
from dev_hub.plans.store import SLUG_RE

IMG_RE = re.compile(r"\{\{IMG:([A-Za-z0-9_.-]+)\}\}")
FEEDBACK_MARKER = "<!-- e2e-verify-feedback v1 -->"
MAX_BYTES = 40_000_000


def publish(
    branch: str, results: Path, feedback: Path | None = None, run_dir: Path | None = None
) -> str:
    if not git.has_branch(branch):
        raise SystemExit(f"refusing: {branch!r} isn't a local branch")
    slug = slug_of(branch)
    if not SLUG_RE.match(slug) or slug == "index":
        raise SystemExit(f"refusing: {branch!r} doesn't make a usable name")
    run_dir = run_dir or repo_dir() / ".claude" / "local" / "e2e-runs" / slug
    html = _read(results)
    notes = _read(feedback) if feedback else None

    token = _token(run_dir)
    for name, text in (("the results", html), ("the feedback", notes)):
        if token and text and token in text:
            raise SystemExit(f"refusing: {name} contain the API token")
    if notes is not None and FEEDBACK_MARKER not in notes:
        raise SystemExit(f"refusing: the feedback lacks the {FEEDBACK_MARKER!r} line")
    if "<html" not in html.lower():
        raise SystemExit("refusing: the results must be a whole HTML page")

    shots = run_dir / "shots"
    wanted = set(IMG_RE.findall(html))
    missing = sorted(name for name in wanted if not (shots / f"{name}.png").is_file())
    if missing:
        raise SystemExit(f"refusing: no screenshot in {shots} for: {', '.join(missing)}")
    html = IMG_RE.sub(lambda m: _data_uri(shots / f"{m[1]}.png"), html)
    if len(html.encode()) > MAX_BYTES:
        raise SystemExit(
            f"refusing: the page is over {MAX_BYTES // 1_000_000} MB; use fewer or smaller screenshots"
        )

    target = e2e_dir() / f"{slug}.html"
    _write(target, html)
    if notes is not None:
        _write(e2e_dir() / f"{slug}.feedback.md", notes)
    saved = f"published {target}" + (
        f" and the feedback {target.with_suffix('.feedback.md')}" if notes else ""
    )
    return f"{saved}\nhttp://{HOST}:{PORT}/features/{slug}?tab=e2e"


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as error:
        raise SystemExit(f"refusing: can't read {path}: {error}") from error


def _token(run_dir: Path) -> str:
    try:
        return str(json.loads((run_dir / "state.json").read_text()).get("token") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w") as file:
        file.write(text)
    os.replace(temporary, path)
