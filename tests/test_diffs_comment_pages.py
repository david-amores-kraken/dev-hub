from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from dev_hub.diffs.git import list_commits
from dev_hub.diffs.store import save_description


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


def test_each_page_gets_only_its_own_comments(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, two = list_commits("feature/x")
    url = "/diffs/feature/x/comments"
    body = {"kind": "pr_body", "commit": None, "start": 1, "end": 1, "quote": "q"}
    for target, text in (
        (line_target(one.sha), "on one"),
        (line_target(two.sha), "on two"),
        (line_target(None), "on all changes"),
        (body, "on the description"),
    ):
        post(client, base_url, url, {"target": target, "text": text})

    def texts(page: str) -> list[str]:
        return [c["text"] for c in comments_in(client, base_url, f"/diffs/feature/x{page}")]

    assert texts(f"/commits/{one.sha}") == ["on one"]
    assert texts(f"/commits/{two.sha}") == ["on two"]
    assert texts("/changes") == ["on all changes"]
    assert texts("") == ["on the description"]


def test_open_comments_are_counted_in_the_list_of_parts(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    url = "/diffs/feature/x/comments"
    _, first = post(client, base_url, url, {"target": line_target(one.sha), "text": "a"})
    post(client, base_url, url, {"target": line_target(one.sha), "text": "b"})
    page = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    assert '<span class="pill open" title="Open comments">2</span>' in page
    post(client, base_url, f"{url}/{first['id']}", {"status": "resolved"})
    page = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    assert '<span class="pill open" title="Open comments">1</span>' in page


def test_a_commit_page_carries_its_message_for_commenting_and_the_description_its_body(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    page = client.get(f"/diffs/feature/x/commits/{one.sha}", base_url=base_url).get_data(
        as_text=True
    )
    assert 'data-kind="message" data-text="Add one\n\nWhy one is needed."' in page
    save_description("feature/x", "T", "<b>line</b>\nline two")
    page = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    assert 'data-text="&lt;b&gt;line&lt;/b&gt;\nline two"' in page
