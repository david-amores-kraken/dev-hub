"""Gather everything the pr-brief agents need about a PR into a run folder.

Usage: python -m dev_hub.prs.prepare <pr-number> [--again] [--tier note|light|standard|large] [--repo owner/name]

Refuses a PR that already has a brief, unless --again is passed: only the user asks for a
second brief, never the poller. Checks the PR head out into its own detached worktree (~/pr-reviews/worktrees/pr<n>), works out
the mechanical facts about the diff, and writes the run folder. Nothing in the PR is executed.
Prints the run folder path on the last line.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dev_hub.prs.config import SKILL_DIR
from dev_hub.prs.config import load as load_config
from dev_hub.prs.facts import file_facts, summarise
from dev_hub.prs.store import RUNS, WORKTREES
from dev_hub.prs.tiers import TIERS, choose_tier
from dev_hub.review_context import (
    Refused,
    asana_tasks,
    context_files,
    gh_json,
    gh_paginate,
    matching_rules,
    repo_skills,
    run,
    user_facing,
)

# Per-commit facts mean one diff per commit; past this, only the whole-PR facts are worked out.
MAX_COMMITS_WITH_FACTS = 60
PERSONAS = (
    "domain",
    "correctness",
    "cross-client",
    "tests",
    "conventions",
    "naming",
    "ux",
)
# Personas that run only when the PR changes something an end user sees.
USER_FACING_PERSONAS = ("ux",)
# Who reviews at each tier: nobody for a PR where every change is mechanical, one general
# reviewer for a small safe PR, and the specialised personas for everything else.
TIER_PERSONAS = {"note": (), "light": ("general",)}
DISCUSSION_BODY_LIMIT = 1500
THREAD_EXCERPT_LIMIT = 240
THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved isOutdated path line originalLine
          opener: comments(first: 1) {
            totalCount
            nodes { author { login __typename } body url }
          }
          latest: comments(last: 1) { nodes { author { login } } }
        }
      }
    }
  }
}
"""


