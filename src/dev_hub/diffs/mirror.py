"""Show a comment on both pages that have its lines: a commit's page and "All changes".

A comment is saved once, on the page it was made on. A comment on a commit's diff is also shown on
"All changes" if those lines are still in the branch's diff. A comment on "All changes" is also
shown on the commit that last added (or removed) those lines. A comment on lines the base already
had, and no commit changed, stays on "All changes" only.

The lines are followed from diff to diff by their line numbers (a later commit that adds two lines
above them moves them down two). Where they end up, their text must still be the comment's quote,
so a comment is never shown against other code. If a later commit changed the lines, the comment
stays on its own page only.

Everything here is a pure function of the parsed diffs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from dev_hub.diffs.anchors import Patch, map_line, matches

Lines = list[int]


def mirror(
    target: dict[str, Any], shas: Sequence[str], commits: Mapping[str, Patch], branch: Patch
) -> dict[str, Any] | None:
    """Where else a comment on a diff line is shown, as a target on that page, or None.

    `shas` are the branch's commits, oldest first, and `commits` their parsed diffs. `branch` is
    the parsed "All changes" diff."""
    if target["kind"] != "line":
        return None
    if target["commit"] is None:
        return _to_commit(target, shas, commits, branch)
    if target["commit"] in commits:
        return _to_branch(target, shas, commits, branch)
    return None


def _to_branch(
    target: dict[str, Any], shas: Sequence[str], commits: Mapping[str, Patch], branch: Patch
) -> dict[str, Any] | None:
    """A commit's comment on "All changes". New lines are followed through the later commits to
    the branch's tip; removed lines back through the earlier ones to the base."""
    side, index = target["side"], list(shas).index(target["commit"])
    names = commits[target["commit"]].names.get(target["file"])
    if names is None:
        return None
    lines: Lines | None = _range(target)
    if side == "new":
        name = names[1]
        for sha in shas[index + 1 :]:
            name, lines = _forward(commits[sha], name, lines)
            if lines is None:
                return None
        key = _key(branch, name, after=True)
    else:
        name = names[0]
        for sha in reversed(shas[:index]):
            name, lines = _back(commits[sha], name, lines)
            if lines is None:
                return None
        key = _key(branch, name, after=False)
    if key is None or not _place(branch.files.get(key, []), side, lines, target["quote"]):
        return None
    return _at(target, None, key, lines)


def _to_commit(
    target: dict[str, Any], shas: Sequence[str], commits: Mapping[str, Patch], branch: Patch
) -> dict[str, Any] | None:
    """An "All changes" comment on the commit that made its lines what they are.

    For new lines, that is the newest commit that added any of them, found by going back from the
    tip. For removed lines, the oldest commit that removed any of them, going on from the base."""
    side = target["side"]
    names = branch.names.get(target["file"])
    if names is None:
        return None
    lines: Lines | None = _range(target)
    name = names[1] if side == "new" else names[0]
    order = reversed(shas) if side == "new" else iter(shas)
    for sha in order:
        patch = commits[sha]
        key = _key(patch, name, after=side == "new")
        if key is None:
            continue
        rows = patch.files.get(key, [])
        other = "old" if side == "new" else "new"
        changed = {getattr(r, side) for r in rows if getattr(r, other) is None}
        if changed & set(lines or []):
            return (
                _at(target, sha, key, lines) if _place(rows, side, lines, target["quote"]) else None
            )
        if side == "new":
            name, lines = _back(patch, name, lines)
        else:
            name, lines = _forward(patch, name, lines)
        if lines is None:
            return None
    return None


def _forward(patch: Patch, name: str, lines: Lines | None) -> tuple[str, Lines | None]:
    """A file's name and lines after a commit, from what they were before it. No lines if the
    commit removed one of them, or the file."""
    key = _key(patch, name, after=False)
    if key is None or lines is None:
        return name, lines
    new = patch.names[key][1]
    if not new:
        return name, None
    return new, _map(patch.files.get(key, []), lines, "old")


def _back(patch: Patch, name: str, lines: Lines | None) -> tuple[str, Lines | None]:
    """The same, going from after a commit to before it. No lines if the commit added them."""
    key = _key(patch, name, after=True)
    if key is None or lines is None:
        return name, lines
    old = patch.names[key][0]
    if not old:
        return name, None
    return old, _map(patch.files.get(key, []), lines, "new")


def _map(rows: Sequence[Any], lines: Lines, side: str) -> Lines | None:
    mapped = [map_line(rows, line, side) for line in lines]
    if any(line is None for line in mapped):
        return None
    numbers = [line for line in mapped if line is not None]
    # A line added in the middle of the range splits it; the comment can't cover both parts.
    return numbers if numbers == list(range(numbers[0], numbers[0] + len(numbers))) else None


def _key(patch: Patch, name: str, after: bool) -> str | None:
    """The key of the file the diff calls `name` after (or before) its change, if it changed."""
    side = 1 if after else 0
    return next((key for key, names in patch.names.items() if names[side] == name), None)


def _place(rows: Sequence[Any], side: str, lines: Lines | None, quote: str) -> bool:
    return lines is not None and matches(rows, side, lines, quote)


def _range(target: dict[str, Any]) -> Lines:
    return list(range(target["start"], target["end"] + 1))


def _at(
    target: dict[str, Any], commit: str | None, file: str, lines: Lines | None
) -> dict[str, Any]:
    assert lines is not None
    return {
        "kind": "line",
        "commit": commit,
        "file": file,
        "side": target["side"],
        "start": lines[0],
        "end": lines[-1],
        "quote": target["quote"],
    }
