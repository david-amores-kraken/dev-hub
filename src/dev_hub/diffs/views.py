"""The Diffs section: the branches, one branch with its commits, and the diffs to read."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request
from werkzeug.wrappers import Response

from dev_hub.diffs import git
from dev_hub.diffs.git import Commit, GitError
from dev_hub.diffs.store import MAX_BODY, MAX_TITLE, load_description, save_description

blueprint = Blueprint("diffs", __name__, template_folder="templates", static_folder="static")


@blueprint.get("/")
def index() -> str:
    try:
        branches, error = git.list_branches(), None
    except GitError as problem:
        branches, error = [], str(problem)
    return render_template("diffs/index.html", branches=branches, error=error)


@blueprint.get("/<path:branch>")
def overview(branch: str) -> str:
    commits = _commits(branch)
    return render_template(
        "diffs/overview.html",
        branch=branch,
        commits=commits,
        description=load_description(branch),
        max_title=MAX_TITLE,
        max_body=MAX_BODY,
    )


@blueprint.post("/<path:branch>/description")
def save(branch: str) -> Response | tuple[Response, int]:
    _require_branch(branch)
    data = request.get_json(silent=True)
    title = data.get("title") if isinstance(data, dict) else None
    body = data.get("body") if isinstance(data, dict) else None
    if not (isinstance(title, str) and isinstance(body, str)):
        return jsonify(error="title and body must be text"), 400
    if len(title) > MAX_TITLE or len(body) > MAX_BODY:
        return jsonify(error="too long"), 400
    save_description(branch, title, body)
    return jsonify(ok=True)


@blueprint.get("/<path:branch>/changes")
def changes(branch: str) -> str:
    commits = _commits(branch)
    return _patch_page(branch, commits, git.branch_patch(branch), commit=None)


@blueprint.get("/<path:branch>/commits/<sha>")
def show_commit(branch: str, sha: str) -> str:
    commits = _commits(branch)
    commit = next((c for c in commits if c.sha == sha), None)
    if commit is None:
        abort(404)
    return _patch_page(branch, commits, git.commit_patch(sha), commit=commit)


def _require_branch(branch: str) -> None:
    """A name that isn't a local branch is a 404, so it never goes any further."""
    if not git.has_branch(branch):
        abort(404)


def _commits(branch: str) -> list[Commit]:
    _require_branch(branch)
    return git.list_commits(branch)


def _patch_page(branch: str, commits: list[Commit], patch: str, commit: Commit | None) -> str:
    return render_template(
        "diffs/patch.html", branch=branch, commits=commits, patch=patch, commit=commit
    )
