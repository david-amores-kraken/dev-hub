from __future__ import annotations

from pathlib import Path

from flask.testing import FlaskClient

from dev_hub.features.store import get_feature, list_features, report_file

PLAN = "<html><head><title>Plan A</title></head><body></body></html>"
REPORT = "<html><head><title>Report: Plan A</title></head><body></body></html>"


def test_a_plan_and_a_report_with_the_same_name_are_one_feature(plans: Path, reports: Path) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    (reports / "a-branch.html").write_text(REPORT)
    [feature] = list_features()
    assert (feature.slug, feature.title) == ("a-branch", "Plan A")
    assert feature.has_plan
    assert feature.has_report


def test_a_feature_may_have_only_a_plan_or_only_a_report(plans: Path, reports: Path) -> None:
    (plans / "only-plan.html").write_text(PLAN)
    (reports / "only-report.html").write_text(REPORT)
    features = {f.slug: f for f in list_features()}
    assert (features["only-plan"].has_plan, features["only-plan"].has_report) == (True, False)
    assert (features["only-report"].has_plan, features["only-report"].has_report) == (False, True)
    assert features["only-report"].title == "Plan A"  # "Report:" is dropped from the title


def test_report_indexes_and_odd_slugs_are_not_features(plans: Path, reports: Path) -> None:
    (reports / "index.html").write_text("index")
    (reports / "a-branch.json").write_text("{}")
    assert list_features() == []
    assert get_feature("index") is None
    assert report_file("index") is None
    assert report_file("..") is None


def test_list_page_shows_each_feature_with_what_it_has(
    plans: Path, reports: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    (reports / "a-branch.html").write_text(REPORT)
    page = client.get("/features/", base_url=base_url).get_data(as_text=True)
    assert "/features/a-branch" in page
    assert 'href="/features/" ' in page  # nav
    assert "missing" not in page


def test_feature_page_shows_the_plan_first_and_the_report_on_request(
    plans: Path, reports: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    (reports / "a-branch.html").write_text(REPORT)
    page = client.get("/features/a-branch", base_url=base_url).get_data(as_text=True)
    assert 'src="/features/a-branch/plan/raw"' in page
    page = client.get("/features/a-branch?tab=report", base_url=base_url).get_data(as_text=True)
    assert 'src="/features/a-branch/report/raw"' in page


def test_feature_page_says_when_a_part_is_missing(
    plans: Path, reports: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    page = client.get("/features/a-branch?tab=report", base_url=base_url).get_data(as_text=True)
    assert "Report (none yet)" in page
    assert 'src="/features/a-branch/plan/raw"' in page  # falls back to what exists


def test_parts_are_sandboxed(
    plans: Path, reports: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    (reports / "a-branch.html").write_text(REPORT)
    for part in ("plan", "report"):
        response = client.get(f"/features/a-branch/{part}/raw", base_url=base_url)
        assert response.headers["Content-Security-Policy"].startswith("sandbox")


def test_unknown_features_parts_and_slugs_are_404(
    plans: Path, reports: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "a-branch.html").write_text(PLAN)
    (reports.parent / "secret.html").write_text("secret")
    for url in (
        "/features/nope",
        "/features/index",
        "/features/..%2Fsecret",
        "/features/a-branch/report/raw",  # a feature, but no report
        "/features/a-branch/other/raw",
    ):
        assert client.get(url, base_url=base_url).status_code == 404
