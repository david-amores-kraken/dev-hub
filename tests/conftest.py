"""Keep the tests away from the real ~/pr-reviews, ~/Plans, ~/Reports, ~/E2E and ~/Reviews."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

# dev_hub.prs reads this when it is first imported, so set it before anything imports it.
os.environ["PR_BRIEF_HOME"] = tempfile.mkdtemp(prefix="dev-hub-test-")

import pytest
from flask.testing import FlaskClient
from helpers import commit, git
from werkzeug.test import TestResponse

from dev_hub.app import create_app
from dev_hub.config import HOST, PORT
from dev_hub.prs import rows, store
from dev_hub.prs.config import EXAMPLE


@pytest.fixture(autouse=True)
def no_real_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every folder the hub reads at one that isn't there, so no test reads my real
    repo, plans, reports, e2e results or reviews. The fixtures below replace these."""
    for name in ("REPO", "PLANS", "REPORTS", "E2E", "REVIEWS"):
        monkeypatch.setenv(f"DEV_HUB_{name}", str(tmp_path / f"no-{name.lower()}"))


@pytest.fixture(autouse=True)
def pr_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the PR section's store at a new folder, with the example config in it."""
    folder = tmp_path / "pr-reviews"
    folder.mkdir()
    monkeypatch.setattr(store, "HOME", folder)
    for name, sub in {
        "RUNS": "runs",
        "QUEUE": "queue.json",
        "REQUESTS": "requests",
        "MARKS": "marks.json",
        "HISTORY": "history.json",
        "MANUAL": "manual.json",
    }.items():
        monkeypatch.setattr(store, name, folder / sub)
    # rows.py imported this name directly, so patch its copy too.
    monkeypatch.setattr(rows, "RUNS", folder / "runs")
    shutil.copy(EXAMPLE, folder / "config.json")
    return folder


@pytest.fixture
def plans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "Plans"
    folder.mkdir()
    monkeypatch.setenv("DEV_HUB_PLANS", str(folder))
    return folder


@pytest.fixture
def reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "Reports"
    folder.mkdir()
    monkeypatch.setenv("DEV_HUB_REPORTS", str(folder))
    return folder


@pytest.fixture
def e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "E2E"
    folder.mkdir()
    monkeypatch.setenv("DEV_HUB_E2E", str(folder))
    return folder


@pytest.fixture
def client(plans: Path, reports: Path, reviews: Path, e2e: Path) -> FlaskClient:
    return create_app().test_client()


@pytest.fixture
def base_url() -> str:
    return f"http://{HOST}:{PORT}"


class SameOriginClient(FlaskClient):
    """Sends every request to the hub's own host and from its own origin, as its pages do."""

    def open(self, *args: Any, **kwargs: Any) -> TestResponse:
        base = f"http://{HOST}:{PORT}"
        kwargs.setdefault("base_url", base)
        kwargs["headers"] = {"Origin": base, **(kwargs.get("headers") or {})}
        return super().open(*args, **kwargs)


@pytest.fixture
def prs_client(plans: Path, reports: Path, reviews: Path, e2e: Path) -> FlaskClient:
    """A hub client that passes the host and origin checks, so the PR tests needn't."""
    app = create_app()
    app.test_client_class = SameOriginClient
    return app.test_client()


@pytest.fixture
def reviews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "Reviews"
    folder.mkdir()
    monkeypatch.setenv("DEV_HUB_REVIEWS", str(folder))
    return folder


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small git repo: master has one commit, then `feature/x` adds two, then master moves on."""
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "master")
    commit(folder, "base.txt", "base\n", "Add base")
    git(folder, "switch", "-q", "-c", "feature/x")
    commit(folder, "one.txt", "one\n", "Add one\n\nWhy one is needed.")
    commit(folder, "two.txt", "two\n", "Add two")
    git(folder, "switch", "-q", "master")
    commit(folder, "later.txt", "later\n", "Master moves on")
    monkeypatch.setenv("DEV_HUB_REPO", str(folder))
    monkeypatch.setenv("DEV_HUB_BASE", "master")
    return folder


@pytest.fixture
def skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for ~/.claude (one writing preference file) and for the review brief."""
    home = tmp_path / "claude"
    home.mkdir()
    brief = tmp_path / "brief.md"
    brief.write_text(
        "# Local review brief\n\nThis is a review of a local branch.\n\n```bash\n"
        "{POST_COMMAND} <run folder> <your persona key>\n```\n"
    )
    (home / "comment-preferences.md").write_text("no comments")
    monkeypatch.setattr("dev_hub.review.prepare.CLAUDE", home)
    monkeypatch.setattr("dev_hub.review.prepare.BRIEF", brief)
    return brief
