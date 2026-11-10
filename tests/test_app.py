from __future__ import annotations

from flask.testing import FlaskClient


def test_root_goes_to_the_pr_section(client: FlaskClient, base_url: str) -> None:
    response = client.get("/", base_url=base_url)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/prs/")


def test_nav_lists_every_section_and_marks_the_current_one(
    client: FlaskClient, base_url: str
) -> None:
    page = client.get("/plans/", base_url=base_url).get_data(as_text=True)
    assert 'href="/prs/"' in page
    assert 'href="/plans/" aria-current="page"' in page


def test_pr_section_renders_inside_the_hub(client: FlaskClient, base_url: str) -> None:
    page = client.get("/prs/", base_url=base_url).get_data(as_text=True)
    assert "dev hub" in page
    assert "PR briefs" in page


def test_rejects_other_hosts(client: FlaskClient) -> None:
    assert client.get("/prs/", base_url="http://evil.example").status_code == 403


def test_post_needs_own_origin_and_json(client: FlaskClient, base_url: str) -> None:
    body = {"pr": 1, "state": "reviewed"}
    assert client.post("/prs/api/mark", json=body, base_url=base_url).status_code == 403
    bad = client.post(
        "/prs/api/mark", json=body, base_url=base_url, headers={"Origin": "http://evil.example"}
    )
    assert bad.status_code == 403
    form = client.post("/prs/api/mark", data=body, base_url=base_url, headers={"Origin": base_url})
    assert form.status_code == 403
    ok = client.post("/prs/api/mark", json=body, base_url=base_url, headers={"Origin": base_url})
    assert ok.status_code == 200
