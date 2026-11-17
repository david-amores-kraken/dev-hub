"""A comment on a commit's diff is also shown on "All changes", and the reverse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers import commit, git

from dev_hub.diffs.anchors import Row, map_line, read_patch
from dev_hub.diffs.git import branch_patch, commit_patch, list_commits
from dev_hub.diffs.mirror import mirror

LETTERS = "".join(f"{c}\n" for c in "abcdefghij")


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """f.txt is a..j on master. The branch then:
    1. adds x after b, and drops e,
    2. adds y1, y2 at the top, and changes h to H,
    3. renames f.txt to g.txt."""
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "master")
    commit(folder, "f.txt", LETTERS, "Add letters")
    git(folder, "switch", "-q", "-c", "b")
    commit(folder, "f.txt", LETTERS.replace("b\n", "b\nx\n").replace("e\n", ""), "Add x")
    text = "y1\ny2\n" + (folder / "f.txt").read_text().replace("h\n", "H\n")
    commit(folder, "f.txt", text, "Add y")
    git(folder, "mv", "f.txt", "g.txt")
    git(folder, "commit", "-q", "-m", "Rename")
    monkeypatch.setenv("DEV_HUB_REPO", str(folder))
    monkeypatch.setenv("DEV_HUB_BASE", "master")
    return folder


def where(target: dict[str, Any]) -> dict[str, Any] | None:
    commits = list_commits("b")
    shas = [c.sha for c in commits]
    patches = {sha: read_patch(commit_patch(sha)) for sha in shas}
    found = mirror(target, shas, patches, read_patch(branch_patch("b")))
    names = {c.sha: c.subject for c in commits}
    if found and found["commit"]:
        found["commit"] = names[found["commit"]]
    return found


def line(commit: str | None, file: str, start: int, quote: str, side: str = "new") -> dict:
    lines = quote.count("\n")
    return {
        "kind": "line",
        "commit": commit,
        "file": file,
        "side": side,
        "start": start,
        "end": start + lines,
        "quote": quote,
    }


def sha(subject: str) -> str:
    return next(c.sha for c in list_commits("b") if c.subject == subject)


def test_a_commit_comment_follows_its_lines_through_later_commits(history: Path) -> None:
    # x is line 3 in "Add x"; "Add y" puts two lines above it, and the rename moves the file.
    found = where(line(sha("Add x"), "f.txt", 3, "x"))
    assert found == line(None, "g.txt", 5, "x")


def test_an_all_changes_comment_goes_to_the_commit_that_added_its_lines(history: Path) -> None:
    assert where(line(None, "g.txt", 5, "x")) == line("Add x", "f.txt", 3, "x")
    assert where(line(None, "g.txt", 1, "y1\ny2")) == line("Add y", "f.txt", 1, "y1\ny2")


def test_a_range_goes_to_the_newest_commit_that_added_any_of_it(history: Path) -> None:
    # x (Add x) and c (the base) are both shown in "Add y", which added none of them.
    assert where(line(None, "g.txt", 5, "x\nc")) == line("Add x", "f.txt", 3, "x\nc")


def test_removed_lines_go_to_the_commit_that_removed_them(history: Path) -> None:
    assert where(line(None, "g.txt", 5, "e", side="old")) == line(
        "Add x", "f.txt", 5, "e", side="old"
    )
    assert where(line(sha("Add x"), "f.txt", 5, "e", side="old")) == line(
        None, "g.txt", 5, "e", side="old"
    )


def test_lines_a_later_commit_changed_stay_on_their_own_page(history: Path) -> None:
    # h is line 8 after "Add x", and "Add y" turns it into H.
    assert where(line(sha("Add x"), "f.txt", 8, "h")) is None


def test_lines_from_the_base_that_no_commit_changed_stay_on_all_changes(history: Path) -> None:
    assert where(line(None, "g.txt", 3, "a")) is None


def test_other_comments_have_no_second_page(history: Path) -> None:
    message = {"kind": "message", "commit": sha("Add x"), "start": 1, "end": 1, "quote": "Add x"}
    assert where(message) is None
    assert where(line(None, "g.txt", 5, "not x")) is None


def test_a_line_number_maps_across_a_diff_both_ways() -> None:
    rows = [
        Row(1, 1, "keep"),
        Row(2, None, "gone"),
        Row(None, 2, "new"),
        Row(None, 3, "new too"),
        Row(3, 4, "keep"),
    ]
    assert [map_line(rows, n, "old") for n in (1, 2, 3, 10)] == [1, None, 4, 11]
    assert [map_line(rows, n, "new") for n in (1, 2, 3, 4, 11)] == [1, None, None, 3, 10]


def test_a_renamed_file_keeps_both_names() -> None:
    patch = "diff --git a/a b/b\nsimilarity index 100%\nrename from a\nrename to b\n"
    assert read_patch(patch).names == {"b": ("a", "b")}
