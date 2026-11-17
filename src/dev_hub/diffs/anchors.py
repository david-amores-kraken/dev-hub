"""Find a comment's lines again after the code around them has moved.

A comment keeps the text of the lines it was about (its quote). When a rebase or an edit shifts
those lines, the quote is searched for in the new text, and the comment follows it. If the quote
is gone, the comment is left alone and the page lists it as one it couldn't place.

Everything here is a pure function of text, so none of it touches git or the files.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dev_hub.diffs.git import Commit

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Row:
    """One line of a diff. Removed lines have no `new`, added lines have no `old`."""

    old: int | None
    new: int | None
    text: str
    hunk: int = field(default=0, compare=False)  # which "@@" block of its file it is in


@dataclass(frozen=True)
class Patch:
    """A parsed diff. `files` is what `parse_patch` gives. `names` has each file's name before and
    after (by the same key), with "" for the side where it didn't exist. A file that was only
    renamed has names but no rows."""

    files: dict[str, list[Row]]
    names: dict[str, tuple[str, str]]


def parse_patch(patch: str) -> dict[str, list[Row]]:
    """The rows of each file in a unified diff. A file is called what the diff page calls it:
    its new name, except a deleted file, which keeps its old one."""
    return read_patch(patch).files


def read_patch(patch: str) -> Patch:
    """The rows and the names of each file in a unified diff."""
    files: dict[str, list[Row]] = {}
    names: dict[str, tuple[str, str]] = {}
    rows: list[Row] | None = None
    old_name = new_name = ""
    old = new = hunk = 0
    in_hunk = False
    for line in patch.split("\n"):
        if line.startswith("diff --git "):
            rows, in_hunk, old_name, new_name, hunk = None, False, "", "", 0
        elif not in_hunk and line.startswith("rename from "):
            old_name = line.removeprefix("rename from ")
        elif not in_hunk and line.startswith("rename to "):
            new_name = line.removeprefix("rename to ")
            names[new_name] = (old_name, new_name)
        elif not in_hunk and line.startswith("--- "):
            old_name = _name(line[4:])
        elif not in_hunk and line.startswith("+++ "):
            new_name = _name(line[4:])
            rows = files.setdefault(new_name or old_name, [])
            names[new_name or old_name] = (old_name, new_name)
        elif match := HUNK_RE.match(line):
            old, new, in_hunk, hunk = int(match[1]), int(match[2]), True, hunk + 1
        elif in_hunk and rows is not None:
            if line.startswith("+"):
                rows.append(Row(None, new, line[1:], hunk))
                new += 1
            elif line.startswith("-"):
                rows.append(Row(old, None, line[1:], hunk))
                old += 1
            elif line.startswith(" "):
                rows.append(Row(old, new, line[1:], hunk))
                old, new = old + 1, new + 1
            # Anything else ("\ No newline at end of file", the blank end of the patch) is no line.
    return Patch(files, names)


def map_line(rows: Sequence[Row], line: int, side: str) -> int | None:
    """Where a line of one side of a file's diff is on the other side: an old line number to its
    new one (`side` "old"), or the reverse ("new"). None if the diff removed it (or added it, going
    back). Lines outside the hunks move by what the hunks before them added and removed."""
    other = "new" if side == "old" else "old"
    shift = 0
    for row in rows:
        here, there = getattr(row, side), getattr(row, other)
        if here is None:  # a line only the other side has
            if there is not None and there > line + shift:
                break
            shift += 1
        elif here == line:
            return there
        elif here > line:
            break
        elif there is None:
            shift -= 1
    return line + shift


def matches(rows: Sequence[Row], side: str, lines: Sequence[int], quote: str) -> bool:
    """Whether the diff shows `lines` (numbered on `side`) and their text is still the quote."""
    numbered = {getattr(row, side): row.text for row in rows if getattr(row, side) is not None}
    texts = [line.rstrip() for line in quote.split("\n")]
    return len(lines) == len(texts) and all(
        n in numbered and numbered[n].rstrip() == text for n, text in zip(lines, texts, strict=True)
    )


def relocate_in_patch(
    target: dict[str, Any], files: dict[str, list[Row]]
) -> tuple[int, int] | None:
    """Where a comment's quote is in a diff now, as (start, end), or None if it isn't there."""
    rows = files.get(target["file"], [])
    key = "old" if target["side"] == "old" else "new"
    numbered = [(getattr(row, key), row.text) for row in rows if getattr(row, key) is not None]
    return _find(numbered, target)


def relocate_in_text(target: dict[str, Any], text: str) -> tuple[int, int] | None:
    """The same for a commit message or the PR description, numbered from 1."""
    numbered = list(enumerate(text.split("\n"), start=1))
    return _find(numbered, target)


def find_commit(
    target: dict[str, Any], commits: Sequence[Commit], patch_ids: Mapping[str, str | None]
) -> Commit | None:
    """The commit a comment was made on, now that its sha has gone.

    A commit that was only rebased has the same patch id. One that was changed (amended, or
    fixed up) is found by its subject. If that is still not one commit, there is no answer."""
    wanted = target.get("patch_id")
    same_change = [c for c in commits if wanted and patch_ids.get(c.sha) == wanted]
    if len(same_change) == 1:
        return same_change[0]
    same_subject = [c for c in same_change or commits if c.subject == target.get("subject")]
    return same_subject[0] if len(same_subject) == 1 else None


def _find(numbered: list[tuple[int, str]], target: dict[str, Any]) -> tuple[int, int] | None:
    """The run of consecutive lines whose text is the quote. If it appears more than once, the
    one nearest to where the comment was."""
    quote = [line.rstrip() for line in target["quote"].split("\n")]
    texts = [text.rstrip() for _, text in numbered]
    found = [
        numbered[i][0]
        for i in range(len(numbered) - len(quote) + 1)
        if texts[i : i + len(quote)] == quote
        and numbered[i + len(quote) - 1][0] - numbered[i][0] == len(quote) - 1
    ]
    if not found:
        return None
    start = min(found, key=lambda number: abs(number - target["start"]))
    return start, start + len(quote) - 1


def _name(raw: str) -> str:
    """A file name from a `---` or `+++` line: without the a/ or b/, or empty for /dev/null."""
    raw = raw.split("\t")[0]
    if raw == "/dev/null":
        return ""
    return raw[2:] if raw[:2] in ("a/", "b/") else raw
