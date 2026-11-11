"""Just enough of the PR section for the hub's tests: a page and one POST route."""

from flask import Blueprint, jsonify, render_template_string

blueprint = Blueprint("prs", __name__)


@blueprint.get("/")
def index() -> str:
    return render_template_string(
        '{% extends "base.html" %}{% block content %}<h1>PR briefs</h1>{% endblock %}'
    )


@blueprint.post("/api/mark")
def mark():
    return jsonify(ok=True)
