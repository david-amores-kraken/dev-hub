from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dev_hub.diffs.store import Description, load_description, review_file, save_description


def post(client: FlaskClient, base_url: str, url: str, payload: object) -> tuple[int, dict]:
    response = client.post(url, json=payload, base_url=base_url, headers={"Origin": base_url})
    return response.status_code, response.get_json()


def test_nothing_saved_means_an_empty_description(reviews: Path) -> None:
    assert load_description("feature/x") == Description("", "")


def test_a_saved_description_comes_back(reviews: Path) -> None:
    save_description("feature/x", "A title", "A body\n\nwith two paragraphs")
    assert load_description("feature/x") == Description("A title", "A body\n\nwith two paragraphs")


def test_each_branch_gets_its_own_file_inside_the_reviews_folder(reviews: Path) -> None:
    save_description("feature/x", "x", "")
    save_description("../../escape", "e", "")
    assert load_description("feature/x").title == "x"
    assert load_description("../../escape").title == "e"
    assert {p.parent for p in reviews.rglob("*.json")} == {reviews}
    assert review_file("feature/x").name == "feature%2Fx.json"


def test_saving_keeps_what_else_is_in_the_file(reviews: Path) -> None:
    review_file("feature/x").write_text(json.dumps({"comments": [1, 2], "pr": {"extra": True}}))
    save_description("feature/x", "t", "b")
    data = json.loads(review_file("feature/x").read_text())
    assert data == {"comments": [1, 2], "pr": {"extra": True, "title": "t", "body": "b"}}


def test_a_file_that_cant_be_read_is_never_overwritten(reviews: Path) -> None:
    review_file("feature/x").write_text("{not json")
    with pytest.raises(ValueError):
        save_description("feature/x", "t", "b")
    assert review_file("feature/x").read_text() == "{not json"


