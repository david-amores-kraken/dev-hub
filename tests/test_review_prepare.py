from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import fake_review_helpers, git

from dev_hub.diffs.git import list_commits
from dev_hub.diffs.store import add_comment, add_review, save_description
from dev_hub.review.prepare import prepare


def run_folder(repo: Path, final: bool = False) -> tuple[list[str], Path]:
    return prepare("feature/x", fake_review_helpers(), final=final, cwd=repo)


def meta_of(folder: Path) -> dict:
    return json.loads((folder / "meta.json").read_text())


def test_the_run_folder_has_what_the_personas_read(repo: Path, reviews: Path, skills: Path) -> None:
    save_description(
        "feature/x", "Add one and two", "Adds two files.\nSee https://app.asana.com/0/1/123"
    )
    personas, folder = run_folder(repo)

    assert folder.parent.parent == repo / ".claude" / "local" / "self-review"
    assert folder.parent.name == "branch-feature-x"
    assert "ux" not in personas and "correctness" in personas
    names = {p.name for p in folder.iterdir()}
    assert {
        "diff.patch", "changed-files.txt", "prior-findings.json", "user-comments.json",
        "pr.md", "pr-context.md", "meta.json", "brief.md", "prefs",
    } <= names  # fmt: skip

    diff = (folder / "diff.patch").read_text()
    assert "+++ b/one.txt" in diff and "later.txt" not in diff  # the branch's changes only
    assert (folder / "changed-files.txt").read_text().split() == ["one.txt", "two.txt"]
    pr = (folder / "pr.md").read_text()
    assert pr.startswith("# Add one and two")
    assert "Adds two files." in pr and "### " in pr and "Why one is needed." in pr
    assert (folder / "prefs" / "comment-preferences.md").read_text() == "no comments"

    meta = meta_of(folder)
    assert (meta["mode"], meta["branch"], meta["base"]) == ("local", "feature/x", "master")
    assert meta["commentable_lines"]["one.txt"]["RIGHT"] == [1]
    assert [c["subject"] for c in meta["commits"]] == ["Add one", "Add two"]
    assert meta["asana_tasks"] == [{"id": "123", "url": "https://app.asana.com/0/1/123"}]
    assert meta["first_run"] and meta["check_commit_messages"]


def test_the_title_falls_back_to_the_newest_commit_subject(
    repo: Path, reviews: Path, skills: Path
) -> None:
    _, folder = run_folder(repo)
    assert (folder / "pr.md").read_text().startswith("# Add two")
    assert "(not written yet)" in (folder / "pr.md").read_text()


def test_the_brief_posts_to_the_hub_and_says_the_review_is_local(
    repo: Path, reviews: Path, skills: Path
) -> None:
    _, folder = run_folder(repo)
    brief = (folder / "brief.md").read_text()
    assert "scripts/post.py" not in brief
    assert "-m dev_hub.review post <run folder> <your persona key>" in brief
    assert "This is a local review" in brief
    assert brief.startswith("# Self-review brief")


def test_a_brief_without_the_post_command_is_refused(
    repo: Path, reviews: Path, skills: Path
) -> None:
    (skills / "skills" / "self-review" / "reference" / "brief.md").write_text(
        "# Brief\n\nNothing.\n"
    )
    with pytest.raises(SystemExit, match="no longer has"):
        run_folder(repo)


def test_the_ux_persona_runs_when_users_see_the_change(
    repo: Path, reviews: Path, skills: Path
) -> None:
    personas, _ = prepare("feature/x", fake_review_helpers(user_facing=True), cwd=repo)
    assert "ux" in personas


def test_code_is_snapshotted_unless_the_checkout_is_the_branch(
    repo: Path, reviews: Path, skills: Path
) -> None:
    _, folder = run_folder(repo)  # the repo is on master
    assert not meta_of(folder)["checkout_is_head"]
    assert (folder / "head" / "one.txt").read_text() == "one\n"
    assert "NOT the branch tip" in (folder / "pr-context.md").read_text()

    git(repo, "switch", "-q", "feature/x")
    _, folder = run_folder(repo)
    assert meta_of(folder)["checkout_is_head"]
    assert not (folder / "head").exists()


def test_earlier_findings_and_my_comments_are_passed_on(
    repo: Path, reviews: Path, skills: Path
) -> None:
    one, _ = list_commits("feature/x")
    line = {
        "kind": "line",
        "commit": None,
        "file": "one.txt",
        "side": "new",
        "start": 1,
        "end": 1,
        "quote": "one",
    }
    add_comment("feature/x", line, "Why not a constant?")
    for n, triage in ((1, "address"), (2, "dismiss"), (3, None)):
        finding = add_comment(
            "feature/x", line, f"finding {n}", persona="correctness", author="🧠 Correctness",
            finding_id=f"CR-{n}", severity="nit", **({"triage": triage} if triage else {}),
        )  # fmt: skip
    add_review("feature/x", {"persona": "correctness", "sha": one.sha, "verdict": "comments"}, [])
    assert finding

    _, folder = run_folder(repo)
    prior = json.loads((folder / "prior-findings.json").read_text())
    assert [(f["id"], f["status"], f["where"]) for f in prior["findings"]] == [
        ("CR-1", "endorsed", "one.txt:1"),
        ("CR-2", "rejected", "one.txt:1"),
        ("CR-3", "pending", "one.txt:1"),
    ]
    assert prior["reviews"][0]["persona"] == "correctness"
    mine = json.loads((folder / "user-comments.json").read_text())
    assert [(c["path"], c["line"], c["body"]) for c in mine] == [
        ("one.txt", 1, "Why not a constant?")
    ]
    meta = meta_of(folder)
    assert not meta["first_run"]
    assert not meta["check_commit_messages"]
    assert meta_of(run_folder(repo, final=True)[1])["check_commit_messages"]


def test_unknown_branches_and_branches_with_nothing_ahead_are_refused(
    repo: Path, reviews: Path, skills: Path
) -> None:
    with pytest.raises(SystemExit, match="isn't a local branch"):
        prepare("nope", fake_review_helpers(), cwd=repo)
    with pytest.raises(SystemExit, match="has no commits"):
        prepare("master", fake_review_helpers(), cwd=repo)
