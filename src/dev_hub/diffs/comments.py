"""Check the target of a comment: which lines of what it is about.

A comment is about a range of lines in one of three places:

- `line`: a file in a diff. `commit` is the commit whose page it was made on, or None for the
  "All changes" page. `side` says which numbers the range uses: `new` for added and unchanged
  lines, `old` for removed lines.
- `message`: a commit message. Line 1 is the subject.
- `pr_body`: the PR description.

`quote` is the text of those lines when the comment was made. It is what lets a comment still make
sense after the lines move or change.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

KINDS = ("line", "message", "pr_body")
SIDES = ("old", "new")
STATUSES = ("open", "resolved")
MAX_COMMENT = 20_000
MAX_QUOTE = 20_000
MAX_FILE = 1_000
MAX_LINE = 1_000_000


def parse_target(raw: object, commit_shas: Collection[str]) -> dict[str, Any] | None:
    """The cleaned target, or None if it isn't valid. Only the known keys are kept."""
    if not isinstance(raw, dict):
        return None
    kind, commit = raw.get("kind"), raw.get("commit")
    start, end, quote = raw.get("start"), raw.get("end"), raw.get("quote")
    if kind not in KINDS or not (isinstance(quote, str) and len(quote) <= MAX_QUOTE):
        return None
    if not (isinstance(start, int) and isinstance(end, int) and _lines_ok(start, end)):
        return None
    target: dict[str, Any] = {"kind": kind, "commit": commit, "start": start, "end": end}
    if kind == "pr_body":
        if commit is not None:
            return None
    elif kind == "message":
        if commit not in commit_shas:
            return None
    else:
        file, side = raw.get("file"), raw.get("side")
        if commit is not None and commit not in commit_shas:
            return None
        if not (isinstance(file, str) and 0 < len(file) <= MAX_FILE and side in SIDES):
            return None
        target |= {"file": file, "side": side}
    return target | {"quote": quote}


def is_valid_text(text: object) -> bool:
    return isinstance(text, str) and len(text.strip()) > 0 and len(text) <= MAX_COMMENT


def on_page(comment: dict[str, Any], page: str, shas: Collection[str]) -> bool:
    """Whether a comment belongs on a page: "overview", "changes", or a commit's sha.

    `shas` are the branch's commits. A comment on a commit that is no longer one of them is on the
    overview, where it is listed as one that couldn't be placed."""
    return _page_of(comment["target"], shas) == page


def open_counts(comments: list[dict[str, Any]], shas: Collection[str]) -> dict[str, int]:
    """How many open comments each page has, keyed like `on_page`."""
    counts: dict[str, int] = {}
    for comment in comments:
        if comment["status"] == "open":
            page = _page_of(comment["target"], shas)
            counts[page] = counts.get(page, 0) + 1
    return counts


def _page_of(target: dict[str, Any], shas: Collection[str]) -> str:
    if target["kind"] == "pr_body" or (target["commit"] and target["commit"] not in shas):
        return "overview"
    return target["commit"] or "changes"


def _lines_ok(start: int, end: int) -> bool:
    # bool is an int in Python, but true/false are not line numbers.
    return (
        not isinstance(start, bool) and not isinstance(end, bool) and 1 <= start <= end <= MAX_LINE
    )
