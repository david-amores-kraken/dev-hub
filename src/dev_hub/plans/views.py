"""The Plans section: the list, one plan inside the hub's layout, and the plan file itself."""

from __future__ import annotations

from flask import Blueprint, Response, abort, render_template

from dev_hub.plans.store import list_plans, plan_file, title_of
from dev_hub.sandbox import sandboxed_html

blueprint = Blueprint("plans", __name__, template_folder="templates", static_folder="static")


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
    return sandboxed_html(path)
