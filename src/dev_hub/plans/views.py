"""The Plans section: the list, one plan inside the hub's layout, and the plan file itself."""

from __future__ import annotations

import re

from flask import Blueprint, Response, abort, render_template

from dev_hub.plans.store import list_plans, plan_file, title_of

blueprint = Blueprint("plans", __name__, template_folder="templates", static_folder="static")

HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)
# A plan is a document the model wrote, so it is shown in a sandbox: no scripts, no network, and
# links open in a new tab. Plans only need inline CSS and <details>, which this allows.
PLAN_CSP = (
    "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:"
)


@blueprint.get("/")
def index() -> str:
    return render_template("plans/index.html", plans=list_plans())


@blueprint.get("/<slug>")
def show(slug: str) -> str:
    if plan_file(slug) is None:
        abort(404)
    return render_template("plans/show.html", slug=slug, title=title_of(slug))


@blueprint.get("/<slug>/raw")
def raw(slug: str) -> Response:
    path = plan_file(slug)
    if path is None:
        abort(404)
    html = path.read_text()
    if "<base " not in html.lower():
        html = HEAD_OPEN_RE.sub(lambda m: m[0] + '<base target="_blank">', html, count=1)
    response = Response(html, mimetype="text/html")
    response.headers["Content-Security-Policy"] = PLAN_CSP
    return response
