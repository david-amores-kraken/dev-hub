"""The hub: one Flask app with a section per tool, behind one set of safety checks.

It binds to 127.0.0.1 only. Because any web page you visit can send requests to localhost, it
also rejects a Host other than its own (DNS rebinding) and any POST that isn't JSON from its own
origin. Some sections spend money or start work when they are posted to, so these checks apply
to every route. Add a section by registering its blueprint here and listing it in SECTIONS.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, jsonify, redirect, request, url_for
from werkzeug.wrappers import Response as BaseResponse

from dev_hub.config import HOST, PORT
from dev_hub.diffs import blueprint as diffs
from dev_hub.features import blueprint as features
from dev_hub.plans import blueprint as plans
from pr_brief.web import blueprint as prs

# (nav label, blueprint, URL prefix), in nav order.
SECTIONS = (
    ("PRs", prs, "/prs"),
    ("Features", features, "/features"),
    ("Diffs", diffs, "/diffs"),
    ("Plans", plans, "/plans"),
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    own_hosts = {f"{HOST}:{PORT}", f"localhost:{PORT}"}
    own_origins = {f"http://{host}" for host in own_hosts}

    @app.before_request
    def guard() -> tuple[Response, int] | None:
        if request.host not in own_hosts:
            return jsonify(error="wrong host"), 403
        if request.method == "POST" and not (
            request.headers.get("Origin") in own_origins and request.is_json
        ):
            return jsonify(error="not allowed"), 403
        return None

    @app.after_request
    def harden(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.context_processor
    def nav() -> dict[str, Any]:
        tabs = [(label, bp.name, prefix) for label, bp, prefix in SECTIONS]
        return {"sections": tabs, "current_section": request.blueprint}

    @app.get("/")
    def home() -> BaseResponse:
        return redirect(url_for("prs.index"))

    for _, blueprint, prefix in SECTIONS:
        app.register_blueprint(blueprint, url_prefix=prefix)
    return app
