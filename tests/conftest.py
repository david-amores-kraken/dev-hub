"""Keep the tests away from the real ~/pr-reviews and ~/Plans."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# pr_brief reads this when it is first imported, so set it before anything imports pr_brief.
os.environ["PR_BRIEF_HOME"] = tempfile.mkdtemp(prefix="dev-hub-test-")

import pytest
from flask.testing import FlaskClient

from dev_hub.app import create_app
from dev_hub.config import HOST, PORT


@pytest.fixture
def plans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "Plans"
    folder.mkdir()
    monkeypatch.setenv("DEV_HUB_PLANS", str(folder))
    return folder


@pytest.fixture
def client(plans: Path) -> FlaskClient:
    return create_app().test_client()


@pytest.fixture
def base_url() -> str:
    return f"http://{HOST}:{PORT}"