def main() -> None:
    args = sys.argv[1:]
    repo_arg = None
    again = "--again" in args
    if again:
        args.remove("--again")
    forced_tier = None
    if "--tier" in args:
        i = args.index("--tier")
        forced_tier = args[i + 1] if i + 1 < len(args) else ""
        del args[i : i + 2]
        if forced_tier not in TIERS:
            raise SystemExit(f"--tier must be one of: {', '.join(TIERS)}")
    if "--repo" in args:
        i = args.index("--repo")
        repo_arg = args[i + 1]
        del args[i : i + 2]
    if len(args) != 1 or not args[0].isdigit():
        raise SystemExit(
            "usage: prepare.py <pr-number> [--again] [--tier note|light|standard|large] [--repo owner/name]"
        )
    pr = int(args[0])
    previous = _previous_run(RUNS / f"pr{pr}")
    if previous and not again:
        raise Refused(
            f"PR #{pr} already has a brief ({Path(previous['dir']).name}); "
            "pass --again to brief it again"
        )

    main_repo = _main_worktree()
    repo = repo_arg or _origin_repo(main_repo)
    data = gh_json(
        [
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            (
                "number,title,body,url,author,state,isDraft,headRefName,headRefOid,baseRefName,"
                "baseRefOid,commits,files,additions,deletions,changedFiles,labels,reviewRequests,"
                "latestReviews,reviewDecision,createdAt"
            ),
        ]
    )
    assert isinstance(data, dict)
    if data["state"] != "OPEN":
        raise Refused(f"PR #{pr} is {data['state'].lower()}")
    if data["isDraft"] and not forced_tier:
        raise Refused(f"PR #{pr} is a draft; pass --tier to brief it anyway")
    sha = data["headRefOid"]
    me = run(["gh", "api", "user", "--jq", ".login"]).strip()

    head_ref = f"refs/pr-brief/pr{pr}"
    git = ["git", "-C", str(main_repo)]
    run(
        [
            *git,
            "fetch",
            "-q",
            "origin",
            f"+refs/pull/{pr}/head:{head_ref}",
            data["baseRefOid"],
        ]
    )
    if run([*git, "rev-parse", head_ref]).strip() != sha:
        raise Refused(f"PR #{pr} moved while it was being fetched; try again")
    base = run([*git, "merge-base", data["baseRefOid"], sha]).strip()
    worktree = _checkout(main_repo, pr, sha)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / f"pr{pr}" / f"{stamp}-{sha[:7]}"
    (run_dir / "out").mkdir(parents=True)
    earlier = _earlier_findings(previous)
    if earlier is not None:
        (run_dir / "earlier-findings.json").write_text(json.dumps(earlier, indent=1))

    diff = run([*git, "-c", "core.quotePath=false", "diff", "--no-ext-diff", "-M", base, sha])
    (run_dir / "diff.patch").write_text(diff)
    diff_index = _diff_index(diff)
    (run_dir / "diff-index.json").write_text(json.dumps(diff_index, indent=1))

    files = file_facts(main_repo, base, sha, worktree)
    owners, my_teams = _owners(worktree, [f["path"] for f in files], me)
    for f in files:
        f["owners"] = owners.get(f["path"], [])
        f["owned_by_my_team"] = bool(set(f["owners"]) & my_teams)
        f["github_anchor"] = "diff-" + hashlib.sha256(f["path"].encode()).hexdigest()
        f["diff_lines"] = diff_index.get(f["path"])

    commits = _commit_facts(main_repo, base, sha, data["commits"])
    _mark_new(commits, previous)
    checks = _checks(repo, pr)
    discussion = _discussion(repo, pr, me)
    (run_dir / "discussion.json").write_text(json.dumps(discussion, indent=2))
    threads = _threads(repo, pr, me, data["author"]["login"])

    changed = [f["path"] for f in files]
    since = _since_previous(main_repo, previous, sha)
    meta = {
        "repo": repo,
        "pr": pr,
        "url": data["url"],
        "title": data["title"],
        "author": data["author"]["login"],
        "me": me,
        "my_teams": sorted(my_teams),
        "draft": data["isDraft"],
        "head_ref": data["headRefName"],
        "base_ref": data["baseRefName"],
        "sha": sha,
        "base_sha": base,
        "worktree": str(worktree),
        "main_repo": str(main_repo),
        "run_dir": str(run_dir),
        "created": stamp,
        "pr_created": data["createdAt"],
        "additions": data["additions"],
        "deletions": data["deletions"],
        "labels": [label["name"] for label in data["labels"]],
        "review_requests": [
            r.get("login") or r.get("slug") or r.get("name") for r in data["reviewRequests"]
        ],
        "reviews": [
            {"author": r["author"]["login"], "state": r["state"]} for r in data["latestReviews"]
        ],
        "review_decision": data["reviewDecision"],
        "checks": checks,
        "asana_tasks": asana_tasks(
            [data["body"] or ""]
            + [f"{c['messageHeadline']}\n{c['messageBody']}" for c in data["commits"]]
        ),
        "context_files": context_files(worktree, changed),
        "rules": matching_rules(worktree, changed),
        "skills": repo_skills(worktree),
        "user_facing": user_facing(diff),
        "since_previous": since,
        "earlier_findings": None if earlier is None else len(earlier),
        "discussion_count": len(discussion),
        "threads": threads,
    }
    meta["tier"], meta["tier_reason"] = choose_tier(files, load_config(), forced_tier)
    tier_personas = TIER_PERSONAS.get(meta["tier"])
    meta["personas"] = (
        list(tier_personas)
        if tier_personas is not None
        else [p for p in PERSONAS if meta["user_facing"] or p not in USER_FACING_PERSONAS]
    )
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (run_dir / "facts.json").write_text(json.dumps({"files": files, "commits": commits}, indent=1))
    (run_dir / "pr.md").write_text(_pr_text(data))
    (run_dir / "pr-context.md").write_text(_context_text(meta, files, commits))
    shutil.copy(SKILL_DIR / "reference" / "brief.md", run_dir / "brief.md")

    substantive = sum(f["substantive_lines"] for f in files)
    print(f"files: {len(files)} · substantive lines: {substantive} · commits: {len(commits)}")
    print(f"tier: {meta['tier']} ({meta['tier_reason']})")
    print(f"personas: {', '.join(meta['personas']) or 'none'}")
    print(run_dir)


