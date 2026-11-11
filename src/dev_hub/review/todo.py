"""What the agent that acts on my review should do: list the comments, and answer them.

A comment is something to do when it is open and either I wrote it, or it is a persona's finding
that I marked "address". Findings I haven't answered, and ones I dismissed, are left alone.
"""

from __future__ import annotations

from typing import Any

from dev_hub.diffs import git
from dev_hub.diffs.store import add_reply, list_comments
from dev_hub.review.prepare import describe


def todo(branch: str) -> dict[str, Any]:
    """The comments to act on, oldest first, with where they are and what they were about."""
    subjects = {c.sha: c.subject for c in git.list_commits(branch)}
    items = []
    for comment in list_comments(branch):
        is_mine = not comment.get("finding_id")
        if comment["status"] != "open" or not (is_mine or comment.get("triage") == "address"):
            continue
        target = comment["target"]
        items.append(
            {
                "id": comment["id"],
                "from": "me" if is_mine else f"{comment['author']} {comment['finding_id']}",
                "severity": comment.get("severity"),
                "where": describe(target),
                "commit": subjects.get(target["commit"]) if target["commit"] else None,
                "lines": [target["start"], target["end"]],
                "quote": target["quote"],
                "text": comment["text"],
                "replies": comment.get("replies", []),
            }
        )
    return {"branch": branch, "items": items}


def address(branch: str, comment_id: str, reply: str, commit: str | None, author: str) -> str:
    """Answer a comment and mark it resolved."""
    if add_reply(branch, comment_id, author, reply, commit) is None:
        raise SystemExit(f"refusing: {branch!r} has no comment {comment_id!r}")
    return f"answered {comment_id}"
