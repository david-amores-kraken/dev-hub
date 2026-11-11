from __future__ import annotations

from pathlib import Path

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
