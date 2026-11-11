"""The Diffs section: the branches, one branch with its commits, and the diffs to read."""

from __future__ import annotations

from flask import Blueprint, abort, render_template

from dev_hub.diffs import git
from dev_hub.diffs.git import Commit, GitError

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
    return render_template("diffs/overview.html", branch=branch, commits=commits)


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


def _commits(branch: str) -> list[Commit]:
    """The branch's commits. A name that isn't a local branch is a 404, so it never reaches git."""
    if not git.has_branch(branch):
        abort(404)
    return git.list_commits(branch)


def _patch_page(branch: str, commits: list[Commit], patch: str, commit: Commit | None) -> str:
    return render_template(
        "diffs/patch.html", branch=branch, commits=commits, patch=patch, commit=commit
    )
