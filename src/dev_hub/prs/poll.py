"""Keep the to-review queue up to date, and brief the PRs the user asks for.

Usage: python -m dev_hub.prs.poll [--dry-run] [--only <pr-number>] [--queue-only | --requests-only]

Every tick lists the open, non-draft PRs whose review was requested from the user or one of
their groups, whoever wrote them, plus the open PRs the user added by link (manual.json),
and saves the ones with no brief in queue.json. The index page
shows that list; its Brief button (through server.py) writes requests/<pr>.json with a tier.
Each queued request is prepared (no model involved), then run through `claude -p` with the
1Password wrapper and a spending cap for the tier, then costed and added to the report.

PRs by `auto_brief_authors` in config.json are briefed without a click, at the tier picked by size.

A PR counts as done only once it has a report.json, so a run that dies, for example because
nobody approved the 1Password prompt, can be run again.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dev_hub.config import repo_dir
from dev_hub.prs.assemble import report_url
from dev_hub.prs.config import load
from dev_hub.prs.manual import fetch_pr
from dev_hub.prs.store import (
    HOME,
    QUEUE,
    REQUESTS,
    STATE,
    all_requests,
    brief_runs,
    drop_manual,
    now,
    read_json,
    read_manual,
    read_queue,
    write_json,
    write_request,
)
from dev_hub.prs.tiers import suggest_tier

LOG = HOME / "poll.log"
LOCK = HOME / "poll.lock"
QUEUE_LOCK = HOME / "queue.lock"
LOGIN_FAILURE_MARKERS = (
    "failed to fetch api key",
    "apikeyhelper",
    "authorization",
    "authorisation",
    "unauthorized",
    "authentication",
)
RUN_NOTE = (
    "The poller already ran prepare.py for this PR, so skip step 1 of the skill. Run folder: {run}"
    " (tier: {tier}; personas: {personas})."
)


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    queue_only = "--queue-only" in args
    requests_only = "--requests-only" in args
    only = int(args[args.index("--only") + 1]) if "--only" in args else None
    HOME.mkdir(parents=True, exist_ok=True)
    REQUESTS.mkdir(exist_ok=True)
    config = load()
    state = read_json(STATE, {})

    found: list[dict] = []
    if not requests_only:
        found = [pr for pr in candidates(config) if only in (None, pr["number"])]
        pending = [pr for pr in found if not has_brief(pr["number"])]
        if dry_run:
            auto = auto_authors(config)
            for pr in pending:
                kind = "auto-brief" if pr["author"]["login"].lower() in auto else "queue"
                print(f"#{pr['number']} {pr['author']['login']}: {pr['title'][:70]} -> {kind}")
            print(f"{len(pending)} waiting, {len(found) - len(pending)} already briefed")
            return
        refresh_queue(config, pending)
    if queue_only:
        return

    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # the previous run is still working and will pick up new requests
        for request in all_requests():
            if request["status"] == "running":  # we hold the lock, so nothing is running
                write_request(request | {"status": "failed", "error": "interrupted; try again"})
        if process_requests(config, state) == "login":
            return
        auto = auto_authors(config)
        for pr in found:
            if pr["author"]["login"].lower() in auto and wanted(pr, state, config):
                outcome = brief(pr, config, state, None)
                write_json(STATE, state)
                if outcome == "login":
                    log("login failed: stopping until the next tick")
                    break


def module(name: str) -> list[str]:
    """The command that runs one of this package's modules with the same Python as the poller."""
    return [sys.executable, "-m", f"dev_hub.prs.{name}"]


def auto_authors(config: dict) -> set[str]:
    return {a.lower() for a in config.get("auto_brief_authors", [])}


def process_requests(config: dict, state: dict) -> str:
    """Brief every queued request, oldest first. Returns "login" if 1Password refused."""
    while True:
        queued = sorted(
            (r for r in all_requests() if r["status"] == "queued"), key=lambda r: r["requested_at"]
        )
        if not queued:
            return "done"
        request = queued[0]
        write_request(request | {"status": "running", "started_at": now()})
        entry = state.setdefault(str(request["pr"]), {"attempts": 0})
        entry["attempts"] = 0  # a click is a fresh start
        entry.pop("refused", None)
        pr = {
            "number": request["pr"],
            "title": request["title"],
            "updatedAt": request["updated_at"],
        }
        outcome = brief(pr, config, state, request["tier"])
        write_json(STATE, state)
        if outcome == "done":
            write_request(request | {"status": "done", "finished_at": now()})
            continue
        error = "login failed" if outcome == "login" else entry.get("refused") or entry.get("error")
        write_request(
            request | {"status": "failed", "finished_at": now(), "error": error or outcome}
        )
        if outcome == "login":
            log("login failed: stopping until the next tick")
            return "login"


