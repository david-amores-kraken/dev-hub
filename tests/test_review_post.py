from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from helpers import commit, fake_review_helpers, git

from dev_hub.diffs.git import list_commits
from dev_hub.diffs.store import list_comments, list_reviews, save_description
from dev_hub.review.post import post
from dev_hub.review.prepare import prepare


@pytest.fixture
def run(repo: Path, reviews: Path, skills: Path) -> Path:
    """A prepared run folder for `feature/x`, which has a three-line file as well."""
    git(repo, "switch", "-q", "feature/x")
    commit(repo, "three.txt", "a\nb\nc\n", "Add three")
    git(repo, "switch", "-q", "master")
    save_description("feature/x", "Title", "Intro line\nSecond line")
    _, folder = prepare("feature/x", fake_review_helpers(), cwd=repo)
    return folder


def findings(
    folder: Path, persona: str, summary: str, items: list[dict[str, Any]], **more: Any
) -> None:
    (folder / "findings").mkdir(exist_ok=True)
    (folder / "findings" / f"{persona}.json").write_text(
        json.dumps({"summary": summary, "findings": items, **more})
    )


def test_a_line_finding_becomes_a_comment_on_all_changes(run: Path) -> None:
    findings(
        run, "correctness", "Worst case survived.",
        [{"path": "one.txt", "line": 1, "side": "RIGHT", "severity": "blocker", "body": "Why `one`?"}],
    )  # fmt: skip
    line = post(run, "correctness")
    assert line.startswith("Correctness: 1 finding (1 blocker) — http://")

    [comment] = list_comments("feature/x")
    assert comment["text"] == "Why `one`?"
    assert (comment["persona"], comment["author"], comment["finding_id"]) == (
        "correctness", "🧠 Correctness", "CR-1",
    )  # fmt: skip
    assert comment["severity"] == "blocker" and comment["status"] == "open"
    assert comment["target"] == {
        "kind": "line", "commit": None, "file": "one.txt", "side": "new",
        "start": 1, "end": 1, "quote": "one",
    }  # fmt: skip
    [review] = list_reviews("feature/x")
    assert (review["verdict"], review["summary"], review["findings"]) == (
        "comments", "Worst case survived.", ["CR-1"],
    )  # fmt: skip


def test_a_range_is_quoted_from_the_diff(run: Path) -> None:
    findings(
        run, "naming", "Names.",
        [{"path": "three.txt", "line": 3, "start_line": 2, "side": "RIGHT", "severity": "nit", "body": "x"}],
    )  # fmt: skip
    post(run, "naming")
    [comment] = list_comments("feature/x")
    assert (comment["target"]["start"], comment["target"]["end"]) == (2, 3)
    assert comment["target"]["quote"] == "b\nc"
    assert comment["finding_id"] == "NM-1"


def test_description_and_commit_message_findings_become_comments_on_them(run: Path) -> None:
    [one, _, _] = list_commits("feature/x")
    findings(
        run, "writing", "Words.",
        [
            {"where": "PR description", "severity": "should-fix", "body": "Too vague."},
            {"where": f"commit {one.sha[:7]}", "severity": "nit", "body": "Subject is long."},
        ],
    )  # fmt: skip
    post(run, "writing")
    description, message = list_comments("feature/x")
    assert description["target"] == {
        "kind": "pr_body", "commit": None, "start": 1, "end": 2, "quote": "Intro line\nSecond line",
    }  # fmt: skip
    assert message["target"]["kind"] == "message"
    assert message["target"]["commit"] == one.sha
    assert message["target"]["quote"] == one.message
    assert (message["target"]["start"], message["target"]["end"]) == (1, 3)
    assert message["target"]["subject"] == "Add one" and message["target"]["patch_id"]


def test_a_finding_with_no_place_stays_in_the_review(run: Path) -> None:
    findings(
        run, "tests", "Tests.",
        [
            {"where": "src/elsewhere.py", "severity": "should-fix", "body": "Not covered."},
            {"path": "one.txt", "line": 99, "severity": "nit", "body": "No such line."},
            {"where": "commit deadbee", "severity": "nit", "body": "No such commit."},
        ],
    )  # fmt: skip
    post(run, "tests")
    assert list_comments("feature/x") == []
    [review] = list_reviews("feature/x")
    assert [(u["finding_id"], u["where"], u["body"]) for u in review["unplaced"]] == [
        ("TS-1", "src/elsewhere.py", "Not covered."),
        ("TS-2", "one.txt:99", "No such line."),
        ("TS-3", "commit deadbee", "No such commit."),
    ]


