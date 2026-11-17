"""The Diffs section: the branches, one branch with its commits, and the diffs to read."""

from __future__ import annotations

from functools import cache
from typing import Any

from flask import Blueprint, abort, jsonify, render_template, request, url_for
from werkzeug.wrappers import Response

from dev_hub.diffs import git
from dev_hub.diffs.anchors import Patch, Row, read_patch
from dev_hub.diffs.comments import (
    STATUSES,
    TRIAGE,
    is_valid_text,
    open_counts,
    page_of,
    parse_target,
)
from dev_hub.diffs.follow import follow
from dev_hub.diffs.git import Commit, GitError
from dev_hub.diffs.markdown import render
from dev_hub.diffs.mirror import mirror
from dev_hub.diffs.store import (
    MAX_BODY,
    MAX_TITLE,
    add_comment,
    delete_comment,
    list_reviews,
    load_description,
    save_description,
    set_triage,
    update_comment,
)
from dev_hub.features.store import has_feature, slug_of

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
    commits = _commits(branch)
    description = load_description(branch)
    patch = git.branch_patch(branch)
    comments = follow(branch, commits, body=description.body, patch=patch)
    reviews = _newest_first(list_reviews(branch))
    findings = _findings(branch, commits, reviews, comments, read_patch(patch))
    return _page(
        "diffs/overview.html",
        branch,
        commits,
        comments,
        page="overview",
        branch_patch=patch,
        description=description,
        reviews=reviews,
        findings=findings,
        review_comments=[item["comment"] for items in findings.values() for item in items],
        max_title=MAX_TITLE,
        max_body=MAX_BODY,
    )


@blueprint.get("/<path:branch>/changes")
def changes(branch: str) -> str:
    commits = _commits(branch)
    patch = git.branch_patch(branch)
    comments = follow(branch, commits, patch=patch)
    return _page(
        "diffs/patch.html",
        branch,
        commits,
        comments,
        page="changes",
        branch_patch=patch,
        patch=patch,
        versions=_versions(patch),
    )


@blueprint.get("/<path:branch>/commits/<sha>")
def show_commit(branch: str, sha: str) -> str:
    commits = _commits(branch)
    branch_patch = git.branch_patch(branch)
    # First, so a rebased commit's comments are on its new sha.
    comments = follow(branch, commits, patch=branch_patch)
    commit = next((c for c in commits if c.sha == sha), None)
    if commit is None:
        abort(404)
    patch = _commit_patch(sha)
    return _page(
        "diffs/patch.html",
        branch,
        commits,
        comments,
        page=sha,
        branch_patch=branch_patch,
        commit=commit,
        patch=patch,
        versions=_versions(patch),
    )


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


@blueprint.post("/<path:branch>/preview")
def preview(branch: str) -> Reply:
    """The description as the reviewer will read it. Takes the text as typed, saved or not."""
    _require_branch(branch)
    data = request.get_json(silent=True)
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, str) or len(body) > MAX_BODY:
        return jsonify(error="body must be text"), 400
    return jsonify(html=render(body))


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
    return jsonify(_shown(add_comment(branch, target, data["text"])))


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
    if "triage" in data and data["triage"] not in (None, *TRIAGE):
        return jsonify(error="triage must be address, dismiss or null"), 400
    comment = update_comment(branch, comment_id, text=text, status=status)
    if comment is not None and "triage" in data:
        comment = set_triage(branch, comment_id, data["triage"])
    if comment is None:
        abort(404)
    return jsonify(_shown(comment))


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


@cache
def _commit_patch(sha: str) -> str:
    """A commit's diff. A sha always names the same commit, so it never needs reading twice."""
    return git.commit_patch(sha)


def _shown(comment: dict[str, Any]) -> dict[str, Any]:
    """A comment as the page gets it: with its text, and its replies', rendered as GitHub would.
    A suggestion replaces the quoted lines."""
    quote = comment.get("target", {}).get("quote")
    replies = [{**r, "html": render(r.get("text", ""), quote)} for r in comment.get("replies", [])]
    shown = {**comment, "html": render(comment.get("text", ""), quote)}
    return {**shown, "replies": replies} if "replies" in comment else shown


def _versions(patch: str) -> list[dict[str, str | None]]:
    """The whole files, for highlighting. Without them the diff is still shown, just highlighted
    line by line."""
    try:
        return git.file_versions(patch)
    except GitError:
        return []


