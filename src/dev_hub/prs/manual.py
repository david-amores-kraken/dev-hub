"""PRs the user adds by link, though nobody asked them to review it."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

FIELDS = "number,title,author,createdAt,updatedAt,url,isDraft,state"
LINK = re.compile(r"^(?:https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)(?:[/?#].*)?|#?(\d+))$")


def parse_pr_link(text: str, repo: str) -> int | None:
    """The PR number from a link to a PR in `repo`, or from a bare number. None for anything else."""
    found = LINK.match(text.strip())
    if not found:
        return None
    if found[3]:
        return int(found[3])
    return int(found[2]) if found[1].lower() == repo.lower() else None


def fetch_pr(number: int, config: dict[str, Any]) -> dict[str, Any]:
    """The PR as `gh search prs` shows it, plus its state. Raises if GitHub can't be reached."""
    view = subprocess.run(
        ["gh", "pr", "view", str(number), "--repo", config["repo"], "--json", FIELDS],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(view.stdout)