def refresh_queue(config: dict, pending: list[dict]) -> None:
    """Save the PRs waiting for a brief, with a size and a suggested tier for each."""
    with QUEUE_LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        old = {item["number"]: item for item in read_queue()["items"]}
        items = [queue_item(pr, config, old.get(pr["number"])) for pr in pending]
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        write_json(QUEUE, {"refreshed": now(), "items": items})


def queue_item(pr: dict, config: dict, previous: dict | None) -> dict:
    """One row of queue.json. A PR that hasn't changed keeps its size, so gh isn't asked again."""
    if previous and previous["updated_at"] == pr["updatedAt"] and "additions" in previous:
        stats = {
            k: previous[k]
            for k in ("additions", "deletions", "changed_files", "suggested", "reason")
        }
    else:
        stats = pr_stats(pr["number"], config)
    return {
        "number": pr["number"],
        "title": pr["title"],
        "author": pr["author"]["login"],
        "url": pr["url"],
        "created_at": pr["createdAt"],
        "updated_at": pr["updatedAt"],
        "requested_via": pr["via"],
        **stats,
    }


def add_to_queue(pr: dict, config: dict) -> None:
    """Put a PR the user added by link in the queue now, without waiting for the next tick."""
    with QUEUE_LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        queue = read_queue()
        items = [item for item in queue["items"] if item["number"] != pr["number"]]
        items.append(queue_item(pr | {"via": ["link"]}, config, None))
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        write_json(QUEUE, queue | {"items": items})


