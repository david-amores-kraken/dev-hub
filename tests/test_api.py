from __future__ import annotations

from pathlib import Path
from typing import Any

from flask.testing import FlaskClient
from helpers import commit, git

from dev_hub.diffs.git import list_commits
from dev_hub.diffs.pages import page_files
from dev_hub.diffs.store import add_comment, add_review, save_description

BRANCH = "feature/x"


def get(client: FlaskClient, base_url: str, url: str, **params: str) -> tuple[int, Any]:
    response = client.get(url, query_string=params, base_url=base_url)
    return response.status_code, response.get_json()


def line(commit: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "line",
        "commit": commit,
        "file": "one.txt",
        "side": "new",
        "start": 1,
        "end": 1,
        "quote": "one",
    } | extra


def test_branches_lists_only_those_with_commits_to_review(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    status, branches = get(client, base_url, "/api/branches")
    assert status == 200
    assert [(b["name"], b["commits"], b["subject"]) for b in branches] == [
        ("feature/x", 2, "Add two")
    ]


def test_a_branch_has_its_commits_and_the_files_of_each_page(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, two = list_commits(BRANCH)
    save_description(BRANCH, "Add one and two", "Body")
    status, data = get(client, base_url, "/api/branch", branch=BRANCH)
    assert status == 200
    assert data["branch"] == BRANCH
    assert data["description"] == {"title": "Add one and two", "body": "Body"}
    assert [c["sha"] for c in data["commits"]] == [one.sha, two.sha]
    assert data["commits"][0]["message"] == "Add one\n\nWhy one is needed."
    assert data["urls"] == {
        "overview": "/diffs/feature/x",
        "comments": "/diffs/feature/x/comments",
    }
    assert data["feature"] is None
    assert [f["path"] for f in data["files"]["changes"]] == ["one.txt", "two.txt"]
    assert data["files"][one.sha] == [
        {
            "path": "one.txt",
            "old_path": "",
            "status": "added",
            "lines": {"old": [], "new": [1]},
        }
    ]


def test_a_branch_links_to_the_parts_of_its_feature(
    repo: Path, plans: Path, e2e: Path, client: FlaskClient, base_url: str
) -> None:
    (plans / "feature-x.html").write_text("<html><head><title>Do X</title></head></html>")
    (e2e / "feature-x.html").write_text("<html></html>")
    _, data = get(client, base_url, "/api/branch", branch=BRANCH)
    feature = data["feature"]
    assert (feature["slug"], feature["title"], feature["url"]) == (
        "feature-x",
        "Do X",
        "/features/feature-x",
    )
    assert [(p["key"], p["label"], p["url"]) for p in feature["parts"]] == [
        ("plan", "Plan", "/features/feature-x/plan/raw"),
        ("e2e", "E2E", "/features/feature-x/e2e/raw"),
    ]
    assert "script-src" not in feature["content_policy"]
    assert "default-src 'none'" in feature["content_policy"]


def test_comments_are_on_the_pages_the_diffs_section_shows_them_on(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits(BRANCH)
    save_description(BRANCH, "T", "first\nsecond")
    on_changes = add_comment(BRANCH, line(None), "On all changes")
    on_body = add_comment(
        BRANCH, {"kind": "pr_body", "commit": None, "start": 2, "end": 2, "quote": "second"}, "B"
    )
    gone = add_comment(BRANCH, line("c" * 40), "On a commit that has gone")
    _, data = get(client, base_url, "/api/branch", branch=BRANCH)
    where = {(c["id"], c["page"]): c for c in data["comments"]}
    assert set(where) == {
        (on_changes["id"], "changes"),
        (on_changes["id"], one.sha),  # mirrored onto the commit that added the line
        (on_body["id"], "overview"),
        (gone["id"], "overview"),
    }
    assert where[(on_changes["id"], one.sha)]["target"]["commit"] == one.sha
    assert where[(on_changes["id"], "changes")]["html"] == "<p>On all changes</p>\n"
    placed = {key: c["placed"] for key, c in where.items()}
    assert placed[(on_changes["id"], "changes")]
    assert placed[(on_body["id"], "overview")]
    assert not placed[(gone["id"], "overview")]


def test_a_comment_whose_lines_changed_is_not_placed(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits(BRANCH)
    comment = add_comment(BRANCH, line(one.sha, quote="what it said before"), "Old")
    _, data = get(client, base_url, "/api/branch", branch=BRANCH)
    [shown] = [c for c in data["comments"] if c["id"] == comment["id"]]
    assert (shown["page"], shown["placed"]) == (one.sha, False)


def test_a_branch_lists_its_reviews_newest_first(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    for summary in ("first", "second"):
        add_review(BRANCH, {"persona": "tests", "summary": summary, "findings": []}, [])
    _, data = get(client, base_url, "/api/branch", branch=BRANCH)
    assert [(r["summary"], r["latest"]) for r in data["reviews"]] == [
        ("second", True),
        ("first", False),
    ]


def test_a_file_is_read_as_the_page_shows_it(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits(BRANCH)
    git(repo, "switch", "-q", BRANCH)
    commit(repo, "one.txt", "one\nmore\n", "Add more")
    git(repo, "switch", "-q", "master")
    for page, side, text in (
        (one.sha, "new", "one\n"),
        (one.sha, "old", None),  # it didn't exist before
        ("changes", "new", "one\nmore\n"),
    ):
        status, data = get(
            client, base_url, "/api/file", branch=BRANCH, page=page, path="one.txt", side=side
        )
        assert (status, data) == (200, {"text": text}), (page, side)


def test_a_file_must_be_on_a_page_of_the_branch(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, two = list_commits(BRANCH)
    for params, status in (
        ({"branch": "no/such", "page": "changes", "path": "one.txt", "side": "new"}, 404),
        ({"branch": BRANCH, "page": "a" * 40, "path": "one.txt", "side": "new"}, 404),
        ({"branch": BRANCH, "page": two.sha, "path": "one.txt", "side": "new"}, 404),
        ({"branch": BRANCH, "page": one.sha, "path": "one.txt", "side": "left"}, 400),
    ):
        assert get(client, base_url, "/api/file", **params)[0] == status, params


def test_an_unknown_branch_is_not_found(repo: Path, client: FlaskClient, base_url: str) -> None:
    assert get(client, base_url, "/api/branch", branch="no/such")[0] == 404
    assert get(client, base_url, "/api/branch")[0] == 404


PATCH = """\
diff --git a/old.txt b/new.txt
similarity index 90%
rename from old.txt
rename to new.txt
index 1111111..2222222 100644
--- a/old.txt
+++ b/new.txt
@@ -1,2 +1,2 @@
 same
-before
+after
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 3333333..0000000
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..4444444
Binary files /dev/null and b/logo.png differ
"""


def test_page_files_names_each_file_and_the_lines_a_comment_can_go_on() -> None:
    assert page_files(PATCH) == [
        {
            "path": "new.txt",
            "old_path": "old.txt",
            "status": "renamed",
            "lines": {"old": [2], "new": [1, 2]},
        },
        {
            "path": "gone.txt",
            "old_path": "gone.txt",
            "status": "deleted",
            "lines": {"old": [1], "new": []},
        },
        {"path": "logo.png", "old_path": "", "status": "added", "lines": {"old": [], "new": []}},
    ]
