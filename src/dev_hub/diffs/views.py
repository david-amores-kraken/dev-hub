"""The Diffs section: the branches, one branch with its commits, and the diffs to read."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, jsonify, render_template, request
from werkzeug.wrappers import Response

from dev_hub.diffs import git
from dev_hub.diffs.comments import STATUSES, is_valid_text, on_page, open_counts, parse_target
from dev_hub.diffs.git import Commit, GitError
from dev_hub.diffs.store import (
    MAX_BODY,
    MAX_TITLE,
    add_comment,
    delete_comment,
    list_comments,
    load_description,
    save_description,
    update_comment,
)

blueprint = Blueprint("diffs", __name__, template_folder="templates", static_folder="static")

Reply = Response | tuple[Response, int]


@blueprint.get("/")
def index() -> str:
    try:
        branches, error = git.list_branches(), None
    except GitError as problem:
        branches, error = [], str(problem)
    return render_template("diffs/index.html", branches=branches, error=error)


@blueprint.get("/<path:branch>")
def overview(branch: str) -> str:
    return _page(
        "diffs/overview.html",
        branch,
        page="overview",
        description=load_description(branch),
        max_title=MAX_TITLE,
        max_body=MAX_BODY,
    )


@blueprint.get("/<path:branch>/changes")
def changes(branch: str) -> str:
    _require_branch(branch)
    return _page("diffs/patch.html", branch, page="changes", patch=git.branch_patch(branch))


@blueprint.get("/<path:branch>/commits/<sha>")
def show_commit(branch: str, sha: str) -> str:
    commit = _commit(branch, sha)
    return _page("diffs/patch.html", branch, page=sha, commit=commit, patch=git.commit_patch(sha))


@blueprint.post("/<path:branch>/description")
def save(branch: str) -> Reply:
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


@blueprint.post("/<path:branch>/comments")
def create_comment(branch: str) -> Reply:
    commits = {c.sha: c for c in _commits(branch)}
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    target = parse_target(data.get("target"), commits)
    if target is None:
        return jsonify(error="that isn't a place a comment can go"), 400
    if not is_valid_text(data.get("text")):
        return jsonify(error="the comment is empty or too long"), 400
    if target["commit"]:
        # Remember which commit this was, so it can be found again after a rebase.
        target["subject"] = commits[target["commit"]].subject
        target["patch_id"] = git.patch_id(target["commit"])
    return jsonify(add_comment(branch, target, data["text"]))


@blueprint.post("/<path:branch>/comments/<comment_id>")
def change_comment(branch: str, comment_id: str) -> Reply:
    _require_branch(branch)
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    text, status = data.get("text"), data.get("status")
    if text is not None and not is_valid_text(text):
        return jsonify(error="the comment is empty or too long"), 400
    if status is not None and status not in STATUSES:
        return jsonify(error="status must be open or resolved"), 400
    comment = update_comment(branch, comment_id, text=text, status=status)
    if comment is None:
        abort(404)
    return jsonify(comment)


@blueprint.post("/<path:branch>/comments/<comment_id>/delete")
def remove_comment(branch: str, comment_id: str) -> Reply:
    _require_branch(branch)
    if not delete_comment(branch, comment_id):
        abort(404)
    return jsonify(ok=True)


def _require_branch(branch: str) -> None:
    """A name that isn't a local branch is a 404, so it never goes any further."""
    if not git.has_branch(branch):
        abort(404)


def _commits(branch: str) -> list[Commit]:
    _require_branch(branch)
    return git.list_commits(branch)


def _commit(branch: str, sha: str) -> Commit:
    commit = next((c for c in _commits(branch) if c.sha == sha), None)
    if commit is None:
        abort(404)
    return commit


def _page(template: str, branch: str, page: str, **context: Any) -> str:
    """Render one part of a branch. `page` is "overview", "changes" or a commit's sha, and picks
    which comments go on the page."""
    commits = _commits(branch)
    comments = list_comments(branch)
    return render_template(
        template,
        branch=branch,
        commits=commits,
        page=page,
        comments=[c for c in comments if on_page(c, page)],
        counts=open_counts(comments),
        **context,
    )
