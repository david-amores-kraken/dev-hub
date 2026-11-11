"""Keep the tests away from the real ~/pr-reviews, ~/Plans and ~/Reports."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# pr_brief reads this when it is first imported, so set it before anything imports pr_brief.
os.environ["PR_BRIEF_HOME"] = tempfile.mkdtemp(prefix="dev-hub-test-")

import pytest
from flask.testing import FlaskClient
from helpers import commit, git

from dev_hub.app import create_app
from dev_hub.config import HOST, PORT


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
def client(plans: Path, reports: Path, reviews: Path) -> FlaskClient:
    return create_app().test_client()


@pytest.fixture
def base_url() -> str:
    return f"http://{HOST}:{PORT}"


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
