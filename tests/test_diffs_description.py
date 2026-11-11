from __future__ import annotations

import json
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