def _main_worktree() -> Path:
    common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]).strip()
    return Path(common).parent


def _origin_repo(main_repo: Path) -> str:
    url = run(["git", "-C", str(main_repo), "remote", "get-url", "origin"]).strip()
    repo = re.sub(r"^(git@github\.com:|https://github\.com/)", "", url).removesuffix(".git")
    if repo.count("/") != 1:
        raise Refused(f"could not parse the origin remote: {url}")
    return repo


def _checkout(main_repo: Path, pr: int, sha: str) -> Path:
    """A detached worktree at the PR head. Hooks are off, so checking out runs nothing."""
    worktree = WORKTREES / f"pr{pr}"
    no_hooks = ["-c", "core.hooksPath=/dev/null"]
    if (worktree / ".git").exists():
        run(
            [
                "git",
                "-C",
                str(worktree),
                *no_hooks,
                "checkout",
                "-q",
                "--detach",
                "--force",
                sha,
            ]
        )
        run(["git", "-C", str(worktree), "clean", "-q", "-fdx"])
    else:
        WORKTREES.mkdir(parents=True, exist_ok=True)
        run(["git", "-C", str(main_repo), "worktree", "prune"])
        run(
            [
                "git",
                "-C",
                str(main_repo),
                *no_hooks,
                "worktree",
                "add",
                "-q",
                "--detach",
                str(worktree),
                sha,
            ]
        )
    return worktree


def _previous_run(pr_runs: Path) -> dict | None:
    """The latest earlier run that produced a report, if any."""
    for folder in sorted(pr_runs.glob("*"), reverse=True):
        meta, report = folder / "meta.json", folder / "report.json"
        if meta.is_file() and report.is_file() and not (folder / "FAILED").exists():
            return {"dir": str(folder), "sha": json.loads(meta.read_text())["sha"]}
    return None


def _earlier_findings(previous: dict | None) -> list[dict] | None:
    """The last brief's findings, one per persona finding, for the personas to follow up.

    None when there's no earlier brief, or it's from before findings had IDs.
    """
    if not previous:
        return None
    report = json.loads((Path(previous["dir"]) / "report.json").read_text())
    items = [item for card in report.get("findings", []) for item in card["items"]]
    if not items or not all("id" in item for item in items):
        return [] if "findings" in report and not items else None
    return [
        {
            "id": item["id"],
            "agent": item["agent"],
            "severity": item["severity"],
            "title": item["title"],
            "body": item["body"],
            "locations": [
                {k: loc[k] for k in ("path", "start", "end", "side")}
                for loc in item.get("locations", [])
            ],
        }
        for item in items
    ]


def _since_previous(main_repo: Path, previous: dict | None, sha: str) -> dict | None:
    if not previous:
        return None
    git = ["git", "-C", str(main_repo)]
    old = previous["sha"]
    if old == sha:
        return {"run": previous["dir"], "sha": old, "same_head": True}
    ancestor = _is_ancestor(main_repo, old, sha)
    new_commits = (
        run([*git, "log", "--format=%h %s", f"{old}..{sha}"]).strip().splitlines()
        if ancestor
        else []
    )
    return {
        "run": previous["dir"],
        "sha": old,
        "same_head": False,
        "force_pushed": not ancestor,
        "new_commits": new_commits,
    }


