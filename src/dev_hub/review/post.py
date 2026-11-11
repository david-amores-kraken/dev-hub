"""Put one persona's findings into the dev hub.

Reads `<run folder>/findings/<persona>.json` (the format is in the local-review skill's
reference/brief.md), checks it, and saves it in the branch's review file:

- A finding on a line of the diff becomes a comment on the "All changes" page.
- A finding on "PR description" becomes a comment on the description, and one on "commit <sha>" a
  comment on that commit's message.
- A finding that can't be placed (a file outside the diff, say) stays in the review's summary card.
- The summary, the verdict and the findings the persona says are fixed go in a review, shown on the
  overview.

Finding IDs are numbered here so they never clash with earlier runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dev_hub.diffs import git
from dev_hub.diffs.anchors import Row, parse_patch
from dev_hub.diffs.comments import MAX_QUOTE, parse_target
from dev_hub.diffs.store import add_comment, add_review, list_comments, load_description
from dev_hub.review.personas import PERSONAS
from dev_hub.review.prepare import hub_url

SEVERITIES = ("blocker", "should-fix", "nit")
COMMIT_RE = re.compile(r"\bcommit\s+([0-9a-f]{7,40})\b", re.IGNORECASE)


def post(run_dir: Path, persona: str, dry_run: bool = False) -> str:
    """Save the persona's findings. Returns the line to print."""
    if persona not in PERSONAS:
        raise SystemExit(f"refusing: unknown persona {persona!r}; expected {', '.join(PERSONAS)}")
    emoji, name, prefix = PERSONAS[persona]
    receipt = run_dir / "posted" / f"{persona}.json"
    if receipt.exists():
        raise SystemExit(f"refusing: {persona} already posted for this run")
    meta = json.loads((run_dir / "meta.json").read_text())
    if meta.get("mode") != "local":
        raise SystemExit("refusing: this run folder was prepared for a PR, not a local review")
    branch = meta["branch"]
    data = _load(run_dir, persona)

    # Number new findings after every ID this persona has used on the branch before.
    used = [
        int(c["finding_id"].split("-")[1])
        for c in list_comments(branch)
        if c.get("finding_id", "").startswith(f"{prefix}-")
    ]
    number = max(used, default=0) + 1
    rows = parse_patch((run_dir / "diff.patch").read_text())
    commits = {c.sha: c for c in git.list_commits(branch)}
    body = load_description(branch).body

    placed: list[tuple[dict[str, Any], str, dict[str, Any]]] = []  # (target, finding id, finding)
    unplaced = []
    for finding in data["findings"]:
        finding_id = f"{prefix}-{number}"
        number += 1
        target = _target(finding, meta, rows, commits, body)
        if target is None:
            where = finding.get("where") or f"{finding.get('path')}:{finding.get('line')}"
            unplaced.append(
                {
                    "finding_id": finding_id,
                    "severity": finding["severity"],
                    "where": where,
                    "body": finding["body"].strip(),
                }
            )
        else:
            placed.append((target, finding_id, finding))

    total = len(data["findings"])
    blockers = sum(f["severity"] == "blocker" for f in data["findings"])
    if total == 0:
        status = "LGTM"
    else:
        status = f"{total} finding{'s' * (total != 1)}" + (
            f" ({blockers} blocker{'s' * (blockers != 1)})" if blockers else ""
        )
    review = {
        "persona": persona,
        "name": name,
        "emoji": emoji,
        "sha": meta["sha"],
        "verdict": "lgtm" if total == 0 else "comments",
        "summary": data["summary"].strip(),
        "resolved": data.get("resolved") or [],
        "findings": [finding_id for _, finding_id, _ in placed]
        + [u["finding_id"] for u in unplaced],
        "unplaced": unplaced,
    }
    if dry_run:
        return json.dumps(
            {"review": review, "comments": [{"id": i, "target": t} for t, i, _ in placed]},
            indent=2,
            ensure_ascii=False,
        )

    for target, finding_id, finding in placed:
        add_comment(
            branch,
            target,
            finding["body"].strip(),
            persona=persona,
            author=f"{emoji} {name}",
            finding_id=finding_id,
            severity=finding["severity"],
        )
    add_review(branch, review, review["resolved"])
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps({"placed": len(placed), "unplaced": len(unplaced)}))
    return f"{name}: {status} — {hub_url(branch)}"


def _load(run_dir: Path, persona: str) -> dict[str, Any]:
    path = run_dir / "findings" / f"{persona}.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"refusing: can't read {path}: {error}") from error
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise SystemExit("refusing: findings need a non-empty 'summary'")
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise SystemExit("refusing: 'findings' must be a list (use [] for LGTM)")
    for i, finding in enumerate(findings):
        if finding.get("severity") not in SEVERITIES:
            raise SystemExit(f"refusing: finding {i}: 'severity' must be one of {SEVERITIES}")
        if not str(finding.get("body", "")).strip():
            raise SystemExit(f"refusing: finding {i}: 'body' is empty")
        if not finding.get("path") and not finding.get("where"):
            raise SystemExit(f"refusing: finding {i}: give 'path' + 'line', or 'where'")
    return data


def _target(
    finding: dict[str, Any],
    meta: dict[str, Any],
    rows: dict[str, list[Row]],
    commits: dict[str, git.Commit],
    description: str,
) -> dict[str, Any] | None:
    """Where a finding goes in the hub, or None if it has no place there."""
    path, line, side = finding.get("path"), finding.get("line"), finding.get("side", "RIGHT")
    allowed = meta["commentable_lines"].get(path, {}).get(side, []) if path else []
    if path and isinstance(line, int) and line in allowed:
        start = finding.get("start_line")
        start = start if isinstance(start, int) and start < line and start in allowed else line
        key = "old" if side == "LEFT" else "new"
        numbered = [(getattr(r, key), r.text) for r in rows.get(path, []) if getattr(r, key)]
        quote = "\n".join(text for number, text in numbered if start <= number <= line)
        target = {
            "kind": "line",
            "commit": None,
            "file": path,
            "side": key,
            "start": start,
            "end": line,
            "quote": quote,
        }
        return parse_target(target, set()) if quote else None

    where = str(finding.get("where") or "")
    if where.lower().startswith("pr description") and description.strip():
        lines = description.split("\n")
        target = {"kind": "pr_body", "commit": None, "start": 1, "end": len(lines)}
        return (
            parse_target({**target, "quote": description}, set())
            if len(description) <= MAX_QUOTE
            else None
        )

    if match := COMMIT_RE.search(where):
        commit = next((c for sha, c in commits.items() if sha.startswith(match[1].lower())), None)
        if commit is not None:
            lines = commit.message.split("\n")
            target = {"kind": "message", "commit": commit.sha, "start": 1, "end": len(lines)}
            parsed = parse_target({**target, "quote": commit.message}, set(commits))
            if parsed is not None:
                # Remember the commit, so the comment can follow it through a rebase.
                return parsed | {"subject": commit.subject, "patch_id": git.patch_id(commit.sha)}
    return None
