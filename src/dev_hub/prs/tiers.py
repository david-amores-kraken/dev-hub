"""Review tiers: which one a PR gets by default, and which one to suggest from its size alone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

TIERS = ("note", "light", "standard", "large")


def choose_tier(
    files: list[dict[str, Any]], config: dict, forced: str | None = None
) -> tuple[str, str]:
    """The tier for a PR and why, from what git worked out about its diff.

    note: every change is mechanical, so no agent has anything to say.
    light: small, and none of the changes touch anything risky.
    large: big enough that the user needs the brief more than a read-through.
    Everything else is standard. Risky signals always rule out light, whatever the size.
    """
    if forced:
        return forced, "set by hand"
    substantive = sum(f["substantive_lines"] for f in files)
    size = f"{substantive} substantive lines in {len(files)} files"
    if files and all(f["mechanical"] for f in files):
        return "note", "every change is mechanical"
    large = config["tiers"]["large"]
    if substantive >= large["min_substantive_lines"] or len(files) >= large["min_files"]:
        return "large", size
    risky = sorted(
        {
            signal["label"]
            for f in files
            for signal in f["signals"]
            if signal["label"] in config["risk_signals"]
        }
    )
    light = config["tiers"]["light"]
    if risky:
        return "standard", f"{size}; touches {', '.join(risky)}"
    if substantive <= light["max_substantive_lines"] and len(files) <= light["max_files"]:
        return "light", size
    return "standard", size


LOCKFILES = {
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
}


def suggest_tier(
    files: list[dict[str, Any]], changed_files: int, config: dict, *, known: bool = True
) -> tuple[str, str]:
    """A tier to suggest for a PR from its size alone, before anything is fetched.

    `files` holds path, additions and deletions per file (GitHub lists at most 100).
    This counts every changed line, where `choose_tier` counts only substantive ones, so it
    can lean larger than the tier `prepare.py` would pick. It can't see mechanical changes,
    except a PR that only touches lockfiles, and it guesses risk from file paths.
    """
    if not known:
        return "standard", "size unknown"
    lines = sum(f["additions"] + f["deletions"] for f in files)
    size = f"{lines} changed lines in {changed_files} files"
    if files and all(Path(f["path"]).name in LOCKFILES for f in files):
        return "note", "only lockfiles changed"
    large = config["tiers"]["large"]
    if lines >= large["min_substantive_lines"] or changed_files >= large["min_files"]:
        return "large", size
    risky = sorted(
        {
            label
            for f in files
            for label, hit in (
                ("migration", "/migrations/" in f["path"]),
                ("settings file", "settings" in Path(f["path"]).name),
            )
            if hit
        }
    )
    if risky:
        return "standard", f"{size}; touches {', '.join(risky)}"
    light = config["tiers"]["light"]
    if lines <= light["max_substantive_lines"] and changed_files <= light["max_files"]:
        return "light", size
    return "standard", size
