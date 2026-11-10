from __future__ import annotations

import json
from pathlib import Path

from flask.testing import FlaskClient

PLAN = "<!doctype html><html><head><title>Plan A</title></head><body><h1>Plan A</h1></body></html>"


def write_index(folder: Path, *entries: dict) -> None:
    (folder / "index.html").write_text(
        f'<html><script type="application/json" id="plans">{json.dumps(list(entries))}</script></html>'
    )


def test_lists_plans_from_the_index_newest_first(
    plans: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    (plans / "b-branch.html").write_text(PLAN)
    write_index(
        plans,
        {"file": "a-branch.html", "title": "Older plan", "updated": "2026-10-01T10:00"},
        {"file": "b-branch.html", "title": "Newer plan", "updated": "2026-11-01T10:00"},
        {"file": "gone.html", "title": "Deleted plan", "updated": "2026-12-01T10:00"},
    )
    page = client.get("/plans/", base_url=base_url).get_data(as_text=True)
    assert page.index("Newer plan") < page.index("Older plan")
    assert "Deleted plan" not in page  # listed but the file is missing


def test_a_plan_missing_from_the_index_is_still_listed(
    plans: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "stray.html").write_text(PLAN)
    page = client.get("/plans/", base_url=base_url).get_data(as_text=True)
    assert "Plan A" in page
    assert "/plans/stray" in page


def test_show_wraps_the_plan_in_the_hub(plans: Path, client: FlaskClient, base_url: str) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    page = client.get("/plans/a-branch", base_url=base_url).get_data(as_text=True)
    assert '<iframe class="plan"' in page
    assert 'href="/plans/" ' in page  # nav


def test_raw_plan_is_sandboxed_and_opens_links_in_a_new_tab(
    plans: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    response = client.get("/plans/a-branch/raw", base_url=base_url)
    assert response.headers["Content-Security-Policy"].startswith("sandbox")
    assert '<base target="_blank">' in response.get_data(as_text=True)


def test_unknown_and_odd_slugs_are_404(plans: Path, client: FlaskClient, base_url: str) -> None:
    (plans.parent / "secret.html").write_text("secret")
    (plans / "index.html").write_text("index")
    for slug in ("nope", "..%2Fsecret", "index", ".hidden"):
        assert client.get(f"/plans/{slug}", base_url=base_url).status_code == 404
        assert client.get(f"/plans/{slug}/raw", base_url=base_url).status_code == 404
