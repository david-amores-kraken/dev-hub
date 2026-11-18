"""Estimate what a pr-brief run cost, from the session's transcripts, and save it as cost.json.

Usage: python -m dev_hub.prs.usage <run folder> <session-id> [--cli-cost USD] [--prepare-seconds N]

The main session and every subagent it started keep their own transcript, so spend can be
split per agent. Prices are list prices from config.json, so the numbers are estimates: when
the CLI reported its own total (--cli-cost), that is saved next to them for comparison.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from dev_hub.prs.config import load

PROJECTS = Path.home() / ".claude" / "projects"
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.1


def main() -> None:
    args = sys.argv[1:]
    cli_cost = None
    prepare_seconds = None
    if "--prepare-seconds" in args:
        i = args.index("--prepare-seconds")
        prepare_seconds = float(args[i + 1])
        del args[i : i + 2]
    if "--cli-cost" in args:
        i = args.index("--cli-cost")
        cli_cost = float(args[i + 1])
        del args[i : i + 2]
    if len(args) != 2:
        raise SystemExit("usage: usage.py <run folder> <session-id> [--cli-cost USD]")
    run_dir, session_id = Path(args[0]).expanduser().resolve(), args[1]
    cost = session_cost(session_id, load()["prices_usd_per_mtok"])
    if cost is None:
        raise SystemExit(f"no transcript for session {session_id}")
    cost["cli_total_usd"] = cli_cost
    cost["prepare_seconds"] = prepare_seconds
    (run_dir / "cost.json").write_text(json.dumps(cost, indent=1))
    print(f"estimated ${cost['total_usd']:.2f} across {len(cost['agents']) + 1} sessions")


def session_cost(session_id: str, prices: dict) -> dict | None:
    """The main session and each of its subagents, priced separately."""
    transcripts = list(PROJECTS.glob(f"*/{session_id}.jsonl"))
    if not transcripts:
        return None
    main = transcripts[0]
    agents: list[dict] = []
    for path in sorted((main.parent / session_id / "subagents").glob("agent-*.jsonl")):
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
        agents.append(
            {"agent": meta.get("agentType") or path.stem} | _transcript_cost(path, prices)
        )
    session: dict = {"agent": "main session"} | _transcript_cost(main, prices)
    return {
        "estimated": True,
        "total_usd": round(session["usd"] + sum(a["usd"] for a in agents), 4),
        "session": session,
        "agents": agents,
    }


def _transcript_cost(path: Path, prices: dict) -> dict:
    # A message is logged once per content block with the same usage, except that
    # output_tokens grows as it streams: the last record of each message id is the final one.
    latest: dict[str, tuple[str, dict]] = {}
    lines = path.read_text().splitlines()
    for line in lines:
        try:
            message = (json.loads(line).get("message")) or {}
        except json.JSONDecodeError:
            continue
        if (
            isinstance(message, dict)
            and message.get("id")
            and isinstance(message.get("usage"), dict)
        ):
            latest[message["id"]] = (message.get("model") or "", message["usage"])

    tokens = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    usd = 0.0
    unpriced: set[str] = set()
    for model, usage in latest.values():
        counts = {
            "input": usage.get("input_tokens") or 0,
            "cache_write": usage.get("cache_creation_input_tokens") or 0,
            "cache_read": usage.get("cache_read_input_tokens") or 0,
            "output": usage.get("output_tokens") or 0,
        }
        for key, n in counts.items():
            tokens[key] += n
        price = next(
            (p for name, p in prices.items() if name in model and isinstance(p, dict)), None
        )
        if price is None:
            if any(counts.values()):
                unpriced.add(model or "unknown")
            continue
        usd += (
            counts["input"] * price["input"]
            + counts["cache_write"] * price["input"] * CACHE_WRITE_FACTOR
            + counts["cache_read"] * price["input"] * CACHE_READ_FACTOR
            + counts["output"] * price["output"]
        ) / 1e6
    stamps = []
    for line in lines:
        try:
            stamp = json.loads(line).get("timestamp")
        except json.JSONDecodeError:
            continue
        if isinstance(stamp, str):
            stamps.append(datetime.fromisoformat(stamp.replace("Z", "+00:00")))
    return {
        "seconds": round((max(stamps) - min(stamps)).total_seconds()) if stamps else None,
        "usd": round(usd, 4),
        "tokens": tokens,
        "messages": len(latest),
        "unpriced_models": sorted(unpriced),
    }


if __name__ == "__main__":
    main()