def _newest_first(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reviews, newest first, each marked `latest` if no later review is from the same persona."""
    seen: set[str] = set()
    ordered = []
    for review in reversed(reviews):
        ordered.append({**review, "latest": review["persona"] not in seen})
        seen.add(review["persona"])
    return ordered


def _page(
    template: str,
    branch: str,
    commits: list[Commit],
    comments: list[dict[str, Any]],
    page: str,
    branch_patch: str,
    **context: Any,
) -> str:
    """Render one part of a branch. `page` is "overview", "changes" or a commit's sha, and picks
    which of the comments go on the page. `branch_patch` is the "All changes" diff."""
    placed = _placements(branch, commits, comments, branch_patch)
    return render_template(
        template,
        branch=branch,
        commits=commits,
        page=page,
        comments=[
            _shown(c) | ({"target": t} if t else {}) for c, where, t in placed if where == page
        ],
        counts=open_counts((comment, where) for comment, where, _ in placed),
        feature_slug=slug_of(branch) if has_feature(slug_of(branch)) else None,
        **context,
    )


def _placements(
    branch: str, commits: list[Commit], comments: list[dict[str, Any]], branch_patch: str
) -> list[tuple[dict[str, Any], str, dict[str, Any] | None]]:
    """Each page a comment is shown on, as (comment, page, target there). The target is None on
    the comment's own page. A comment on a diff line is also shown on the other page that has the
    same lines (see `mirror`), with a `mirror` link back to where it was made."""
    shas = [commit.sha for commit in commits]
    subjects = {commit.sha: commit.subject for commit in commits}
    placed: list[tuple[dict[str, Any], str, dict[str, Any] | None]] = []
    lines = [c for c in comments if c["target"]["kind"] == "line"]
    patches = {sha: read_patch(_commit_patch(sha)) for sha in shas} if lines else {}
    whole = read_patch(branch_patch) if lines else Patch({}, {})
    for comment in comments:
        home = page_of(comment["target"], shas)
        placed.append((comment, home, None))
        if comment["target"]["kind"] != "line" or home == "overview":
            continue
        there = mirror(comment["target"], shas, patches, whole)
        if there is None:
            continue
        own = comment["target"]["commit"]
        link = {
            "label": f"commit “{subjects[own]}”" if own else "All changes",
            "url": url_for("diffs.show_commit", branch=branch, sha=own)
            if own
            else url_for("diffs.changes", branch=branch),
        }
        placed.append(({**comment, "mirror": link}, there["commit"] or "changes", there))
    return placed


def _findings(
    branch: str,
    commits: list[Commit],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    whole: Patch,
) -> dict[str, list[dict[str, Any]]]:
    """Each review's findings that are comments, by review id, with the lines they are about as
    GitHub shows them in a review: the end of the diff hunk, up to the last line commented on."""
    shas = {commit.sha for commit in commits}
    found: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        ids = set(review.get("findings", []))
        items = []
        for comment in comments:
            if comment.get("persona") != review["persona"] or comment.get("finding_id") not in ids:
                continue
            target = comment["target"]
            rows = None
            if target["kind"] == "line":
                commit = target["commit"]
                if commit is None:
                    patch = whole
                elif commit in shas:
                    patch = read_patch(_commit_patch(commit))
                else:  # its commit has gone, so its lines can't be shown
                    patch = Patch({}, {})
                rows = _context(patch.files.get(target["file"], []), target)
            items.append({"comment": _shown(comment), "rows": rows, "url": _url(branch, target)})
        found[review["id"]] = items
    return found


def _context(rows: list[Row], target: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The diff rows of a comment's lines and up to three rows before them, in the same hunk, each
    marked `chosen` if it is one of the comment's lines. None if the lines aren't in the diff."""
    side = target["side"]
    wanted = range(target["start"], target["end"] + 1)
    picked = [i for i, row in enumerate(rows) if getattr(row, side) in wanted]
    quote = [line.rstrip() for line in target["quote"].split("\n")]
    if [rows[i].text.rstrip() for i in picked] != quote:
        return None
    first, last = picked[0], picked[-1]
    start = first
    while start > 0 and first - start < 3 and rows[start - 1].hunk == rows[first].hunk:
        start -= 1
    return [
        {
            "old": row.old,
            "new": row.new,
            "text": row.text,
            "change": "del" if row.new is None else "add" if row.old is None else "",
            "chosen": i in picked,
        }
        for i, row in enumerate(rows[start : last + 1], start=start)
    ]


def _url(branch: str, target: dict[str, Any]) -> str:
    if target["kind"] == "pr_body" or not target["commit"]:
        return url_for(
            "diffs.overview" if target["kind"] == "pr_body" else "diffs.changes", branch=branch
        )
    return url_for("diffs.show_commit", branch=branch, sha=target["commit"])
