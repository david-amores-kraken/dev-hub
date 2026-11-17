"""What the pages of a branch show, worked out once for every view of it.

The Diffs section's HTML pages and the JSON API (which the VS Code extension reads) both build on
these, so a comment is placed, mirrored and listed under its review the same way in both.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from flask import url_for

from dev_hub.diffs import git
from dev_hub.diffs.anchors import Patch, Row, read_patch
from dev_hub.diffs.comments import page_of
from dev_hub.diffs.git import Commit, GitError
from dev_hub.diffs.markdown import render
from dev_hub.diffs.mirror import mirror


@cache
def commit_patch(sha: str) -> str:
    """A commit's diff. A sha always names the same commit, so it never needs reading twice."""
    return git.commit_patch(sha)


def shown(comment: dict[str, Any]) -> dict[str, Any]:
    """A comment as the page gets it: with its text, and its replies', rendered as GitHub would.
    A suggestion replaces the quoted lines."""
    quote = comment.get("target", {}).get("quote")
    replies = [{**r, "html": render(r.get("text", ""), quote)} for r in comment.get("replies", [])]
    rendered = {**comment, "html": render(comment.get("text", ""), quote)}
    return {**rendered, "replies": replies} if "replies" in comment else rendered


def versions(patch: str) -> list[dict[str, str | None]]:
    """The whole files, for highlighting. Without them the diff is still shown, just highlighted
    line by line."""
    try:
        return git.file_versions(patch)
    except GitError:
        return []


def newest_first(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reviews, newest first, each marked `latest` if no later review is from the same persona."""
    seen: set[str] = set()
    ordered = []
    for review in reversed(reviews):
        ordered.append({**review, "latest": review["persona"] not in seen})
        seen.add(review["persona"])
    return ordered


def placements(
    branch: str, commits: list[Commit], comments: list[dict[str, Any]], branch_patch: str
) -> list[tuple[dict[str, Any], str, dict[str, Any] | None]]:
    """Each page a comment is shown on, as (comment, page, target there). The target is None on
    the comment's own page. A comment on a diff line is also shown on the other page that has the
    same lines (see `mirror`), with a `mirror` link back to where it was made."""
    shas = [commit.sha for commit in commits]
    subjects = {commit.sha: commit.subject for commit in commits}
    placed: list[tuple[dict[str, Any], str, dict[str, Any] | None]] = []
    lines = [c for c in comments if c["target"]["kind"] == "line"]
    patches = {sha: read_patch(commit_patch(sha)) for sha in shas} if lines else {}
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


def findings(
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
                    patch = read_patch(commit_patch(commit))
                else:  # its commit has gone, so its lines can't be shown
                    patch = Patch({}, {})
                rows = _context(patch.files.get(target["file"], []), target)
            items.append({"comment": shown(comment), "rows": rows, "url": _url(branch, target)})
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