def _is_ancestor(main_repo: Path, old: str, new: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(main_repo), "merge-base", "--is-ancestor", old, new],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _diff_index(diff: str) -> dict[str, list[int]]:
    """For each file, the first and last line of its section in diff.patch (1-based)."""
    index: dict[str, list[int]] = {}
    current = None
    start = 0
    lines = diff.splitlines()
    for number, line in enumerate(lines, start=1):
        if line.startswith("diff --git "):
            if current:
                index[current] = [start, number - 1]
            current, start = None, number
        elif current is None and line.startswith("+++ "):
            target = line[4:].rstrip("\t")
            current = None if target == "/dev/null" else target.removeprefix("b/")
        elif current is None and line.startswith("--- ") and line[4:].strip() != "/dev/null":
            current = line[4:].rstrip("\t").removeprefix("a/")
        elif current is None and line.startswith("rename to "):
            current = line.removeprefix("rename to ")
    if current:
        index[current] = [start, len(lines)]
    return index


def _owners(worktree: Path, paths: list[str], me: str) -> tuple[dict[str, list[str]], set[str]]:
    """CODEOWNERS teams per file, using the repo's own matcher, and the teams the user is in."""
    teams = gh_paginate("user/teams")
    my_teams = {f"@{t['organization']['login']}/{t['slug']}" for t in teams}
    my_teams.add(f"@{me}")
    codeowners = worktree / ".github" / "CODEOWNERS"
    try:
        sys.path.insert(0, str(worktree / "src"))
        from tools.codeowners import CodeOwnersMatcher  # ty: ignore[import-not-found]

        matcher = CodeOwnersMatcher.from_codeowners_file(codeowners)
        return {p: list(matcher.get_codeowners(p)) for p in paths}, my_teams
    except Exception as error:
        print(f"warning: no CODEOWNERS data ({error})", file=sys.stderr)
        return {}, my_teams
    finally:
        sys.path.remove(str(worktree / "src"))


def _commit_facts(main_repo: Path, base: str, sha: str, pr_commits: list[dict]) -> list[dict]:
    git = ["git", "-C", str(main_repo)]
    listing = run([*git, "rev-list", "--reverse", "--parents", f"{base}..{sha}"]).split("\n")
    messages = {c["oid"]: c for c in pr_commits}
    commits = []
    for line in filter(None, listing):
        oid, *parents = line.split()
        info = messages.get(oid, {})
        entry = {
            "sha": oid,
            "short": oid[:7],
            "headline": info.get("messageHeadline")
            or run([*git, "log", "-1", "--format=%s", oid]).strip(),
            "author": ", ".join(
                a.get("login") or a.get("name", "") for a in info.get("authors", [])
            ),
        }
        if len(parents) > 1:
            # A merge from the base branch. Only conflict resolutions are the author's own work.
            remerge = run([*git, "show", "--remerge-diff", "--format=", "--numstat", oid])
            resolved = [r for r in remerge.splitlines() if r.strip()]
            entry |= {
                "merge": True,
                "files": len(resolved),
                "summary": {
                    "mechanical": None if resolved else "clean merge, no conflicts resolved",
                    "paths": [r.split("\t")[-1] for r in resolved],
                },
            }
        else:
            # Survives a rebase, so the next brief can tell which commits are really new.
            patch = run([*git, "show", "--format=", "--no-ext-diff", oid])
            entry["patch_id"] = (
                run(["git", "patch-id", "--stable"], input=patch).split() or [None]
            )[0]
            if len(listing) - 1 <= MAX_COMMITS_WITH_FACTS:
                entry["summary"] = summarise(file_facts(main_repo, parents[0], oid, None))
        commits.append(entry)
    return commits


