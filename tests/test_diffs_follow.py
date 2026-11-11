from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from helpers import commit, git

from dev_hub.diffs.git import list_commits
from dev_hub.diffs.store import list_comments, review_file, save_description

LINES = [f"line {n}\n" for n in range(1, 11)]


@pytest.fixture
def topic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`topic` changes line 8 of f.txt. Then master adds three lines to the top of f.txt, so
    rebasing topic moves its change from line 8 to line 11."""
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "master")
    commit(folder, "f.txt", "".join(LINES), "Add f")
    git(folder, "switch", "-q", "-c", "topic")
    edited = [*LINES[:7], "EDITED\n", *LINES[8:]]
    commit(folder, "f.txt", "".join(edited), "Edit line 8\n\nThe body.")
    git(folder, "switch", "-q", "master")
    commit(folder, "f.txt", "new 1\nnew 2\nnew 3\n" + "".join(LINES), "Prepend")
    monkeypatch.setenv("DEV_HUB_REPO", str(folder))
    monkeypatch.setenv("DEV_HUB_BASE", "master")
    return folder


def rebase(folder: Path) -> None:
    git(folder, "switch", "-q", "topic")
    git(folder, "rebase", "-q", "master")


def comment(client: FlaskClient, base_url: str, target: dict[str, Any], text: str) -> None:
    response = client.post(
        "/diffs/topic/comments",
        json={"target": target, "text": text},
        base_url=base_url,
        headers={"Origin": base_url},
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def line_target(sha: str | None, start: int = 8, quote: str = "EDITED") -> dict[str, Any]:
    return {
        "kind": "line",
        "commit": sha,
        "file": "f.txt",
        "side": "new",
        "start": start,
        "end": start,
        "quote": quote,
    }


def shown(client: FlaskClient, base_url: str, page: str) -> list[dict[str, Any]]:
    html = client.get(f"/diffs/topic{page}", base_url=base_url).get_data(as_text=True)
    match = re.search(r'<script type="application/json" id="comments">(.*?)</script>', html, re.S)
    assert match
    return json.loads(match[1])


def where(comments: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    return [(c["text"], c["target"]["start"], c["target"]["end"]) for c in comments]


def test_a_rebased_commit_keeps_its_comments_on_the_new_sha_and_line(
    topic: Path, client: FlaskClient, base_url: str
) -> None:
    [before] = list_commits("topic")
    comment(client, base_url, line_target(before.sha), "about the edit")
    message = {"kind": "message", "commit": before.sha, "start": 3, "end": 3, "quote": "The body."}
    comment(client, base_url, message, "about the message")
    rebase(topic)
    [after] = list_commits("topic")
    assert after.sha != before.sha

    page = shown(client, base_url, f"/commits/{after.sha}")
    assert where(page) == [("about the edit", 11, 11), ("about the message", 3, 3)]
    assert {c["target"]["commit"] for c in page} == {after.sha}
    # It was saved, not just shown, and a second look changes nothing.
    assert [c["target"]["commit"] for c in list_comments("topic")] == [after.sha, after.sha]
    saved = review_file("topic").read_text()
    shown(client, base_url, f"/commits/{after.sha}")
    assert review_file("topic").read_text() == saved


def test_an_amended_commit_is_found_by_its_subject(
    topic: Path, client: FlaskClient, base_url: str
) -> None:
    [before] = list_commits("topic")
    comment(client, base_url, line_target(before.sha), "about the edit")
    git(topic, "switch", "-q", "topic")
    git(topic, "rebase", "-q", "master")
    commit(topic, "g.txt", "more\n", "tmp")
    git(topic, "reset", "-q", "--soft", "HEAD~1")
    git(topic, "commit", "-q", "--amend", "--no-edit")  # same subject, a new file as well
    [after] = list_commits("topic")

    assert where(shown(client, base_url, f"/commits/{after.sha}")) == [("about the edit", 11, 11)]


def test_a_comment_whose_commit_is_gone_waits_on_the_overview(
    topic: Path, client: FlaskClient, base_url: str
) -> None:
    [before] = list_commits("topic")
    comment(client, base_url, line_target(before.sha), "about the edit")
    git(topic, "switch", "-q", "topic")
    git(topic, "rebase", "-q", "master")
    (topic / "f.txt").write_text("something else entirely\n")
    git(topic, "commit", "-q", "-a", "--amend", "-m", "A different commit")
    [after] = list_commits("topic")

    assert shown(client, base_url, f"/commits/{after.sha}") == []
    [lost] = shown(client, base_url, "")
    assert lost["text"] == "about the edit"
    assert lost["target"]["commit"] == before.sha  # left as it was
    page = client.get("/diffs/topic", base_url=base_url).get_data(as_text=True)
    assert '<span class="pill open" title="Open comments">1</span>' in page


def test_all_changes_comments_follow_the_branch(
    topic: Path, client: FlaskClient, base_url: str
) -> None:
    comment(client, base_url, line_target(None), "on the branch")
    assert where(shown(client, base_url, "/changes")) == [("on the branch", 8, 8)]  # nothing moved
    rebase(topic)
    assert where(shown(client, base_url, "/changes")) == [("on the branch", 11, 11)]
    assert where(list_comments("topic")) == [("on the branch", 11, 11)]


def test_description_comments_follow_their_lines(
    topic: Path, client: FlaskClient, base_url: str
) -> None:
    save_description("topic", "T", "intro\nsecond\nthird")
    target = {"kind": "pr_body", "commit": None, "start": 2, "end": 2, "quote": "second"}
    comment(client, base_url, target, "about second")
    save_description("topic", "T", "new first line\nintro\nsecond\nthird")
    assert where(shown(client, base_url, "")) == [("about second", 3, 3)]
    save_description("topic", "T", "all different")
    assert where(shown(client, base_url, "")) == [("about second", 3, 3)]  # lost: left as it was
