"""The facts about a branch's review that the feature report uses, in the shape its facts.py wants.

The feature skill's report records the feedback I gave. On a PR that came from GitHub comments;
here it comes from the review file: the comments I wrote (not the personas' findings, which are
not my feedback), and how big the change is.
"""

from __future__ import annotations

from typing import Any

from dev_hub.diffs import git
from dev_hub.diffs.store import list_comments, load_description
from dev_hub.review.prepare import hub_url

# Comments within this many minutes of each other belong to one round of review.
ROUND_GAP_MINUTES = 30


def facts(branch: str) -> dict[str, Any]:
    if not git.has_branch(branch):
        raise SystemExit(f"refusing: {branch!r} isn't a local branch")
    description = load_description(branch)
    mine = [c for c in list_comments(branch) if not c.get("finding_id")]
    on_code = [c for c in mine if c["target"]["kind"] == "line"]
    on_text = [c for c in mine if c["target"]["kind"] != "line"]
    stats = git.branch_stats(branch)
    is_test = lambda path: "/tests/" in path or path.rsplit("/", 1)[-1].startswith("test_")  # noqa: E731
    return {
        "pr": {
            "number": None,
            "url": hub_url(branch),
            "title": description.title or branch,
            "state": "local",
            "body": description.body,
            "me": "me",
            "my_review_rounds": _rounds([c["created"] for c in mine]),
            "my_inline_comments": [
                {
                    "id": c["id"],
                    "at": c["created"],
                    "file": c["target"]["file"],
                    "line": c["target"]["end"],
                    "text": c["text"],
                    "reply": False,
                    "diff_hunk": c["target"]["quote"][-400:],
                }
                for c in on_code
            ],
            # Comments on a commit message or the description have no file or line.
            "my_top_level_comments": [
                {"id": c["id"], "at": c["created"], "text": _with_where(c)} for c in on_text
            ],
        },
        "work_shape": {
            "commits": stats["commits"],
            "files": len(stats["files"]),
            "test_files": sum(is_test(f) for f in stats["files"]),
            "insertions": stats["insertions"],
            "deletions": stats["deletions"],
            "first_commit_at": stats["first_commit_at"],
            "paths": stats["files"],
        },
    }


def _with_where(comment: dict[str, Any]) -> str:
    target = comment["target"]
    where = "the PR description" if target["kind"] == "pr_body" else "a commit message"
    return f"(on {where}: {target['quote'][:200]!r}) {comment['text']}"


def _rounds(times: list[str]) -> int:
    """How many separate sittings the comments were written in."""
    from datetime import datetime

    moments = sorted(datetime.fromisoformat(t) for t in times)
    rounds = 0
    for earlier, later in zip([None, *moments], moments, strict=False):
        if earlier is None or (later - earlier).total_seconds() > ROUND_GAP_MINUTES * 60:
            rounds += 1
    return rounds