def test_no_description_means_a_description_finding_stays_in_the_review(
    repo: Path, reviews: Path, skills: Path
) -> None:
    _, folder = prepare("feature/x", fake_review_helpers(), cwd=repo)
    findings(
        folder,
        "writing",
        "Words.",
        [{"where": "PR description", "severity": "nit", "body": "Empty."}],
    )
    post(folder, "writing")
    assert list_comments("feature/x") == []
    assert list_reviews("feature/x")[0]["unplaced"][0]["where"] == "PR description"


def test_an_lgtm_is_a_review_with_no_comments(run: Path) -> None:
    findings(run, "domain", "Matches the ticket.", [])
    assert post(run, "domain").startswith("Domain: LGTM")
    assert list_comments("feature/x") == []
    assert list_reviews("feature/x")[0]["verdict"] == "lgtm"


def test_numbers_continue_after_earlier_runs_and_fixed_findings_are_resolved(
    repo: Path, reviews: Path, skills: Path
) -> None:
    item = {"path": "one.txt", "line": 1, "severity": "nit", "body": "first"}
    _, first = prepare("feature/x", fake_review_helpers(), cwd=repo)
    findings(first, "correctness", "One.", [item])
    post(first, "correctness")

    _, second = prepare("feature/x", fake_review_helpers(), cwd=repo)
    findings(second, "correctness", "Two.", [{**item, "body": "second"}], resolved=["CR-1"])
    post(second, "correctness")
    comments = {c["finding_id"]: c["status"] for c in list_comments("feature/x")}
    assert comments == {"CR-1": "resolved", "CR-2": "open"}


def test_a_dry_run_saves_nothing(run: Path) -> None:
    findings(run, "naming", "N.", [{"path": "one.txt", "line": 1, "severity": "nit", "body": "x"}])
    printed = json.loads(post(run, "naming", dry_run=True))
    assert printed["comments"][0]["id"] == "NM-1"
    assert list_comments("feature/x") == [] and list_reviews("feature/x") == []
    assert not (run / "posted").exists()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"summary": "", "findings": []}, "non-empty 'summary'"),
        ({"summary": "s", "findings": "no"}, "must be a list"),
        (
            {"summary": "s", "findings": [{"severity": "huge", "body": "b", "where": "w"}]},
            "severity",
        ),
        (
            {"summary": "s", "findings": [{"severity": "nit", "body": " ", "where": "w"}]},
            "'body' is empty",
        ),
        ({"summary": "s", "findings": [{"severity": "nit", "body": "b"}]}, "give 'path'"),
    ],
)
def test_bad_findings_are_refused_and_nothing_is_saved(
    run: Path, data: dict[str, Any], message: str
) -> None:
    (run / "findings").mkdir()
    (run / "findings" / "naming.json").write_text(json.dumps(data))
    with pytest.raises(SystemExit, match=message):
        post(run, "naming")
    assert list_reviews("feature/x") == []


def test_a_persona_posts_once_per_run_and_only_known_ones(run: Path) -> None:
    findings(run, "naming", "N.", [])
    post(run, "naming")
    with pytest.raises(SystemExit, match="already posted"):
        post(run, "naming")
    with pytest.raises(SystemExit, match="unknown persona"):
        post(run, "nobody")


def test_a_run_folder_made_for_a_pr_is_refused(run: Path) -> None:
    meta = json.loads((run / "meta.json").read_text())
    (run / "meta.json").write_text(json.dumps({**meta, "mode": None}))
    findings(run, "naming", "N.", [])
    with pytest.raises(SystemExit, match="prepared for a PR"):
        post(run, "naming")


def test_posted_comments_show_on_the_all_changes_page(
    run: Path, client: FlaskClient, base_url: str
) -> None:
    findings(
        run, "correctness", "C.", [{"path": "one.txt", "line": 1, "severity": "nit", "body": "x"}]
    )
    post(run, "correctness")
    page = client.get("/diffs/feature/x/changes", base_url=base_url).get_data(as_text=True)
    assert '"finding_id": "CR-1"' in page or '"finding_id":"CR-1"' in page
    overview = client.get("/diffs/feature/x", base_url=base_url).get_data(as_text=True)
    assert "Correctness" in overview and "C." in overview
