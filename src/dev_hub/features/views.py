"""The Features section: the list, one feature with its plan and report, and the files themselves."""

from __future__ import annotations

from flask import Blueprint, Response, abort, render_template, request

from dev_hub.features.store import e2e_file, get_feature, list_features, report_file
from dev_hub.plans.store import plan_file
from dev_hub.sandbox import sandboxed_html

blueprint = Blueprint("features", __name__, template_folder="templates", static_folder="static")

# The parts of a feature, in tab order. Add a part here and in the store to show it.
PARTS = ("plan", "report", "e2e")


@blueprint.get("/")
def index() -> str:
    return render_template("features/index.html", features=list_features())


@blueprint.get("/<slug>")
def show(slug: str) -> str:
    feature = get_feature(slug)
    if feature is None:
        abort(404)
    have = {"plan": feature.has_plan, "report": feature.has_report, "e2e": feature.has_e2e}
    wanted = request.args.get("tab", "")
    tab = wanted if have.get(wanted) else next((part for part in PARTS if have[part]), "plan")
    return render_template("features/show.html", feature=feature, parts=PARTS, have=have, tab=tab)


@blueprint.get("/<slug>/<part>/raw")
def raw(slug: str, part: str) -> Response:
    path = {"plan": plan_file, "report": report_file, "e2e": e2e_file}.get(part, lambda _: None)(
        slug
    )
    if path is None:
        abort(404)
    return sandboxed_html(path)
