"""The PR briefs section: the table of PRs, each brief, and the endpoints the buttons call.

A brief costs money, so the POST endpoints must only be reachable from the hub's own page. The
hub app enforces that for every section (host and origin checks), so this blueprint must not be
served any other way.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.wrappers import Response as BaseResponse

from dev_hub.prs import report as report_helpers
from dev_hub.prs.config import load
from dev_hub.prs.manual import fetch_pr, parse_pr_link
from dev_hub.prs.poll import add_to_queue
from dev_hub.prs.rows import build_rows, counts
from dev_hub.prs.store import (
    HOME,
    MARK_STATES,
    add_manual,
    brief_runs,
    now,
    read_queue,
    read_report,
    read_request,
    set_mark,
    write_request,
)
from dev_hub.prs.tiers import TIERS

RUN_RE = re.compile(r"^[\w.-]+$")
STATUS_LABELS = {
    "waiting": "to review",
    "queued": "queued…",
    "running": "running…",
    "failed": "failed",
    "briefed": "brief ready",
    "reviewed": "reviewed",
    "skipped": "won't review",
    "archived": "brief removed",
}


blueprint = Blueprint("prs", __name__, template_folder="templates", static_folder="static")

blueprint.add_app_template_filter(report_helpers.rich, "rich")
blueprint.add_app_template_filter(report_helpers.stamp, "stamp")
blueprint.add_app_template_filter(report_helpers.duration, "duration")
blueprint.add_app_template_filter(report_helpers.short_location, "short_location")


@blueprint.context_processor
def template_globals() -> dict[str, Any]:
    return {**report_helpers.TEMPLATE_GLOBALS, "STATUS_LABELS": STATUS_LABELS}


# --- pages


@blueprint.get("/")
def index() -> str:
    return render_template("prs/index.html", **index_context())


@blueprint.get("/rows")
def rows() -> str:
    return render_template("prs/_live.html", **index_context())


def index_context() -> dict[str, Any]:
    config = load()
    table = build_rows()
    refreshed = read_queue()["refreshed"]
    return {
        "rows": table,
        "counts": counts(table),
        "refreshed": refreshed.replace("T", " ").removesuffix("Z") + " UTC"
        if refreshed
        else "never",
        "tiers": TIERS,
        "team_name": config.get("team_name", "Core team"),
        "budgets": config["budget_usd"] | {"note": 0},
        "thresholds": config["tiers"],
    }


@blueprint.get("/<int:pr>")
def latest_report(pr: int) -> BaseResponse:
    runs = brief_runs(pr)
    if not runs:
        abort(404)
    return redirect(url_for("prs.report_page", pr=pr, run=runs[-1].name))


@blueprint.get("/<int:pr>/<run>")
def report_page(pr: int, run: str) -> str:
    report = read_report(pr, run) if RUN_RE.match(run) else None
    if report is None:
        abort(404)
    return render_template(
        "prs/report.html",
        report=report,
        meta=report["meta"],
        view=report_helpers.report_view(report),
    )


# --- what the buttons call


@blueprint.post("/api/brief")
def brief() -> tuple[Response, int]:
    body = request.get_json(silent=True)
    pr, tier = (body or {}).get("pr"), (body or {}).get("tier")
    if not isinstance(pr, int) or isinstance(pr, bool) or tier not in TIERS:
        return error(f"need pr (number) and tier ({', '.join(TIERS)})", 400)
    item = next((i for i in read_queue()["items"] if i["number"] == pr), None)
    if item is None:
        return error("that PR isn't in the to-review list", 404)
    existing = read_request(pr)
    if existing and existing["status"] in ("queued", "running"):
        return error(f"already {existing['status']}", 409)
    queued = {
        "pr": pr,
        "tier": tier,
        "title": item["title"],
        "updated_at": item["updated_at"],
        "status": "queued",
        "requested_at": now(),
    }
    write_request(queued)
    start_poller("--requests-only")
    return jsonify(queued), 202


@blueprint.post("/api/add")
def add() -> tuple[Response, int]:
    """Add a PR to the list by link, even though nobody asked the user to review it."""
    config = load()
    link = (request.get_json(silent=True) or {}).get("link")
    number = parse_pr_link(link, config["repo"]) if isinstance(link, str) else None
    if number is None:
        return error(f"need a link to a PR in {config['repo']}, or its number", 400)
    try:
        pr = fetch_pr(number, config)
    except (subprocess.SubprocessError, ValueError):
        return error(f"couldn't get #{number} from GitHub", 502)
    if pr["state"] != "OPEN":
        return error(f"#{number} is {pr['state'].lower()}, so there is nothing to review", 409)
    add_manual(number)
    set_mark(number, None)  # if it was marked reviewed or won't review, it is back on the list
    if not brief_runs(number):
        add_to_queue(pr, config)
    return jsonify(number=number, title=pr["title"]), 201


@blueprint.post("/api/mark")
def mark() -> tuple[Response, int]:
    body = request.get_json(silent=True) or {}
    pr, state = body.get("pr"), body.get("state")
    if not isinstance(pr, int) or isinstance(pr, bool) or state not in (*MARK_STATES, None):
        return error(f"need pr (number) and state ({', '.join(MARK_STATES)} or null)", 400)
    set_mark(pr, state)
    return jsonify(ok=True), 200


@blueprint.post("/api/refresh")
def refresh() -> tuple[Response, int]:
    start_poller("--queue-only")
    return jsonify(ok=True), 202


def error(message: str, status: int) -> tuple[Response, int]:
    return jsonify(error=message), status


def start_poller(flag: str) -> None:
    """Run the poller detached, so restarting this server doesn't kill a brief half way."""
    config = load()
    log = (HOME / "server.log").open("ab")
    subprocess.Popen(
        [sys.executable, "-m", "dev_hub.prs.poll", flag],
        cwd=config["main_repo"],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
