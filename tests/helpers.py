"""Helpers for tests that need a real git repo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git(folder: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
    }
    result = subprocess.run(
        ["git", "-C", str(folder), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def commit(folder: Path, name: str, text: str, message: str) -> None:
    (folder / name).write_text(text)
    git(folder, "add", name)
    git(folder, "commit", "-q", "-m", message)
