from __future__ import annotations

from pathlib import Path

import pytest
from helpers import commit, git

from dev_hub.diffs.git import branch_stats, list_commits
from dev_hub.diffs.store import add_comment, save_description
from dev_hub.review.facts import _rounds, facts

LINE = {
    "kind": "line",
    "commit": None,
    "file": "one.txt",
    "side": "new",
    "start": 1,
    "end": 1,
    "quote": "one",
}


def test_branch_stats_count_files_lines_and_commits(repo: Path) -> None:
    git(repo, "switch", "-q", "feature/x")
    (repo / "one.txt").write_text("one\nmore\n")
    (repo / "tests").mkdir()
    commit(repo, "tests/test_x.py", "a\nb\nc\n", "Add a test")
    stats = branch_stats("feature/x")
    assert stats["files"] == ["one.txt", "tests/test_x.py", "two.txt"]
    assert (stats["insertions"], stats["deletions"], stats["commits"]) == (5, 0, 3)
    assert stats["first_commit_at"]


def test_the_facts_hold_my_feedback_but_not_the_personas(repo: Path, reviews: Path) -> None:
    save_description("feature/x", "Add one and two", "Body")
    one, _ = list_commits("feature/x")
    add_comment("feature/x", LINE, "Why not a constant?")
    add_comment(
        "feature/x",
        {"kind": "pr_body", "commit": None, "start": 1, "end": 1, "quote": "Body"},
        "Say why",
    )
    add_comment(
        "feature/x",
        LINE,
        "a finding",
        finding_id="CR-1",
        persona="correctness",
        author="x",
        severity="nit",
    )

    result = facts("feature/x")
    pr = result["pr"]
    assert (pr["number"], pr["title"], pr["state"], pr["my_review_rounds"]) == (
        None,
        "Add one and two",
        "local",
        1,
    )
    [inline] = pr["my_inline_comments"]
    assert (inline["file"], inline["line"], inline["text"], inline["diff_hunk"]) == (
        "one.txt", 1, "Why not a constant?", "one",
    )  # fmt: skip
    [top] = pr["my_top_level_comments"]
    assert top["text"].startswith("(on the PR description: 'Body') Say why")
    assert result["work_shape"]["commits"] == 2
    assert result["work_shape"]["paths"] == ["one.txt", "two.txt"]
    assert one.sha  # the branch still has its commits


def test_comments_close_in_time_are_one_round() -> None:
    times = [
        "2026-01-01T10:00:00+00:00", "2026-01-01T10:20:00+00:00",  # one sitting
        "2026-01-01T12:00:00+00:00",  # another
        "2026-01-02T09:00:00+00:00", "2026-01-02T09:05:00+00:00",  # a third
    ]  # fmt: skip
    assert _rounds(times) == 3
    assert _rounds([]) == 0


def test_an_unknown_branch_is_refused(repo: Path, reviews: Path) -> None:
    with pytest.raises(SystemExit, match="isn't a local branch"):
        facts("nope")
