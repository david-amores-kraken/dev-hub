"""What the VS Code extension reads: the branches, everything about one branch, and its files.

The extension shows the same things as the Features and Diffs sections, so this builds on the same
code (`diffs.pages`, `features`). It only reads. Comments are changed through the Diffs section's
own routes, which the extension posts to as the pages do.

Branch names have slashes, so they are passed as a query parameter (`?branch=`), not in the path.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, jsonify, request, url_for
from werkzeug.wrappers import Response

from dev_hub.diffs import git
from dev_hub.diffs.anchors import read_patch
from dev_hub.diffs.follow import follow
from dev_hub.diffs.git import Commit, GitError
from dev_hub.diffs.pages import (
    commit_patch,
    is_placed,
    newest_first,
    page_files,
    placements,
    shown,
    versions,
)
from dev_hub.diffs.store import list_reviews, load_description
from dev_hub.features.store import get_feature, slug_of
from dev_hub.features.views import LABELS, parts_of
from dev_hub.sandbox import CONTENT_POLICY

blueprint = Blueprint("api", __name__)

SIDES = ("old", "new")


@blueprint.get("/branches")
def branches() -> Response | tuple[Response, int]:
    """The local branches with commits the base doesn't have, newest first."""
    try:
        found = git.list_branches()
    except GitError as problem:
        return jsonify(error=str(problem)), 502
    return jsonify(
        [
            {"name": b.name, "commits": b.commits, "updated": b.updated, "subject": b.subject}
            for b in found
            if b.commits
        ]
    )


@blueprint.get("/branch")
def branch() -> Response:
    """Everything the extension shows for a branch: its feature, PR description, commits, the
    files of each page, reviews, and comments placed on their pages as the Diffs section does.

    A page is "changes" (All changes) or a commit's sha. A comment shown on two pages (see
    `mirror`) is listed once for each. `placed` is false for one the Diffs section lists as
    "couldn't place"."""
    name = _branch()
    commits = git.list_commits(name)
    description = load_description(name)
    patch = git.branch_patch(name)
    comments = follow(name, commits, body=description.body, patch=patch)
    patches = {"changes": patch} | {c.sha: commit_patch(c.sha) for c in commits}
    parsed = {page: read_patch(text) for page, text in patches.items()}
    texts = {"overview": description.body} | {c.sha: c.message for c in commits}
    return jsonify(
        branch=name,
        urls={
            "overview": url_for("diffs.overview", branch=name),
            "comments": url_for("diffs.create_comment", branch=name),
        },
        feature=_feature(name),
        description={"title": description.title, "body": description.body},
        commits=[_commit(c) for c in commits],
        files={page: page_files(text) for page, text in patches.items()},
        reviews=newest_first(list_reviews(name)),
        comments=[
            shown(comment)
            | {
                "target": target or comment["target"],
                "page": page,
                "placed": is_placed(target or comment["target"], page, parsed, texts),
            }
            for comment, page, target in placements(name, commits, comments, patch)
        ],
    )


@blueprint.get("/file")
def file() -> Response:
    """One side of a file on one page of a branch, as the diff page shows it. `text` is None
    when that side doesn't exist, is binary or is too big."""
    name = _branch()
    page, path, side = (request.args.get(key, "") for key in ("page", "path", "side"))
    if side not in SIDES:
        abort(400)
    if page == "changes":
        patch = git.branch_patch(name)
    elif page in {c.sha for c in git.list_commits(name)}:
        patch = commit_patch(page)
    else:
        abort(404)
    index = next((i for i, f in enumerate(page_files(patch)) if f["path"] == path), None)
    if index is None:
        abort(404)
    contents = versions(patch)
    return jsonify(text=contents[index][side] if index < len(contents) else None)


def _branch() -> str:
    """The `branch` parameter. One that isn't a local branch is a 404, so it goes no further."""
    name = request.args.get("branch", "")
    if not name or not git.has_branch(name):
        abort(404)
    return name


def _commit(commit: Commit) -> dict[str, str]:
    return {
        "sha": commit.sha,
        "subject": commit.subject,
        "message": commit.message,
        "author": commit.author,
        "date": commit.date,
    }


def _feature(branch: str) -> dict[str, Any] | None:
    """The feature with the branch's name, with a link to each part it has."""
    feature = get_feature(slug_of(branch))
    if feature is None:
        return None
    return {
        "slug": feature.slug,
        "title": feature.title,
        "url": url_for("features.show", slug=feature.slug),
        "parts": [
            {
                "key": part,
                "label": LABELS[part],
                "url": url_for("features.raw", slug=feature.slug, part=part),
            }
            for part, has in parts_of(feature).items()
            if has
        ],
        # The parts are pages a model wrote. Show them with no scripts and no network.
        "content_policy": CONTENT_POLICY,
    }
