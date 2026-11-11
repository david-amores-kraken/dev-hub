from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev_hub.diffs.git import list_commits
from dev_hub.diffs.store import add_comment, list_comments, set_triage, update_comment
from dev_hub.review.todo import address, todo

LINE = {
    "kind": "line",
    "commit": None,
    "file": "one.txt",
    "side": "new",
    "start": 1,
    "end": 1,
    "quote": "one",
}


def finding(text: str, finding_id: str) -> dict:
    return add_comment(
        "feature/x",
        LINE,
        text,
        persona="tests",
        author="🧪 Tests",
        finding_id=finding_id,
        severity="nit",
    )


def test_todo_lists_my_open_comments_and_the_findings_i_said_to_address(
    repo: Path, reviews: Path
) -> None:
    one, _ = list_commits("feature/x")
    message = {"kind": "message", "commit": one.sha, "start": 1, "end": 1, "quote": "Add one"}
    add_comment("feature/x", message, "Reword this")
    mine_done = add_comment("feature/x", LINE, "Already done")
    update_comment("feature/x", mine_done["id"], status="resolved")
    unanswered = finding("not answered", "TS-1")
    chosen = finding("fix this", "TS-2")
    dismissed = finding("no thanks", "TS-3")
    set_triage("feature/x", chosen["id"], "address")
    set_triage("feature/x", dismissed["id"], "dismiss")
    assert unanswered

    result = todo("feature/x")
    assert result["branch"] == "feature/x"
    assert [(i["from"], i["text"]) for i in result["items"]] == [
        ("me", "Reword this"),
        ("🧪 Tests TS-2", "fix this"),
    ]
    first, second = result["items"]
    assert first["where"] == f"commit {one.sha[:7]} message"
    assert first["commit"] == "Add one"
    assert (second["where"], second["lines"], second["quote"], second["severity"]) == (
        "one.txt:1", [1, 1], "one", "nit",
    )  # fmt: skip


def test_addressing_a_comment_answers_it_and_takes_it_off_the_list(
    repo: Path, reviews: Path
) -> None:
    mine = add_comment("feature/x", LINE, "Use a constant")
    assert address("feature/x", mine["id"], "Done.", "abc1234", "TARS") == f"answered {mine['id']}"
    [saved] = list_comments("feature/x")
    assert saved["status"] == "resolved"
    assert [(r["author"], r["text"], r["commit"]) for r in saved["replies"]] == [
        ("TARS", "Done.", "abc1234")
    ]
    assert todo("feature/x")["items"] == []
    with pytest.raises(SystemExit, match="no comment"):
        address("feature/x", "nope", "x", None, "TARS")


def test_the_commands_work_from_the_command_line(
    repo: Path, reviews: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = add_comment("feature/x", LINE, "Use a constant")
    env = {
        "DEV_HUB_REPO": str(repo), "DEV_HUB_BASE": "master", "DEV_HUB_REVIEWS": str(reviews),
        "PATH": "/usr/bin:/bin",
    }  # fmt: skip

    def run(*args: str) -> str:
        done = subprocess.run(
            [sys.executable, "-m", "dev_hub.review", *args],
            capture_output=True, text=True, check=True, env=env,
        )  # fmt: skip
        return done.stdout

    assert json.loads(run("todo", "feature/x"))["items"][0]["id"] == mine["id"]
    run("address", "feature/x", mine["id"], "--reply", "Done.", "--as", "TARS")
    assert json.loads(run("todo", "feature/x"))["items"] == []
