"""Ask git about a branch: its commits and their diffs, measured against the base ref.

Branches and commits come straight from the repo's refs, so nothing is checked out and the
working tree is never touched. A branch's commits are the ones the base doesn't have (`base..branch`),
which stays right after the branch is rebased or the base moves on. The "all changes" diff uses
`base...branch`, so it shows what the branch changed since it left the base, not what the base did.
Arguments are passed to git as a list (never through a shell), and branch names are always written
as `refs/heads/<name>`, so a name can't be read as an option.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

from dev_hub.config import base_ref, repo_dir

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FIELD = "\x1f"
RECORD = "\x1e"


class GitError(Exception):
    """git failed, e.g. the repo or the base ref doesn't exist."""


@dataclass(frozen=True)
class Branch:
    name: str
    commits: int  # how many it has that the base doesn't
    updated: str  # date of the newest commit, YYYY-MM-DD HH:MM
    subject: str  # of the newest commit


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    date: str  # YYYY-MM-DD HH:MM
    subject: str
    message: str  # the whole message, subject included


def list_branches() -> list[Branch]:
    """Local branches with commits the base doesn't have, newest first."""
    fields = ["%(refname:short)", "%(committerdate:format:%Y-%m-%d %H:%M)", "%(subject)"]
    output = _git(
        "for-each-ref",
        f"--no-merged={base_ref()}",
        "--sort=-committerdate",
        f"--format={FIELD.join(fields)}",
        "refs/heads",
    )
    branches = []
    for line in output.splitlines():
        name, updated, subject = line.split(FIELD)
        count = int(_git("rev-list", "--count", f"{base_ref()}..refs/heads/{name}"))
        branches.append(Branch(name, count, updated, subject))
    return branches


def has_branch(name: str) -> bool:
    try:
        _git("rev-parse", "--verify", "--quiet", f"refs/heads/{name}^{{commit}}")
    except GitError:
        return False
    return True


def list_commits(branch: str) -> list[Commit]:
    """The branch's commits, oldest first, as a PR lists them."""
    fields = ["%H", "%an", "%ad", "%s", "%B"]
    output = _git(
        "log",
        "--reverse",
        "--date=format:%Y-%m-%d %H:%M",
        f"--format={FIELD.join(fields)}{RECORD}",
        f"{base_ref()}..refs/heads/{branch}",
    )
    commits = []
    for record in output.split(RECORD):
        if record.strip():
            sha, author, date, subject, message = record.strip("\n").split(FIELD)
            commits.append(Commit(sha, author, date, subject, message.strip()))
    return commits


def commit_patch(sha: str) -> str:
    """What one commit changed. The caller must have checked that `sha` is a commit of the branch."""
    if not SHA_RE.match(sha):
        raise GitError(f"not a commit: {sha}")
    return _git("show", "--format=", "--patch", "-M", "--no-color", "--no-ext-diff", sha)


def branch_patch(branch: str) -> str:
    """Everything the branch changed since it left the base."""
    return _git("diff", "-M", "--no-color", "--no-ext-diff", f"{base_ref()}...refs/heads/{branch}")


def patch_id(sha: str) -> str | None:
    """git's fingerprint of what a commit changes. It stays the same when the commit is rebased,
    so it is how a commit is found again after its sha changes."""
    output = _git("patch-id", "--stable", stdin=commit_patch(sha))
    return output.split()[0] if output.strip() else None


def _git(*args: str, stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir()), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        raise GitError(str(error)) from error
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def branch_tip(branch: str) -> str:
    """The sha of the branch's newest commit."""
    return _git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}").strip()


def branch_files(branch: str) -> list[str]:
    """The files the branch changed since it left the base."""
    output = _git("diff", "-M", "--name-only", f"{base_ref()}...refs/heads/{branch}")
    return output.splitlines()


def branch_stats(branch: str) -> dict[str, Any]:
    """How big the branch's change is: files, lines added and removed, and when it was started."""
    numstat = _git("diff", "-M", "--numstat", f"{base_ref()}...refs/heads/{branch}")
    files = [line.split("\t") for line in numstat.splitlines() if line]
    dates = _git("log", "--format=%cI", f"{base_ref()}..refs/heads/{branch}").split()
    return {
        "files": [name for _, _, name in files],
        # Binary files show "-" instead of counts.
        "insertions": sum(int(added) for added, _, _ in files if added.isdigit()),
        "deletions": sum(int(removed) for _, removed, _ in files if removed.isdigit()),
        "commits": len(dates),
        "first_commit_at": min(dates, default=None),
    }