def test_the_overview_shows_the_saved_description_escaped(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    save_description("feature/x", "Fix <b>x</b>", "</textarea><script>alert(1)</script>")
    page = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    assert "Fix &lt;b&gt;x&lt;/b&gt;" in page
    assert "<script>alert(1)" not in page


def test_saving_through_the_page_writes_the_file(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    status, body = post(
        client, base_url, "/diffs/feature/x/description", {"title": "T", "body": "B"}
    )
    assert (status, body) == (200, {"ok": True})
    assert load_description("feature/x") == Description("T", "B")


@pytest.mark.parametrize(
    "payload",
    [
        "text",
        [],
        {},
        {"title": "t"},
        {"title": 1, "body": "b"},
        {"title": "t", "body": "x" * 100_001},
    ],
)
def test_bad_payloads_are_rejected_and_nothing_is_saved(
    repo: Path, client: FlaskClient, base_url: str, payload: object
) -> None:
    status, _ = post(client, base_url, "/diffs/feature/x/description", payload)
    assert status == 400
    assert not review_file("feature/x").exists()


def test_only_real_branches_can_be_saved_to(
    repo: Path, reviews: Path, client: FlaskClient, base_url: str
) -> None:
    status, _ = post(client, base_url, "/diffs/nope/description", {"title": "t", "body": "b"})
    assert status == 404
    assert list(reviews.iterdir()) == []


def test_saving_needs_the_hubs_own_origin(repo: Path, client: FlaskClient, base_url: str) -> None:
    response = client.post(
        "/diffs/feature/x/description", json={"title": "t", "body": "b"}, base_url=base_url
    )
    assert response.status_code == 403
    assert not review_file("feature/x").exists()


def test_saving_the_description_keeps_the_comments(reviews: Path) -> None:
    from dev_hub.diffs.store import add_comment, list_comments

    target = {"kind": "pr_body", "commit": None, "start": 1, "end": 1, "quote": "q"}
    add_comment("feature/x", target, "first")
    save_description("feature/x", "t", "b")
    assert [c["text"] for c in list_comments("feature/x")] == ["first"]


def test_preview_renders_markdown_without_saving(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    body = "## Why\n\n- one\n- **two**\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n~~old~~ `code`"
    status, data = post(client, base_url, "/diffs/feature/x/preview", {"body": body})
    assert status == 200
    html = data["html"]
    for part in (
        "<h2>Why</h2>",
        "<li><strong>two</strong></li>",
        "<table>",
        "<s>old</s>",
        "<code>code</code>",
    ):
        assert part in html
    assert not review_file("feature/x").exists()


def test_preview_does_not_let_the_description_run_code_or_load_anything(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    body = "<script>alert(1)</script> <img src=x onerror=alert(2)>\n\n[go](javascript:alert(3))\n\n![pic](http://evil.example/p.png)"
    _, data = post(client, base_url, "/diffs/feature/x/preview", {"body": body})
    html = data["html"]
    assert "<script" not in html
    assert "<img" not in html
    assert 'href="javascript' not in html


@pytest.mark.parametrize("payload", ["text", {}, {"body": 1}, {"body": "x" * 100_001}])
def test_preview_rejects_bad_payloads(
    repo: Path, client: FlaskClient, base_url: str, payload: object
) -> None:
    status, _ = post(client, base_url, "/diffs/feature/x/preview", payload)
    assert status == 400


def test_preview_needs_the_hubs_own_origin_and_a_real_branch(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    response = client.post("/diffs/feature/x/preview", json={"body": "b"}, base_url=base_url)
    assert response.status_code == 403
    status, _ = post(client, base_url, "/diffs/nope/preview", {"body": "b"})
    assert status == 404


def test_preview_box_class_cant_clash_with_the_diff_highlighter(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    # diff2html puts the language name on every code line, so a .md file's lines get the class
    # "markdown". Styling that class boxed each line of a .md diff.
    css = client.get("/diffs/static/diffs.css", base_url=base_url).get_data(as_text=True)
    assert ".markdown" not in css


def preview(client: FlaskClient, base_url: str, body: str) -> str:
    _, data = post(client, base_url, "/diffs/feature/x/preview", {"body": body})
    return data["html"]


def test_preview_keeps_details_and_summary_and_renders_markdown_inside(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    html = preview(
        client,
        base_url,
        "<details open>\n<summary>More <b>info</b></summary>\n\n- **one**\n\n</details>",
    )
    assert "<details open>" in html
    assert "<summary>More <b>info</b></summary>" in html
    assert "<li><strong>one</strong></li>" in html
    assert "</details>" in html


@pytest.mark.parametrize(
    "body",
    [
        "<details onclick=alert(1)>x</details>",
        "<summary style='x'>x</summary>",
        "<script>alert(1)</script>",
        "<a href='javascript:alert(1)'>x</a>",
        "<img src=x onerror=alert(1)>",
        "<iframe src=x></iframe>",
        "<b open>x</b>",
        "<details open/ onclick=x>",
    ],
)
def test_preview_only_lets_plain_allowed_tags_through(
    repo: Path, client: FlaskClient, base_url: str, body: str
) -> None:
    html = preview(client, base_url, body)
    # The attack text may show on the page as text (&lt;...), but never as a real tag.
    for bad in ("<script", "<iframe", "<img", "<a ", "<b open"):
        assert bad not in html
    assert not re.search(r"<[^>]*(onclick|onerror|style)=", html)


def test_preview_hides_html_comments(repo: Path, client: FlaskClient, base_url: str) -> None:
    assert "secret" not in preview(client, base_url, "<!-- secret -->\n\nShown")


def test_preview_turns_emoji_shortcodes_into_emoji(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    html = preview(client, base_url, ":rocket: :paperclip: :information_desk_person: :nope:")
    assert "🚀 📎 💁 :nope:" in html


def test_preview_leaves_emoji_lookalikes_and_code_alone(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    html = preview(client, base_url, "at 10:30:15 and a:b:c, `:rocket:`\n\n```\n:rocket:\n```")
    assert "10:30:15" in html
    assert "a:b:c" in html
    assert "🚀" not in html
