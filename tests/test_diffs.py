from __future__ import annotations

import json
import re
from pathlib import Path

from flask.testing import FlaskClient
from helpers import git

from dev_hub.diffs.git import list_commits


def get(client: FlaskClient, base_url: str, url: str) -> tuple[int, str]:
    response = client.get(url, base_url=base_url)
    return response.status_code, response.get_data(as_text=True)


def test_the_list_shows_branches_ahead_of_the_base(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    status, page = get(client, base_url, "/diffs/")
    assert status == 200
    assert 'href="/diffs/feature/x"' in page
    assert "2 commits" in page
    assert 'href="/diffs/" ' in page  # nav


def test_the_list_says_when_the_repo_cant_be_read(
    tmp_path: Path, monkeypatch, client: FlaskClient, base_url: str
) -> None:
    monkeypatch.setenv("DEV_HUB_REPO", str(tmp_path / "missing"))
    status, page = get(client, base_url, "/diffs/")
    assert status == 200
    assert "Can't read the repo" in page


def test_the_overview_shows_each_commit_with_its_message(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    status, page = get(client, base_url, "/diffs/feature/x")
    assert status == 200
    assert "Add one" in page
    assert "Why one is needed." in page
    assert "Add two" in page
    assert "Master moves on" not in page


def test_a_commit_page_has_that_commits_patch_only(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    status, page = get(client, base_url, f"/diffs/feature/x/commits/{one.sha}")
    assert status == 200
    patch = _patch_in(page)
    assert "+++ b/one.txt" in patch
    assert "two.txt" not in patch
    assert "Why one is needed." in page


def test_the_all_changes_page_has_the_whole_branch_patch(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    status, page = get(client, base_url, "/diffs/feature/x/changes")
    assert status == 200
    patch = _patch_in(page)
    assert "+++ b/one.txt" in patch
    assert "+++ b/two.txt" in patch
    assert "later.txt" not in patch


def test_a_patch_cant_break_out_of_its_script_tag(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    (repo / "evil.txt").write_text("</script><script>alert(1)</script>\n")
    git(repo, "switch", "-q", "feature/x")
    git(repo, "add", "evil.txt")
    git(repo, "commit", "-q", "-m", "Add evil")
    _, page = get(client, base_url, "/diffs/feature/x/changes")
    assert "<script>alert(1)" not in page
    assert "alert(1)" in _patch_in(page)


def test_unknown_branches_and_commits_are_404(
    repo: Path, client: FlaskClient, base_url: str
) -> None:
    one, _ = list_commits("feature/x")
    unknown_sha = "0" * 40
    for url in (
        "/diffs/nope",
        "/diffs/nope/changes",
        f"/diffs/nope/commits/{one.sha}",
        f"/diffs/feature/x/commits/{unknown_sha}",
        "/diffs/feature/x/commits/--output=x",
        "/diffs/--all",
    ):
        assert get(client, base_url, url)[0] == 404, url


def _patch_in(page: str) -> str:
    match = re.search(r'<script type="application/json" id="patch">(.*?)</script>', page, re.S)
    assert match
    return json.loads(match[1])
