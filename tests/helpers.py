"""Helpers for tests that need a real git repo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


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


def fake_review_helpers(user_facing: bool = False) -> Any:
    """A stand-in for ~/.claude/lib/review_context.py, which CI doesn't have."""
    from types import SimpleNamespace

    from dev_hub.diffs.anchors import parse_patch

    def commentable_lines(diff: str) -> dict[str, dict[str, list[int]]]:
        lines: dict[str, dict[str, list[int]]] = {}
        for path, rows in parse_patch(diff).items():
            lines[path] = {
                "RIGHT": [r.new for r in rows if r.new is not None],
                "LEFT": [r.old for r in rows if r.old is not None],
            }
        return lines

    return SimpleNamespace(
        user_facing=lambda diff: [{"path": "one.txt", "why": "template"}] if user_facing else [],
        context_files=lambda root, changed: ["AGENTS.md"],
        matching_rules=lambda root, changed: [],
        repo_skills=lambda root: [
            {"name": "s", "path": ".claude/skills/s/SKILL.md", "description": "d"}
        ],
        asana_tasks=lambda texts: [
            {"id": "123", "url": "https://app.asana.com/0/1/123"}
            for text in texts
            if "asana.com" in text
        ],
        commentable_lines=commentable_lines,
    )
