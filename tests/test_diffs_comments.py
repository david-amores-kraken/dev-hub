from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev_hub.diffs.comments import is_valid_text, on_page, open_counts, parse_target
from dev_hub.diffs.store import add_comment, delete_comment, list_comments, update_comment

SHA = "a" * 40
LINE = {"kind": "line", "commit": SHA, "file": "a.py", "side": "new", "start": 3, "end": 5}
MESSAGE = {"kind": "message", "commit": SHA, "start": 1, "end": 1}
BODY = {"kind": "pr_body", "commit": None, "start": 2, "end": 2}


def valid(target: dict[str, Any]) -> dict[str, Any]:
    return {**target, "quote": "some text"}


@pytest.mark.parametrize("target", [LINE, {**LINE, "commit": None}, MESSAGE, BODY])
def test_good_targets_are_kept(target: dict[str, Any]) -> None:
    assert parse_target(valid(target), {SHA}) == valid(target)


def test_unknown_keys_are_dropped() -> None:
    cleaned = parse_target({**valid(MESSAGE), "extra": 1, "file": "x"}, {SHA})
    assert cleaned == valid(MESSAGE)


@pytest.mark.parametrize(
    "target",
    [
        None,
        "line",
        {**valid(LINE), "kind": "other"},
        {**valid(LINE), "commit": "b" * 40},  # not a commit of the branch
        {**valid(LINE), "file": ""},
        {**valid(LINE), "file": 5},
        {**valid(LINE), "side": "left"},
        {**valid(LINE), "start": 0},
        {**valid(LINE), "start": 6},  # after the end
        {**valid(LINE), "start": True},
        {**valid(LINE), "end": "5"},
        {**valid(LINE), "quote": 1},
        {**valid(LINE), "quote": "x" * 20_001},
        {k: v for k, v in valid(LINE).items() if k != "quote"},
        {**valid(MESSAGE), "commit": None},  # a message belongs to a commit
        {**valid(BODY), "commit": SHA},  # the body belongs to the PR
    ],
)
def test_bad_targets_are_rejected(target: object) -> None:
    assert parse_target(target, {SHA}) is None


def test_comment_text_must_not_be_blank_or_huge() -> None:
    assert is_valid_text("fine")
    assert not is_valid_text("   \n")
    assert not is_valid_text(5)
    assert not is_valid_text("x" * 20_001)


def test_comments_are_added_changed_and_deleted(reviews: Path) -> None:
    first = add_comment("b", valid(LINE), "one")
    second = add_comment("b", valid(MESSAGE), "two")
    assert [c["text"] for c in list_comments("b")] == ["one", "two"]
    assert first["status"] == "open"
    assert first["id"] != second["id"]

    changed = update_comment("b", first["id"], text="one, edited")
    assert changed and (changed["text"], changed["status"]) == ("one, edited", "open")
    changed = update_comment("b", first["id"], status="resolved")
    assert changed and (changed["text"], changed["status"]) == ("one, edited", "resolved")
    assert update_comment("b", "nope", text="x") is None

    assert delete_comment("b", first["id"])
    assert not delete_comment("b", first["id"])
    assert [c["text"] for c in list_comments("b")] == ["two"]


def test_pages_get_their_own_comments_and_counts(reviews: Path) -> None:
    add_comment("b", valid(LINE), "line")
    add_comment("b", valid({**LINE, "commit": None}), "all changes")
    message = add_comment("b", valid(MESSAGE), "message")
    add_comment("b", valid(BODY), "body")
    update_comment("b", message["id"], status="resolved")
    comments = list_comments("b")
    shas = {SHA}

    def texts(page: str) -> list[str]:
        return [c["text"] for c in comments if on_page(c, page, shas)]

    assert texts(SHA) == ["line", "message"]
    assert texts("changes") == ["all changes"]
    assert texts("overview") == ["body"]
    # Resolved comments aren't counted.
    assert open_counts(comments, shas) == {SHA: 1, "changes": 1, "overview": 1}


def test_a_comment_on_a_commit_that_is_gone_goes_on_the_overview(reviews: Path) -> None:
    add_comment("b", valid(LINE), "lost line")
    add_comment("b", valid(MESSAGE), "lost message")
    comments = list_comments("b")
    shas = {"b" * 40}  # the branch no longer has SHA
    assert [c["text"] for c in comments if on_page(c, "overview", shas)] == [
        "lost line",
        "lost message",
    ]
    assert not [c for c in comments if on_page(c, SHA, shas)]
    assert open_counts(comments, shas) == {"overview": 2}
