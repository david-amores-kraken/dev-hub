from __future__ import annotations

from pathlib import Path

import pytest

from dev_hub.diffs.git import (
    GitError,
    branch_patch,
    commit_patch,
    has_branch,
    list_branches,
    list_commits,
)


def test_only_branches_with_commits_the_base_lacks_are_listed(repo: Path) -> None:
    [branch] = list_branches()
    assert (branch.name, branch.commits, branch.subject) == ("feature/x", 2, "Add two")


def test_commits_come_oldest_first_with_their_whole_message(repo: Path) -> None:
    one, two = list_commits("feature/x")
    assert [one.subject, two.subject] == ["Add one", "Add two"]
    assert one.message == "Add one\n\nWhy one is needed."
    assert one.author == "Test Author"
    assert len(one.sha) == 40


def test_a_commit_patch_shows_only_that_commit(repo: Path) -> None:
    one, _ = list_commits("feature/x")
    patch = commit_patch(one.sha)
    assert "+++ b/one.txt" in patch
    assert "two.txt" not in patch


def test_the_branch_patch_ignores_what_the_base_did_since(repo: Path) -> None:
    patch = branch_patch("feature/x")
    assert "+++ b/one.txt" in patch
    assert "+++ b/two.txt" in patch
    assert "later.txt" not in patch


def test_has_branch_only_accepts_local_branches(repo: Path) -> None:
    assert has_branch("feature/x")
    assert not has_branch("nope")
    assert not has_branch("--all")
    assert not has_branch("HEAD")


def test_a_commit_patch_needs_a_full_sha(repo: Path) -> None:
    with pytest.raises(GitError):
        commit_patch("--output=/tmp/nope")


def test_git_errors_become_git_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_HUB_REPO", str(tmp_path / "missing"))
    with pytest.raises(GitError):
        list_branches()