def _mark_new(commits: list[dict], previous: dict | None) -> None:
    """Whether each commit is new since the last brief. A rebased commit keeps its patch ID."""
    if not previous:
        return
    seen = json.loads((Path(previous["dir"]) / "facts.json").read_text())["commits"]
    shas = {c["sha"] for c in seen}
    patches = {c["patch_id"] for c in seen if c.get("patch_id")}
    for c in commits:
        c["new"] = c["sha"] not in shas and c.get("patch_id") not in patches


def _checks(repo: str, pr: int) -> dict:
    # `gh pr checks` exits non-zero while checks fail or are pending, but still prints them.
    raw = run(
        ["gh", "pr", "checks", str(pr), "--repo", repo, "--json", "name,bucket,link"],
        check=False,
    )
    try:
        checks = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return {"available": False}
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["bucket"]] = counts.get(check["bucket"], 0) + 1
    failing = [
        {"name": c["name"], "link": c["link"]} for c in checks if c["bucket"] in ("fail", "cancel")
    ]
    return {"available": True, "counts": counts, "failing": failing[:20]}


def _discussion(repo: str, pr: int, me: str) -> list[dict]:
    """Review comments other people have left, so the agents don't just repeat them."""
    items = []
    for review in gh_paginate(f"repos/{repo}/pulls/{pr}/reviews"):
        if (review.get("body") or "").strip():
            items.append(
                {
                    "kind": "review",
                    "author": review["user"]["login"],
                    "state": review["state"],
                    "body": review["body"][:DISCUSSION_BODY_LIMIT],
                }
            )
    for comment in gh_paginate(f"repos/{repo}/pulls/{pr}/comments"):
        items.append(
            {
                "kind": "inline",
                "author": comment["user"]["login"],
                "path": comment["path"],
                "line": comment.get("line") or comment.get("original_line"),
                "outdated": comment.get("line") is None,
                "body": comment["body"][:DISCUSSION_BODY_LIMIT],
            }
        )
    for comment in gh_paginate(f"repos/{repo}/issues/{pr}/comments"):
        if comment["user"]["type"] == "Bot":
            continue
        items.append(
            {
                "kind": "comment",
                "author": comment["user"]["login"],
                "body": comment["body"][:DISCUSSION_BODY_LIMIT],
            }
        )
    for item in items:
        item["mine"] = item["author"] == me
    return items


