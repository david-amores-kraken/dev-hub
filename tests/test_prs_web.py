from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dev_hub.prs import store


def queue_item(number: int = 1, **extra: object) -> dict:
    return {
        "number": number,
        "title": "Add a thing",
        "author": "someone",
        "url": f"https://github.com/octoenergy/kraken-core/pull/{number}",
        "updated_at": "2026-11-09T10:00:00Z",
        "requested_via": ["you"],
        "additions": 10,
        "deletions": 2,
        "changed_files": 1,
        "suggested": "light",
        "reason": "12 changed lines in 1 files",
        **extra,
    }


def save_queue(*items: dict) -> None:
    store.write_json(store.QUEUE, {"refreshed": "2026-11-09T10:00:00Z", "items": list(items)})


def post(prs_client: FlaskClient, path: str, body: object):
    return prs_client.post(f"/prs{path}", json=body)


def test_index_lists_a_waiting_pr(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7))
    page = prs_client.get("/prs/").get_data(as_text=True)
    assert "#7" in page
    assert '<option value="light" selected>' in " ".join(page.split())
    assert "up to $" not in page
    assert "asked of" not in page
    assert 'data-status="waiting"' in page


def test_titles_are_escaped(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7, title="<script>alert(1)</script>"))
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    assert "<script>alert" not in page


def test_brief_rejects_unknown_pr_and_tier(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7))
    assert post(prs_client, "/api/brief", {"pr": 8, "tier": "light"}).status_code == 404
    assert post(prs_client, "/api/brief", {"pr": 7, "tier": "huge"}).status_code == 400


def test_brief_writes_a_request(
    prs_client: FlaskClient, monkeypatch: pytest.MonkeyPatch, pr_home: Path
) -> None:
    started: list[str] = []
    monkeypatch.setattr("dev_hub.prs.views.start_poller", started.append)
    save_queue(queue_item(7))
    response = post(prs_client, "/api/brief", {"pr": 7, "tier": "large"})
    assert response.status_code == 202
    assert json.loads((pr_home / "requests" / "7.json").read_text())["tier"] == "large"
    assert started == ["--requests-only"]
    again = post(prs_client, "/api/brief", {"pr": 7, "tier": "large"})
    assert again.status_code == 409


def test_marking_hides_a_pr_from_the_open_group(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7))
    assert post(prs_client, "/api/mark", {"pr": 7, "state": "skipped"}).status_code == 200
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    assert 'data-status="skipped" data-group="done"' in page
    assert post(prs_client, "/api/mark", {"pr": 7, "state": None}).status_code == 200
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    assert 'data-status="waiting"' in page


def test_removed_brief_is_remembered(prs_client: FlaskClient) -> None:
    store.write_json(
        store.HISTORY,
        {
            "9": {
                "pr": 9,
                "title": "Old one",
                "author": "x",
                "url": None,
                "tier": "standard",
                "briefed_at": "20261001T000000Z",
                "findings": {"blocker": 1, "should-fix": 0, "question": 0, "nit": 2},
            }
        },
    )
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    assert 'data-status="archived"' in page
    assert "blocker" not in page


def test_index_shows_author_and_both_dates(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7, author="teammate-one", created_at="2026-11-01T08:30:00Z"))
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    assert '<td class="author">teammate-one</td>' in page
    assert "2026-11-01" in page
    assert "2026-11-09" in page
    assert 'data-created="2026-11-01T08:30:00Z"' in page
    assert 'data-updated="2026-11-09T10:00:00Z"' in page


def test_rows_know_if_the_author_is_in_the_team(prs_client: FlaskClient) -> None:
    save_queue(queue_item(1, author="teammate-two"), queue_item(2, author="stranger"))
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    assert 'data-pr="1" data-status="waiting" data-group="todo"\n    data-team="core"' in page
    assert 'data-pr="2" data-status="waiting" data-group="todo"\n    data-team="other"' in page


def test_add_by_link_puts_the_pr_in_the_list(
    prs_client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pr = {
        "number": 55,
        "title": "Not mine to review",
        "author": {"login": "stranger"},
        "createdAt": "2026-11-02T00:00:00Z",
        "updatedAt": "2026-11-03T00:00:00Z",
        "url": "https://github.com/octoenergy/kraken-core/pull/55",
        "isDraft": False,
        "state": "OPEN",
    }
    queued: list[int] = []
    monkeypatch.setattr("dev_hub.prs.views.fetch_pr", lambda number, config: pr)
    monkeypatch.setattr(
        "dev_hub.prs.views.add_to_queue", lambda p, config: queued.append(p["number"])
    )
    store.set_mark(55, "skipped")
    response = post(
        prs_client, "/api/add", {"link": "https://github.com/octoenergy/kraken-core/pull/55/files"}
    )
    assert response.status_code == 201
    assert queued == [55]
    assert store.read_manual() == [55]
    assert 55 not in store.read_marks()


def test_add_rejects_other_repos_and_closed_prs(
    prs_client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = post(prs_client, "/api/add", {"link": "https://github.com/someone/else/pull/5"})
    assert other.status_code == 400
    assert post(prs_client, "/api/add", {"link": "nonsense"}).status_code == 400
    monkeypatch.setattr(
        "dev_hub.prs.views.fetch_pr", lambda number, config: {"number": number, "state": "MERGED"}
    )
    assert post(prs_client, "/api/add", {"link": "#5"}).status_code == 409
    assert store.read_manual() == []


def test_ready_briefs_come_first(prs_client: FlaskClient) -> None:
    save_queue(
        queue_item(1, updated_at="2026-11-12T10:00:00Z"),
        queue_item(2, updated_at="2026-11-01T10:00:00Z"),
        queue_item(3, updated_at="2026-11-11T10:00:00Z"),
    )
    report = {"meta": {}, "assembled": "20261102T000000Z"}
    store.write_json(store.RUNS / "pr2" / "20261102T000000Z" / "report.json", report)
    page = prs_client.get("/prs/rows").get_data(as_text=True)
    order = [page.index(f'data-pr="{n}" data-status') for n in (2, 1, 3)]
    assert order == sorted(order)


def test_brief_keeps_the_focus_the_user_typed(
    prs_client: FlaskClient, monkeypatch: pytest.MonkeyPatch, pr_home: Path
) -> None:
    monkeypatch.setattr("dev_hub.prs.views.start_poller", lambda flag: None)
    save_queue(queue_item(7), queue_item(8))
    body = {"pr": 7, "tier": "standard", "focus": "  Check the migration.  "}
    assert post(prs_client, "/api/brief", body).status_code == 202
    assert json.loads((pr_home / "requests" / "7.json").read_text())["focus"] == (
        "Check the migration."
    )
    assert (
        post(prs_client, "/api/brief", {"pr": 8, "tier": "light", "focus": " "}).status_code == 202
    )
    assert "focus" not in json.loads((pr_home / "requests" / "8.json").read_text())


def test_brief_rejects_a_focus_that_isnt_short_text(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7))
    for focus in (["a list"], "x" * 2001):
        body = {"pr": 7, "tier": "light", "focus": focus}
        assert post(prs_client, "/api/brief", body).status_code == 400


def test_index_has_the_brief_dialog(prs_client: FlaskClient) -> None:
    save_queue(queue_item(7))
    page = prs_client.get("/prs/").get_data(as_text=True)
    assert '<dialog id="brief-dialog"' in page
    assert 'data-focus=""' in page
