"""Gather everything the personas need to review a branch into a run folder.

The folder is what the personas read (see skills/local-review/reference/brief.md): the diff is
`base...branch` read from git, `pr.md` holds the draft title and description from the dev hub, and
earlier findings and my comments come from the hub's review file. `brief.md` is the skill's brief
with the command that posts findings filled in.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from dev_hub.config import HOST, PORT, base_ref, repo_dir
from dev_hub.diffs import git
from dev_hub.diffs.store import list_comments, list_reviews, load_description
from dev_hub.review.personas import PERSONAS, USER_FACING_PERSONAS

CLAUDE = Path.home() / ".claude"
BRIEF = Path(__file__).resolve().parents[3] / "skills" / "local-review" / "reference" / "brief.md"
PREFERENCES = [
    "comment-preferences.md",
    "commit-message-preferences.md",
    "pr-description-preferences.md",
]
POST_PLACEHOLDER = "{POST_COMMAND}"


def post_command() -> str:
    return f"{sys.executable} -m dev_hub.review post"


def hub_url(branch: str) -> str:
    return f"http://{HOST}:{PORT}/diffs/{branch}"


def describe(target: dict[str, Any]) -> str:
    """Where a comment is, in the words the personas use in `where`."""
    if target["kind"] == "pr_body":
        return "PR description"
    if target["kind"] == "message":
        return f"commit {target['commit'][:7]} message"
    return f"{target['file']}:{target['end']}"


def prepare(
    branch: str, helpers: ModuleType, final: bool = False, cwd: Path | None = None
) -> tuple[list[str], Path]:
    """Make the run folder. Returns the personas to start, and the folder."""
    cwd = cwd or Path.cwd()
    if not git.has_branch(branch):
        raise SystemExit(f"refusing: {branch!r} isn't a local branch of {repo_dir()}")
    sha = git.branch_tip(branch)
    commits = git.list_commits(branch)
    if not commits:
        raise SystemExit(f"refusing: {branch!r} has no commits that {base_ref()} doesn't have")
    description = load_description(branch)
    comments, reviews = list_comments(branch), list_reviews(branch)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    slug = re.sub(r"[^\w.-]+", "-", branch)
    run_dir = (
        repo_dir() / ".claude" / "local" / "local-review" / f"branch-{slug}" / f"{stamp}-{sha[:7]}"
    )
    run_dir.mkdir(parents=True)

    diff = git.branch_patch(branch)
    (run_dir / "diff.patch").write_text(diff)
    changed = git.branch_files(branch)
    (run_dir / "changed-files.txt").write_text("\n".join(changed) + "\n")

    # When the personas' checkout isn't the branch tip, give them the changed files at the tip.
    checkout_is_head = _head(cwd) == sha
    if not checkout_is_head:
        for path in changed:
            content = _show(sha, path)
            if content:
                target = run_dir / "head" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)

    (run_dir / "prior-findings.json").write_text(
        json.dumps(_prior(branch, reviews, comments), indent=2)
    )
    mine = [
        {
            "path": c["target"].get("file"),
            "line": c["target"]["end"],
            "where": describe(c["target"]),
            "body": c["text"],
        }
        for c in comments
        if not c.get("finding_id")
    ]
    (run_dir / "user-comments.json").write_text(json.dumps(mine, indent=2))

    title = description.title or commits[-1].subject
    commit_text = "\n\n".join(
        f"### {c.sha[:7]} {c.subject}\n\n{_rest(c)}".rstrip() for c in commits
    )
    (run_dir / "pr.md").write_text(
        f"# {title}\n\nLocal review of branch `{branch}` (no PR yet): {hub_url(branch)}\n\n"
        f"## Description\n\n{description.body.strip() or '(not written yet)'}\n\n"
        f"## Commits ({len(commits)})\n\n{commit_text}\n"
    )

    prefs = run_dir / "prefs"
    prefs.mkdir()
    for name in PREFERENCES:
        if (CLAUDE / name).is_file():
            shutil.copy(CLAUDE / name, prefs / name)
    (run_dir / "brief.md").write_text(_brief())

    first_run = not reviews
    root = _toplevel(cwd)
    user_facing = helpers.user_facing(diff)
    meta = {
        "mode": "local",
        "repo": str(repo_dir()),
        "branch": branch,
        "url": hub_url(branch),
        "sha": sha,
        "base": base_ref(),
        "checkout_is_head": checkout_is_head,
        "check_commit_messages": first_run or final,
        "first_run": first_run,
        "final": final,
        "commits": [{"sha": c.sha, "subject": c.subject} for c in commits],
        "context_files": helpers.context_files(root, changed),
        "rules": helpers.matching_rules(root, changed),
        "skills": helpers.repo_skills(root),
        "asana_tasks": helpers.asana_tasks([description.body, *[c.message for c in commits]]),
        "user_facing": user_facing,
        "commentable_lines": helpers.commentable_lines(diff),
    }
    personas = [p for p in PERSONAS if user_facing or p not in USER_FACING_PERSONAS]
    meta["personas"] = personas
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (run_dir / "pr-context.md").write_text(_context(meta, title, changed, run_dir))
    return personas, run_dir


def _brief() -> str:
    text = BRIEF.read_text()
    if POST_PLACEHOLDER not in text:
        raise SystemExit(f"refusing: {BRIEF} has no {POST_PLACEHOLDER} for the post command")
    return text.replace(POST_PLACEHOLDER, post_command())


def _prior(
    branch: str, reviews: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> dict[str, Any]:
    """What personas said before and how I answered, in the shape the brief describes."""
    findings = []
    for comment in comments:
        if not comment.get("finding_id"):
            continue
        triage = comment.get("triage")
        status = {"address": "endorsed", "dismiss": "rejected"}.get(triage, "pending")
        findings.append(
            {
                "id": comment["finding_id"],
                "persona": comment["persona"],
                "where": describe(comment["target"]),
                "text": comment["text"],
                "status": status,
                "addressed": bool(comment.get("replies")) or comment["status"] == "resolved",
                "user_replies": [],
            }
        )
    return {
        "reviews": [
            {
                "persona": r["persona"],
                "review_id": r["id"],
                "url": hub_url(branch),
                "sha": r["sha"][:12],
            }
            for r in reviews
        ],
        "findings": findings,
    }


def _context(meta: dict[str, Any], title: str, changed: list[str], run_dir: Path) -> str:
    if meta["checkout_is_head"]:
        code = "This checkout is the branch tip: read code straight from the repo."
    else:
        code = (
            f"This checkout is NOT the branch tip. Changed files as they are at the tip are in "
            f"`{run_dir}/head/`. For any other file, use `git show {meta['sha']}:<path>`."
        )
    lines = lambda items: "\n".join(items) or "- none"  # noqa: E731
    return f"""# Review context for branch `{meta["branch"]}`

