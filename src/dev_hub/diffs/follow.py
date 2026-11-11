"""Keep comments on the lines they were about, after a rebase or an edit.

A comment is saved against a commit's sha. A rebase gives the commit a new sha, so the comment is
matched to the new commit (by patch id, then by subject) and its lines are searched for by quote,
since the code around them may have shifted. The same is done for comments on the PR description
and on the "All changes" page, whose lines move when the text or the branch changes.

This runs whenever a page of the branch is shown, and saves what it moved, so the file always says
where each comment is now. A comment that can't be matched or found is left as it was. The page
lists it as one it couldn't place, with its quote.
"""

from __future__ import annotations

from typing import Any

from dev_hub.diffs import git
from dev_hub.diffs.anchors import Row, find_commit, parse_patch, relocate_in_patch, relocate_in_text
from dev_hub.diffs.git import Commit
from dev_hub.diffs.store import list_comments, set_targets


def follow(
    branch: str, commits: list[Commit], body: str | None = None, patch: str | None = None
) -> list[dict[str, Any]]:
    """The branch's comments, moved to where they are now. Pass the saved PR description as
    `body`, and the "All changes" patch as `patch`, to also check the comments on those."""
    comments = list_comments(branch)
    original = {c["id"]: c["target"] for c in comments}
    targets = dict(original)

    _follow_commits(comments, commits, targets)
    if body is not None:
        for comment in comments:
            if targets[comment["id"]]["kind"] == "pr_body":
                _move(targets, comment["id"], relocate_in_text(targets[comment["id"]], body))
    if patch is not None:
        files = parse_patch(patch)
        for comment in comments:
            target = targets[comment["id"]]
            if target["kind"] == "line" and target["commit"] is None:
                _move(targets, comment["id"], relocate_in_patch(target, files))

    moved = {key: target for key, target in targets.items() if target != original[key]}
    if moved:
        set_targets(branch, moved)
    return [{**comment, "target": targets[comment["id"]]} for comment in comments]


def _follow_commits(
    comments: list[dict[str, Any]], commits: list[Commit], targets: dict[str, dict[str, Any]]
) -> None:
    """Point comments whose commit sha has gone at the commit that replaced it."""
    shas = {commit.sha for commit in commits}
    stale = [c for c in comments if targets[c["id"]]["commit"] not in shas | {None}]
    if not stale:
        return
    patch_ids = {commit.sha: git.patch_id(commit.sha) for commit in commits}
    patches: dict[str, dict[str, list[Row]]] = {}
    for comment in stale:
        target = targets[comment["id"]]
        commit = find_commit(target, commits, patch_ids)
        if commit is None:
            continue
        targets[comment["id"]] = target = {
            **target,
            "commit": commit.sha,
            "subject": commit.subject,
            "patch_id": patch_ids[commit.sha],
        }
        if target["kind"] == "line":
            files = patches.setdefault(commit.sha, parse_patch(git.commit_patch(commit.sha)))
            _move(targets, comment["id"], relocate_in_patch(target, files))
        else:
            _move(targets, comment["id"], relocate_in_text(target, commit.message))


def _move(targets: dict[str, dict[str, Any]], key: str, lines: tuple[int, int] | None) -> None:
    if lines is not None:
        targets[key] = {**targets[key], "start": lines[0], "end": lines[1]}