def pr_stats(number: int, config: dict) -> dict:
    try:
        view = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                config["repo"],
                "--json",
                "additions,deletions,changedFiles,files",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        data = json.loads(view.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return {
            "additions": None,
            "deletions": None,
            "changed_files": None,
            "suggested": "standard",
            "reason": "size unknown",
        }
    suggested, reason = suggest_tier(data["files"], data["changedFiles"], config)
    return {
        "additions": data["additions"],
        "deletions": data["deletions"],
        "changed_files": data["changedFiles"],
        "suggested": suggested,
        "reason": reason,
    }


def candidates(config: dict) -> list[dict]:
    """Open PRs with a review requested from the user or a group, by anyone but the user."""
    me = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()
    found: dict[int, dict] = {}
    for target in ["@me", *config["reviewer_groups"]]:
        listing = subprocess.run(
            [
                "gh",
                "search",
                "prs",
                "--repo",
                config["repo"],
                "--state",
                "open",
                "--draft=false",
                f"--review-requested={target}",
                "--limit",
                "100",
                "--json",
                "number,title,author,createdAt,updatedAt,isDraft,url",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,  # a hung gh call would otherwise hold the lock and stall every later tick
        )
        for pr in json.loads(listing.stdout):
            if not pr["isDraft"] and pr["author"]["login"] != me:
                found.setdefault(pr["number"], pr | {"via": []})["via"].append(
                    "you" if target == "@me" else target
                )
    for number in read_manual():
        pr = fetch_pr(number, config)
        if pr["state"] != "OPEN":
            drop_manual(number)  # merged or closed: nothing left to review
        else:
            found.setdefault(number, pr | {"via": []})["via"].append("link")
    return sorted(found.values(), key=lambda pr: pr["updatedAt"])


def has_brief(number: int) -> bool:
    return bool(brief_runs(number))


def why_not(pr: dict, state: dict, config: dict) -> str:
    entry = state.get(str(pr["number"]), {})
    if has_brief(pr["number"]):
        return "already briefed"
    if entry.get("refused") and entry.get("updated_at") == pr["updatedAt"]:
        return f"refused: {entry['refused']}"
    if entry.get("attempts", 0) >= config["max_attempts"]:
        return f"gave up after {entry['attempts']} attempts ({entry.get('error', '?')[:60]})"
    return "wanted"


def wanted(pr: dict, state: dict, config: dict) -> bool:
    return why_not(pr, state, config) == "wanted"


def brief(pr: dict, config: dict, state: dict, tier: str | None) -> str:
    """Brief one PR at the given tier (None: by size). Returns done, failed, refused or login."""
    number = pr["number"]
    entry = state.setdefault(str(number), {"attempts": 0})
    entry["updated_at"] = pr["updatedAt"]

    started = time.monotonic()
    prepared = subprocess.run(
        [*module("prepare"), str(number), *(["--tier", tier] if tier else [])],
        capture_output=True,
        text=True,
        cwd=repo_dir(),
        check=False,
    )
    if prepared.returncode != 0:
        message = (prepared.stderr or prepared.stdout).strip().splitlines()[-1:] or ["unknown"]
        if "refusing" in message[0]:
            entry["refused"] = message[0]
            log(f"#{number} refused: {message[0]}")
            return "refused"
        entry |= {"attempts": entry["attempts"] + 1, "error": f"prepare: {message[0]}"}
        log(f"#{number} prepare failed: {message[0]}")
        return "failed"
    entry.pop("refused", None)
    prepare_seconds = round(time.monotonic() - started)
    run_dir = Path(prepared.stdout.strip().splitlines()[-1])
    meta = json.loads((run_dir / "meta.json").read_text())
    tier = meta["tier"]
    log(f"#{number} {tier} tier ({meta['tier_reason']}): briefing")

    session_id = str(uuid.uuid4())
    (run_dir / "session.json").write_text(json.dumps({"session_id": session_id}))
    cli_cost = None
    error = ""
    if tier != "note":
        outcome, cli_cost, error = run_claude(number, run_dir, meta, config, session_id)
        if outcome == "login":
            entry["error"] = "login failed"
            return "login"
        if outcome == "failed":
            entry |= {"attempts": entry["attempts"] + 1, "error": error}
            log(f"#{number} claude failed: {error}")

    if tier != "note":
        subprocess.run(
            [*module("usage"), str(run_dir), session_id]
            + ["--prepare-seconds", str(prepare_seconds)]
            + (["--cli-cost", str(cli_cost)] if cli_cost is not None else []),
            capture_output=True,
            check=False,
        )
    outputs = list((run_dir / "out").glob("*.json"))
    if tier != "note" and not outputs:
        # Nobody wrote anything, so a report would be empty: leave the PR pending for a retry.
        entry |= {"attempts": entry["attempts"] + 1, "error": error or "no agent wrote output"}
        (run_dir / "FAILED").write_text(entry["error"])
        log(f"#{number} no agent output; will retry ({entry['attempts']} attempts)")
        return "failed"
    # The skill assembles at the end; do it again so the report has the spend, and so a session
    # that ran out of budget or time still leaves a brief with whatever the agents finished.
    assembled = subprocess.run(
        [*module("assemble"), str(run_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if assembled.returncode != 0 or not (run_dir / "report.json").is_file():
        entry |= {"attempts": entry["attempts"] + 1, "error": "no report"}
        return "failed"
    entry.pop("error", None)
    entry["attempts"] = 0
    notify(f"Brief ready: #{number}", pr["title"])
    log(f"#{number} done: {report_url(number, run_dir.name)}")
    return "done"


def run_claude(
    number: int, run_dir: Path, meta: dict, config: dict, session_id: str
) -> tuple[str, float | None, str]:
    command = [
        config["with_1password"],
        config["claude"],
        "-p",
        f"/pr-brief {number}",
        "--output-format",
        "json",
        "--max-budget-usd",
        str(config["budget_usd"][meta["tier"]]),
        "--permission-prompts",
        "none",
        "--session-id",
        session_id,
        "--append-system-prompt",
        RUN_NOTE.format(run=run_dir, tier=meta["tier"], personas=", ".join(meta["personas"])),
    ]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=repo_dir(),
            timeout=config["timeout_minutes"] * 60,
            check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return "failed", None, f"timed out after {config['timeout_minutes']} minutes"
    text = (done.stdout + done.stderr).lower()
    result: dict = {}
    with contextlib.suppress(json.JSONDecodeError):
        result = json.loads(done.stdout)
    if done.returncode != 0 and not result and any(m in text for m in LOGIN_FAILURE_MARKERS):
        return "login", None, ""
    cost = result.get("total_cost_usd")
    if result.get("is_error"):
        return "failed", cost, str(result.get("subtype") or result.get("result") or "error")[:200]
    return "ok", cost, ""


def notify(title: str, message: str) -> None:
    def clean(text: str) -> str:
        return text.replace("\\", " ").replace('"', "'")[:120]

    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{clean(message)}" with title "{clean(title)}"',
        ],
        capture_output=True,
        check=False,
    )


def log(message: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    with LOG.open("a") as handle:
        handle.write(f"{stamp} {message}\n")


if __name__ == "__main__":
    main()