def _threads(repo: str, pr: int, me: str, author: str) -> dict:
    """Unresolved review threads other reviewers opened, and whether the author has answered."""
    owner, name = repo.split("/")
    try:
        pages = gh_json(
            [
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={pr}",
                "-f",
                f"query={THREADS_QUERY}",
            ]
        )
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"warning: no review threads ({error})", file=sys.stderr)
        return {"available": False}
    assert isinstance(pages, list)
    nodes = [
        node
        for page in pages
        for node in page["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    ]
    open_threads = []
    resolved = 0
    for node in nodes:
        opener = node["opener"]["nodes"][0] if node["opener"]["nodes"] else None
        who = (opener or {}).get("author") or {}
        login = who.get("login", "")
        if not opener or login in ("", me, author) or who.get("__typename") == "Bot":
            continue
        if node["isResolved"]:
            resolved += 1
            continue
        latest = (node["latest"]["nodes"] or [{}])[0].get("author") or {}
        count = node["opener"]["totalCount"]
        open_threads.append(
            {
                "reviewer": login,
                "path": node["path"],
                "line": node["line"] or node["originalLine"],
                "outdated": node["isOutdated"],
                "excerpt": " ".join(opener["body"].split())[:THREAD_EXCERPT_LIMIT],
                "url": opener["url"],
                "replies": count - 1,
                "author_replied": count > 1 and latest.get("login") == author,
            }
        )
    return {"available": True, "open": open_threads, "resolved": resolved}


def _pr_text(data: dict) -> str:
    commits = "\n\n".join(
        f"### {c['oid'][:7]} {c['messageHeadline']}\n\n{c['messageBody'].strip()}"
        for c in data["commits"]
    )
    return (
        f"# {data['title']}\n\n{data['url']} · by {data['author']['login']}\n\n"
        f"## Description\n\n{(data['body'] or '').strip() or '(empty)'}\n\n"
        f"## Commits ({len(data['commits'])})\n\n{commits}\n"
    )


def _context_text(meta: dict, files: list[dict], commits: list[dict]) -> str:
    def file_line(f: dict) -> str:
        notes = [f["status"]]
        if f["old_path"]:
            notes.append(f"from `{f['old_path']}`")
        notes.append(f"+{f['additions']}/-{f['deletions']}")
        if f["moved_lines"]:
            notes.append(f"{f['moved_lines']} moved")
        if f["mechanical"]:
            notes.append(f"MECHANICAL: {f['mechanical']}")
        if f["owned_by_my_team"]:
            notes.append("your team owns it")
        return f"- `{f['path']}` ({', '.join(notes)})"

    def commit_line(c: dict) -> str:
        summary = c.get("summary") or {}
        notes = []
        if c.get("merge"):
            notes.append("merge commit")
        if "files" in summary:
            notes.append(
                f"{summary['files']} files, {summary['substantive_lines']} substantive lines"
            )
        if summary.get("mechanical"):
            notes.append(f"MECHANICAL: {summary['mechanical']}")
        if c.get("new"):
            notes.append("new since the last brief")
        return f"- `{c['short']}` {c['headline']}" + (f" ({'; '.join(notes)})" if notes else "")

    since = meta["since_previous"]
    if not since:
        since_text = "first brief for this PR"
    elif since["same_head"]:
        since_text = "same head as the last brief"
    elif since["force_pushed"]:
        since_text = f"force-pushed since the last brief (was `{since['sha'][:7]}`)"
    else:
        since_text = f"{len(since['new_commits'])} new commit(s) since the last brief at `{since['sha'][:7]}`"
    if meta["earlier_findings"] is not None:
        since_text += f"; its {meta['earlier_findings']} finding(s) are in `earlier-findings.json`"
    elif since:
        since_text += "; it's in an older format, so there are no earlier findings to follow up"

    return f"""# PR #{meta["pr"]} brief context

- **PR:** {meta["url"]} — {meta["title"]}
- **Author:** {meta["author"]} · **you are:** {meta["me"]} (teams: {", ".join(meta["my_teams"])})
- **Head:** `{meta["sha"]}` · **merge base:** `{meta["base_sha"]}` (into `{meta["base_ref"]}`)
- **Code at the PR head:** `{meta["worktree"]}/` (read files there, by absolute path)
- **Run folder:** `{meta["run_dir"]}`
- **Tier:** {meta["tier"]} ({meta["tier_reason"]})
- **Since last brief:** {since_text}
- **CI:** {json.dumps(meta["checks"].get("counts", "unavailable"))}
- **Discussion so far:** {meta["discussion_count"]} comment(s) by others, in `discussion.json`

## Asana tasks linked from the PR and commits

{chr(10).join(f"- `{t['id']}`: {t['url']}" for t in meta["asana_tasks"]) or "- none"}

## Commits ({len(commits)})

{chr(10).join(commit_line(c) for c in commits)}

## Changed files ({len(files)})

Full facts per file (signals, owners, moved lines, diff.patch line range) are in `facts.json`.

{chr(10).join(file_line(f) for f in files)}

## User-facing files (UX persona)

{chr(10).join(f"- `{f['path']}`: {f['why']}" for f in meta["user_facing"]) or "- none"}

## Guidance files along the changed paths (at the PR head)

{chr(10).join(f"- `{p}`" for p in meta["context_files"] + meta["rules"]) or "- none"}

## Repo skills (for picking domain knowledge)

{chr(10).join(f"- `{s['path']}`: {s['description']}" for s in meta["skills"])}
"""


if __name__ == "__main__":
    main()
