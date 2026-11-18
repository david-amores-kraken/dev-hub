"""Render a hand-made report.json through the real templates."""

from __future__ import annotations

from typing import Any

from dev_hub.prs import store
from dev_hub.prs.report import rich

RUN = "20261110T010203Z-abc1234"


def make_report() -> dict[str, Any]:
    finding = {
        "severity": "should-fix",
        "status": "new",
        "agents": ["correctness", "tests"],
        "commits": ["abc1234"],
        "already_raised_by": ["reviewer"],
        "locations": [
            {
                "path": "src/a/b.py",
                "start": 4,
                "end": 9,
                "side": "head",
                "href": "https://github.com/o/r/pull/5/files#diff-1R4",
            }
        ],
        "items": [
            {
                "title": "Handles `None` badly <b>",
                "body": "See src/a/b.py:4-9 for the branch.",
                "agent": "correctness",
                "severity": "should-fix",
                "where": "b.py",
                "links": {"src/a/b.py:4-9": "https://github.com/o/r/pull/5/files#diff-1R4"},
            },
            {
                "title": "No test",
                "body": "Add one.",
                "agent": "tests",
                "severity": "question",
                "where": "",
            },
        ],
    }
    return {
        "meta": {
            "pr": 5,
            "repo": "o/r",
            "url": "https://github.com/o/r/pull/5",
            "title": "Fix the thing",
            "author": "someone",
            "sha": "abc1234def",
            "additions": 3,
            "deletions": 1,
            "draft": False,
            "tier": "standard",
            "tier_reason": "10 substantive lines in 2 files",
            "checks": {"available": True, "counts": {"pass": 3}},
            "reviews": [{"author": "x", "state": "APPROVED"}],
            "since_previous": None,
            "run_dir": "/tmp/run",
            "worktree": "/tmp/wt",
            "main_repo": "/tmp/repo",
        },
        "assembled": "20261110T010203Z",
        "cost": {
            "session": {"agent": "main session", "usd": 0.5, "seconds": 30},
            "agents": [{"agent": "review-tests", "usd": 1.25, "seconds": 70}],
            "total_usd": 1.75,
            "prepare_seconds": 20,
        },
        "goal": {
            "text": "Make `x` work",
            "links": {},
            "ticket": {
                "match": "yes",
                "summary": "Matches.",
                "tasks": [{"id": "1", "name": "Task", "url": "https://app.asana.com/0/1/2"}],
            },
        },
        "findings": [finding],
        "resolved": {
            "gone": [{"title": "Old", "agent": "naming", "severity": "nit", "why": "fixed"}]
        },
        "commits": [
            {
                "sha": "abc1234def",
                "short": "abc1234",
                "headline": "Fix it",
                "merge": False,
                "new": True,
                "what": "Fixes it",
                "reason": "40+ lines",
                "tier": "focus",
                "additions": 3,
                "deletions": 1,
                "findings": 1,
            }
        ],
        "threads": {
            "available": True,
            "resolved": 1,
            "open": [
                {
                    "url": "https://github.com/o/r/pull/5#r1",
                    "reviewer": "x",
                    "path": "a.py",
                    "line": 3,
                    "author_replied": False,
                    "replies": 0,
                    "outdated": True,
                    "excerpt": "why?",
                }
            ],
        },
        "agents": {
            "correctness": {"ran": True, "summary": "Checked branches.", "findings": 1},
            "tests": {"ran": False, "summary": "", "findings": 0},
        },
        "notes": {"correctness": ["Did not read the migration."]},
        "problems": ["The naming agent wrote no output."],
    }


def test_report_renders(pr_home, prs_client) -> None:
    store.write_json(store.RUNS / "pr5" / RUN / "report.json", make_report())
    page = prs_client.get(f"/prs/5/{RUN}").get_data(as_text=True)
    assert "Fix the thing" in page
    assert "<code>None</code>" in page  # backticks become code
    assert "&lt;b&gt;" in page  # agent text is escaped
    assert 'href="https://github.com/o/r/pull/5/files#diff-1R4">src/a/b.py:4-9</a>' in page
    assert "already raised by @reviewer" in page
    assert "estimated spend $1.75" in page
    assert "Gone since the last brief (1)" in page
    assert "no reply" in page and "outdated" in page


def test_latest_report_redirects(pr_home, prs_client) -> None:
    store.write_json(store.RUNS / "pr5" / RUN / "report.json", make_report())
    response = prs_client.get("/prs/5")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/prs/5/{RUN}")


def test_unknown_or_odd_run_is_404(prs_client) -> None:
    assert prs_client.get("/prs/5/nope").status_code == 404
    assert prs_client.get("/prs/5/..%2F..").status_code == 404


def test_rich_only_links_resolved_references() -> None:
    text = str(rich("a.py:3 and b.py:4", {"a.py:3": "https://x/y"}))
    assert '<a href="https://x/y">a.py:3</a>' in text
    assert "b.py:4" in text and "<a" not in text.split("and")[1]
