from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from dev_hub.diffs.git import list_commits, patch_id
from dev_hub.diffs.store import list_comments


def post(client: FlaskClient, base_url: str, url: str, payload: object) -> tuple[int, Any]:
    response = client.post(url, json=payload, base_url=base_url, headers={"Origin": base_url})
    return response.status_code, response.get_json()


def line_target(commit: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "line",
        "commit": commit,
        "file": "one.txt",
        "side": "new",
        "start": 1,
        "end": 1,
        "quote": "one",
    } | extra


def comments_in(client: FlaskClient, base_url: str, url: str) -> list[dict[str, Any]]:
    page = client.get(url, base_url=base_url).get_data(as_text=True)
    match = re.search(r'<script type="application/json" id="comments">(.*?)</script>', page, re.S)
    assert match
    return json.loads(match[1])


def test_a_line_comment_is_saved_with_the_commit_it_was_made_on(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    status, comment = post(
        client,
        base_url,
        "/diffs/feature/x/comments",
        {"target": line_target(one.sha), "text": "Why this?"},
    )
    assert status == 200
    assert (comment["status"], comment["text"]) == ("open", "Why this?")
    assert comment["target"]["subject"] == "Add one"
    assert comment["target"]["patch_id"] == patch_id(one.sha)
    assert comment.pop("html") == "<p>Why this?</p>\n"  # shown, not saved
    assert list_comments("feature/x") == [comment]


def test_message_and_description_comments_can_be_added(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    message = {"kind": "message", "commit": one.sha, "start": 3, "end": 3, "quote": "Why"}
    body = {"kind": "pr_body", "commit": None, "start": 1, "end": 2, "quote": "a\nb"}
    for target in (message, body):
        status, _ = post(
            client, base_url, "/diffs/feature/x/comments", {"target": target, "text": "hm"}
        )
        assert status == 200


def test_bad_comments_are_rejected(repo: Path, client: FlaskClient, base_url: str) -> None:
    one, _ = list_commits("feature/x")
    url = "/diffs/feature/x/comments"
    for payload in (
        {"target": line_target("b" * 40), "text": "x"},  # not a commit of this branch
        {"target": line_target(one.sha, side="left"), "text": "x"},
        {"target": line_target(one.sha), "text": "   "},
        {"target": line_target(one.sha)},
        {"text": "x"},
        [],
    ):
        assert post(client, base_url, url, payload)[0] == 400, payload
    assert list_comments("feature/x") == []
    assert post(client, base_url, "/diffs/nope/comments", {})[0] == 404


def test_a_comment_can_be_edited_resolved_reopened_and_deleted(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    _, comment = post(
        client,
        base_url,
        "/diffs/feature/x/comments",
        {"target": line_target(None), "text": "first"},
    )
    url = f"/diffs/feature/x/comments/{comment['id']}"
    assert post(client, base_url, url, {"text": "second"})[1]["text"] == "second"
    assert post(client, base_url, url, {"status": "resolved"})[1]["status"] == "resolved"
    assert post(client, base_url, url, {"status": "open"})[1]["status"] == "open"
    assert post(client, base_url, url, {"status": "done"})[0] == 400
    assert post(client, base_url, url, {"text": ""})[0] == 400
    assert list_comments("feature/x")[0]["text"] == "second"

    assert post(client, base_url, f"{url}/delete", {})[0] == 200
    assert post(client, base_url, f"{url}/delete", {})[0] == 404
    assert post(client, base_url, url, {"text": "x"})[0] == 404
    assert list_comments("feature/x") == []


def test_commenting_needs_the_hubs_own_origin(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    response = client.post(
        "/diffs/feature/x/comments",
        json={"target": line_target(one.sha), "text": "x"},
        base_url=base_url,
    )
    assert response.status_code == 403
    assert list_comments("feature/x") == []


def test_a_finding_can_be_marked_address_or_dismiss_and_cleared(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    from dev_hub.diffs.store import add_comment

    target = line_target(None)
    finding = add_comment("feature/x", target, "off by one", finding_id="CR-1", severity="blocker")
    url = f"/diffs/feature/x/comments/{finding['id']}"
    assert post(client, base_url, url, {"triage": "address"})[1]["triage"] == "address"
    assert post(client, base_url, url, {"triage": "dismiss"})[1]["triage"] == "dismiss"
    assert "triage" not in post(client, base_url, url, {"triage": None})[1]
    assert post(client, base_url, url, {"triage": "maybe"})[0] == 400
    assert list_comments("feature/x")[0].get("triage") is None


def test_the_overview_lists_reviews_newest_first_and_opens_the_latest_per_persona(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    from dev_hub.diffs.store import add_review

    base = {"name": "Correctness", "emoji": "🧠", "sha": "a" * 40, "findings": [], "resolved": []}
    add_review(
        "feature/x",
        {**base, "persona": "correctness", "verdict": "lgtm", "summary": "First pass <b>fine</b>."},
        [],
    )
    add_review(
        "feature/x",
        {
            **base,
            "persona": "correctness",
            "verdict": "comments",
            "summary": "Second pass.",
            "findings": ["CR-1"],
            "unplaced": [
                {
                    "finding_id": "CR-1",
                    "severity": "nit",
                    "where": "src/x.py",
                    "body": "Outside the diff.",
                }
            ],
        },
        [],
    )
    page = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    assert page.index("Second pass.") < page.index("First pass")
    assert page.count('<details class="review" open>') == 1
    assert "First pass &lt;b&gt;fine&lt;/b&gt;." in page
    assert "Outside the diff." in page


def test_a_comment_is_shown_as_markdown_and_its_suggestion_replaces_the_quoted_lines(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    text = "Use **two**.\n\n```suggestion\ntwo <b>\n```"
    post(
        client,
        base_url,
        "/diffs/feature/x/comments",
        {"target": line_target(one.sha), "text": text},
    )
    [comment] = comments_in(client, base_url, f"/diffs/feature/x/commits/{one.sha}")
    assert "<strong>two</strong>" in comment["html"]
    assert "Suggested change" in comment["html"]
    assert '<div class="del">one</div><div class="add">two &lt;b&gt;</div>' in comment["html"]


def test_an_empty_suggestion_removes_the_quoted_lines(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    target = line_target(one.sha)
    post(
        client,
        base_url,
        "/diffs/feature/x/comments",
        {"target": target, "text": "```suggestion\n```"},
    )
    [comment] = comments_in(client, base_url, f"/diffs/feature/x/commits/{one.sha}")
    assert '<div class="suggestion-lines"><div class="del">one</div></div>' in comment["html"]


def test_a_review_lists_its_findings_with_the_diff_lines_they_are_about(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    from dev_hub.diffs.store import add_comment, add_review

    finding = add_comment(
        "feature/x", line_target(None), "Why one?", persona="correctness", finding_id="CR-1"
    )
    gone = add_comment(
        "feature/x",
        line_target(None, quote="not there"),
        "Old news",
        persona="correctness",
        finding_id="CR-2",
    )
    add_comment(
        "feature/x", line_target(None), "Not this review", persona="tests", finding_id="TS-1"
    )
    review = {"persona": "correctness", "name": "Correctness", "emoji": "🧠", "sha": "a" * 40}
    add_review(
        "feature/x",
        {**review, "verdict": "comments", "summary": "S.", "findings": ["CR-1", "CR-2"]},
        [],
    )
    page = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    match = re.search(r'id="review-comments">(.*?)</script>', page, re.S)
    assert match
    assert [c["id"] for c in json.loads(match[1])] == [finding["id"], gone["id"]]
    assert f'data-comment="{finding["id"]}"' in page
    assert '<tr class="add chosen"><td class="num"></td><td class="num">1</td>' in page
    assert page.count('<span class="pill">Outdated</span>') == 1
