from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev_hub.diffs.store import add_comment, list_comments, load_description, save_description
from dev_hub.review.description import show, update


def test_the_title_and_description_are_read_and_written(repo: Path, reviews: Path) -> None:
    assert show("feature/x") == {"title": "", "body": ""}
    assert update("feature/x", "Add one and two", "First line.\n\nSecond.") == (
        "saved the title and description"
    )
    assert show("feature/x") == {"title": "Add one and two", "body": "First line.\n\nSecond."}


def test_leaving_one_out_keeps_it_and_the_comments_survive(repo: Path, reviews: Path) -> None:
    save_description("feature/x", "Old title", "Old body")
    target = {"kind": "pr_body", "commit": None, "start": 1, "end": 1, "quote": "Old body"}
    add_comment("feature/x", target, "a comment")
    assert update("feature/x", "New title", None) == "saved the title"
    assert load_description("feature/x").body == "Old body"
    assert update("feature/x", None, "New body") == "saved the description"
    assert show("feature/x") == {"title": "New title", "body": "New body"}
    assert [c["text"] for c in list_comments("feature/x")] == ["a comment"]


@pytest.mark.parametrize(
    ("title", "body", "message"),
    [
        (None, None, "give --title"),
        ("", None, "one non-empty line"),
        ("Two\nlines", None, "one non-empty line"),
        ("x" * 501, None, "one non-empty line"),
        (None, "x" * 100_001, "longer than"),
    ],
)
def test_bad_input_is_refused_and_nothing_changes(
    repo: Path, reviews: Path, title: str | None, body: str | None, message: str
) -> None:
    save_description("feature/x", "Keep", "Keep")
    with pytest.raises(SystemExit, match=message):
        update("feature/x", title, body)
    assert show("feature/x") == {"title": "Keep", "body": "Keep"}


def test_only_local_branches_can_be_written_to(repo: Path, reviews: Path) -> None:
    with pytest.raises(SystemExit, match="isn't a local branch"):
        update("nope", "T", "B")
    with pytest.raises(SystemExit, match="isn't a local branch"):
        show("nope")
    assert list(reviews.iterdir()) == []


def test_from_the_command_line_the_body_can_come_from_a_file_or_stdin(
    repo: Path, reviews: Path, tmp_path: Path
) -> None:
    env = {
        "DEV_HUB_REPO": str(repo), "DEV_HUB_BASE": "master", "DEV_HUB_REVIEWS": str(reviews),
        "PATH": "/usr/bin:/bin",
    }  # fmt: skip

    def run(*args: str, stdin: str | None = None) -> str:
        done = subprocess.run(
            [sys.executable, "-m", "dev_hub.review", "pr", *args],
            input=stdin, capture_output=True, text=True, check=True, env=env,
        )  # fmt: skip
        return done.stdout

    body_file = tmp_path / "body.md"
    body_file.write_text("From a file.\n")
    run("set", "feature/x", "--title", "T", "--body-file", str(body_file))
    assert json.loads(run("show", "feature/x")) == {"title": "T", "body": "From a file.\n"}
    run("set", "feature/x", "--body-file", "-", stdin="From stdin.\n")
    assert json.loads(run("show", "feature/x"))["body"] == "From stdin.\n"
    run("set", "feature/x", "--body", "Inline.")
    assert json.loads(run("show", "feature/x"))["body"] == "Inline."
