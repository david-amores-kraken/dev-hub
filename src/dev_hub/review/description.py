"""Read and write the draft PR title and description of a branch, for the agent that writes them.

The same title and description are in the Overview box of the Diffs section. Whoever saves last
wins, and the page shows the saved text when it is opened.
"""

from __future__ import annotations

from dev_hub.diffs import git
from dev_hub.diffs.store import MAX_BODY, MAX_TITLE, load_description, save_description


def show(branch: str) -> dict[str, str]:
    _require(branch)
    description = load_description(branch)
    return {"title": description.title, "body": description.body}


def update(branch: str, title: str | None, body: str | None) -> str:
    """Save a new title and/or body. Whatever is left out stays as it was."""
    _require(branch)
    if title is None and body is None:
        raise SystemExit("refusing: give --title, --body or --body-file")
    if title is not None and (not title.strip() or "\n" in title.strip() or len(title) > MAX_TITLE):
        raise SystemExit(
            f"refusing: the title must be one non-empty line of at most {MAX_TITLE} characters"
        )
    if body is not None and len(body) > MAX_BODY:
        raise SystemExit(f"refusing: the description is longer than {MAX_BODY} characters")
    current = load_description(branch)
    save_description(
        branch,
        current.title if title is None else title.strip(),
        current.body if body is None else body,
    )
    return f"saved the {' and '.join(p for p, v in (('title', title), ('description', body)) if v is not None)}"


def _require(branch: str) -> None:
    if not git.has_branch(branch):
        raise SystemExit(f"refusing: {branch!r} isn't a local branch")
