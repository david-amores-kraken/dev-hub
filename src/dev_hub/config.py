"""Where the hub listens and where it reads things from."""

from __future__ import annotations

import os
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("DEV_HUB_PORT", "8765"))


def plans_dir() -> Path:
    """Where the feature skill saves plans (and their index.html)."""
    return Path(os.environ.get("DEV_HUB_PLANS") or Path.home() / "Plans")


def reports_dir() -> Path:
    """Where the feature skill saves reports (and their index.html)."""
    return Path(os.environ.get("DEV_HUB_REPORTS") or Path.home() / "Reports")


def e2e_dir() -> Path:
    """Where the e2e-verify skill saves its results for each feature."""
    return Path(os.environ.get("DEV_HUB_E2E") or Path.home() / "E2E")


def repo_dir() -> Path:
    """The git repo whose branches the Diffs section shows."""
    return Path(os.environ.get("DEV_HUB_REPO") or Path.home() / "Code" / "kraken-core")


def base_ref() -> str:
    """What branches are compared against: a branch's commits are the ones not in this ref."""
    return os.environ.get("DEV_HUB_BASE") or "origin/master"


def reviews_dir() -> Path:
    """Where the Diffs section keeps what I write about a branch (the PR title and body)."""
    return Path(os.environ.get("DEV_HUB_REVIEWS") or Path.home() / "Reviews")