- **Branch:** {title} (local review, no PR yet): {meta["url"]}
- **Tip:** `{meta["sha"]}` (against `{meta["base"]}`)
- **Run folder:** `{run_dir}`
- **Reading code:** {code}
- **Run:** {"first review of this branch" if meta["first_run"] else "re-run: see prior-findings.json"}{" · final pass" if meta["final"] else ""}
- **Commit messages:** {"check them (Writing persona)" if meta["check_commit_messages"] else "skip them: mid-loop feedback commits get squashed later"}

## Asana tasks linked from the description and commits (Domain persona)

{lines(f"- `{t['id']}`: {t['url']}" for t in meta["asana_tasks"])}

## Changed files ({len(changed)})

{lines(f"- `{p}`" for p in changed)}

## User-facing files (UX persona)

{lines(f"- `{f['path']}`: {f['why']}" for f in meta["user_facing"])}

## Guidance files along the changed paths

{lines(f"- `{p}`" for p in meta["context_files"] + meta["rules"])}

## Repo skills (for picking domain knowledge)

{lines(f"- `{s['path']}`: {s['description']}" for s in meta["skills"])}
"""


def _rest(commit: git.Commit) -> str:
    return commit.message.removeprefix(commit.subject).strip()


def _head(cwd: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd).strip()


def _toplevel(cwd: Path) -> Path:
    return Path(_run(["git", "rev-parse", "--show-toplevel"], cwd).strip())


def _show(sha: str, path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir()), "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""
