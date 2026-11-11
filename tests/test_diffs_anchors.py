from __future__ import annotations

from typing import Any

from dev_hub.diffs.anchors import (
    Row,
    find_commit,
    parse_patch,
    relocate_in_patch,
    relocate_in_text,
)
from dev_hub.diffs.git import Commit

PATCH = """\
diff --git a/old.py b/new.py
similarity index 80%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1,4 +1,4 @@
 keep
-removed
+added
 keep too
 last
@@ -20,2 +20,3 @@ def thing():
 twenty
+twenty-one
 end
\\ No newline at end of file
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
diff --git a/fresh.py b/fresh.py
new file mode 100644
--- /dev/null
+++ b/fresh.py
@@ -0,0 +1 @@
+hello
"""


def test_a_patch_is_read_into_rows_with_both_line_numbers() -> None:
    files = parse_patch(PATCH)
    assert list(files) == ["new.py", "gone.py", "fresh.py"]  # renamed: new name; deleted: old name
    assert files["new.py"] == [
        Row(1, 1, "keep"),
        Row(2, None, "removed"),
        Row(None, 2, "added"),
        Row(3, 3, "keep too"),
        Row(4, 4, "last"),
        Row(20, 20, "twenty"),
        Row(None, 21, "twenty-one"),
        Row(21, 22, "end"),
    ]
    assert files["gone.py"] == [Row(1, None, "one"), Row(2, None, "two")]
    assert files["fresh.py"] == [Row(None, 1, "hello")]


def test_a_line_that_starts_with_dashes_is_not_taken_for_a_file_header() -> None:
    patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n--- a comment\n+++ new text\n keep\n"
    assert parse_patch(patch)["f"] == [
        Row(1, None, "-- a comment"),
        Row(None, 1, "++ new text"),
        Row(2, 2, "keep"),
    ]


def target(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "line",
        "file": "new.py",
        "side": "new",
        "start": 2,
        "end": 2,
        "quote": "added",
    } | extra


def test_a_comment_follows_its_quote_to_the_new_line_number() -> None:
    files = {"new.py": [Row(None, 1, "x"), Row(None, 2, "y"), Row(None, 12, "added")]}
    assert relocate_in_patch(target(), files) == (12, 12)


def test_a_comment_that_is_still_in_place_stays() -> None:
    assert relocate_in_patch(target(), parse_patch(PATCH)) == (2, 2)


def test_a_range_is_found_only_as_consecutive_lines() -> None:
    wanted = target(start=3, end=4, quote="a\nb")
    split = {"new.py": [Row(None, 3, "a"), Row(None, 5, "b")]}
    together = {"new.py": [Row(None, 7, "a"), Row(None, 8, "b")]}
    assert relocate_in_patch(wanted, split) is None
    assert relocate_in_patch(wanted, together) == (7, 8)


def test_removed_lines_are_found_by_their_old_numbers() -> None:
    wanted = target(side="old", start=9, end=9, quote="removed")
    assert relocate_in_patch(wanted, parse_patch(PATCH)) == (2, 2)


def test_the_nearest_copy_wins_and_trailing_spaces_dont_matter() -> None:
    files = {"new.py": [Row(None, 1, "added"), Row(None, 40, "added  "), Row(None, 90, "added")]}
    assert relocate_in_patch(target(start=50, end=50), files) == (40, 40)


def test_a_missing_file_or_quote_is_not_found() -> None:
    assert relocate_in_patch(target(file="other.py"), parse_patch(PATCH)) is None
    assert relocate_in_patch(target(quote="nope"), parse_patch(PATCH)) is None


def test_text_comments_follow_their_quote_too() -> None:
    wanted = {"start": 1, "end": 1, "quote": "Fix the bug"}
    assert relocate_in_text(wanted, "Fix the bug\n\nbody") == (1, 1)
    assert relocate_in_text(wanted, "Title\n\nWhy.\nFix the bug") == (4, 4)
    assert relocate_in_text(wanted, "Something else") is None


def commit(sha: str, subject: str) -> Commit:
    return Commit(sha, "me", "2026-01-01 00:00", subject, subject)


def test_a_rebased_commit_is_found_by_its_patch_id() -> None:
    commits = [commit("a", "One"), commit("b", "Two")]
    ids = {"a": "p1", "b": "p2"}
    assert find_commit({"patch_id": "p2", "subject": "Renamed"}, commits, ids) == commits[1]


def test_a_changed_commit_is_found_by_its_subject() -> None:
    commits = [commit("a", "One"), commit("b", "Two")]
    ids = {"a": "p9", "b": "p8"}
    assert find_commit({"patch_id": "p2", "subject": "Two"}, commits, ids) == commits[1]


def test_the_subject_picks_between_commits_with_the_same_patch_id() -> None:
    commits = [commit("a", "Same"), commit("b", "Same too")]
    ids = {"a": "p1", "b": "p1"}
    assert find_commit({"patch_id": "p1", "subject": "Same too"}, commits, ids) == commits[1]


def test_no_commit_is_found_when_nothing_or_too_much_matches() -> None:
    commits = [commit("a", "Same"), commit("b", "Same")]
    assert find_commit({"patch_id": "p1", "subject": "Same"}, commits, {"a": "x", "b": "y"}) is None
    assert find_commit({"patch_id": "p1", "subject": "Gone"}, commits, {"a": "x", "b": "y"}) is None
    assert find_commit({"subject": "Gone"}, [], {}) is None
