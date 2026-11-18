"""Merge the personas' findings into report.json and size up each commit.

Usage: python -m dev_hub.prs.assemble <run folder>

Writes report.json. The web app renders it on request. Agent output is untrusted: anything
that doesn't match reference/brief.md is dropped and listed under "problems" in the report,
rather than failing the whole run.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from os.path import commonpath
from pathlib import Path

from dev_hub.config import hub_url
from dev_hub.prs.text import REF_RE
from dev_hub.review_context import run

# Used when meta.json predates the "personas" list prepare.py writes.
AGENTS = ("domain", "correctness", "cross-client", "tests", "conventions", "naming")
SEVERITIES = ("blocker", "should-fix", "question", "nit")
MATCHES = ("yes", "partly", "no", "no-ticket", "unavailable")
# A commit with at least this many changed lines outside tests is worth reading in full.
FOCUS_CODE_LINES = 40
FOCUS_SIGNALS = ("migration", "data migration", "raw SQL", "transaction", "permissions")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m dev_hub.prs.assemble <run folder>")
    run_dir = Path(sys.argv[1]).expanduser().resolve()
    if not (run_dir / "meta.json").is_file():
        raise SystemExit(f"not a pr-brief run folder: {run_dir}")

    report = assemble(run_dir)
    (run_dir / "report.json").write_text(json.dumps(report, indent=1))
    severities = Counter(f["severity"] for f in report["findings"])
    tiers = Counter(c["tier"] for c in report["commits"])
    print(
        "findings: "
        + (", ".join(f"{severities[s]} {s}" for s in SEVERITIES if severities[s]) or "none")
        + " · commits: "
        + ", ".join(f"{tiers[t]} {t}" for t in ("focus", "skim", "skip") if tiers[t])
        + f" · problems: {len(report['problems'])}"
    )
    print(report_url(report["meta"]["pr"], run_dir.name))


def report_url(pr: int, run: str) -> str:
    return f"{hub_url()}/prs/{pr}/{run}"


def assemble(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    facts = json.loads((run_dir / "facts.json").read_text())
    discussion = json.loads((run_dir / "discussion.json").read_text())
    agents_run = tuple(meta.get("personas", AGENTS))
    problems: list[str] = []
    outputs: dict[str, dict | None] = {}
    for key in agents_run:
        outputs[key], problem = _load(run_dir, key)
        if problem:
            problems.append(problem)

    places = _Places(meta, facts["files"], problems)
    blame = _Blame(meta, facts["commits"])
    reviewers = {d["author"] for d in discussion if not d["mine"]}
    earlier_path = run_dir / "earlier-findings.json"
    earlier = json.loads(earlier_path.read_text()) if earlier_path.is_file() else None
    raw = [
        finding
        for key in agents_run
        for finding in _findings(key, outputs[key], places, reviewers, problems)
    ]
    for finding in raw:
        finding["commits"] = blame(finding["locations"])
        finding["links"] = places.links(
            finding["body"], [loc["path"] for loc in finding["locations"]]
        )
    resolved = _follow_up(raw, earlier, outputs, problems)
    findings = _merge(raw)
    # The Domain persona writes the goal and the commit lines; in the light tier General does.
    narrator = outputs.get("domain") or outputs.get("general")
    commits = _commits(facts["commits"], findings, narrator, places)
    goal = _goal(narrator)
    if goal:
        goal["links"] = places.links(goal["text"], [])

    agents = {}
    notes = {}
    for key in agents_run:
        output = outputs[key]
        agents[key] = {
            "ran": output is not None,
            "summary": _text((output or {}).get("summary")),
            "findings": sum(1 for f in raw if f["agent"] == key),
        }
        if output and (agent_notes := [str(n) for n in _list(output, "notes") if n]):
            notes[key] = agent_notes

    cost_path = run_dir / "cost.json"
    return {
        "meta": meta,
        "assembled": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "cost": json.loads(cost_path.read_text()) if cost_path.is_file() else None,
        "goal": goal,
        "findings": findings,
        "resolved": resolved,
        "commits": commits,
        "threads": meta.get("threads", {"available": False}),
        "agents": agents,
        "notes": notes,
        "problems": [
            f"{problem} (×{count})" if count > 1 else problem
            for problem, count in Counter(problems).items()
        ],
    }


def _load(run_dir: Path, key: str) -> tuple[dict | None, str | None]:
    path = run_dir / "out" / f"{key}.json"
    if not path.is_file():
        return None, f"The {key} agent wrote no output."
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        return None, f"The {key} agent's output isn't valid JSON ({error})."
    if not isinstance(data, dict):
        return None, f"The {key} agent's output isn't a JSON object."
    return data, None


def _list(data: dict | None, key: str) -> list:
    value = (data or {}).get(key)
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _pick(value: object, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


class _Places:
    """Checks the agents' locations and links each one to GitHub."""

    def __init__(self, meta: dict, files: list[dict], problems: list[str]) -> None:
        self.meta = meta
        self.worktree = Path(meta["worktree"])
        self.anchors = {f["path"]: f["github_anchor"] for f in files}
        self.anchors |= {f["old_path"]: f["github_anchor"] for f in files if f["old_path"]}
        self.problems = problems
        self.files: list[str] | None = None

    def __call__(self, raw: object, owner: str) -> list[dict]:
        if not isinstance(raw, list):
            return []
        return [place for item in raw if (place := self._one(item, owner))]

    def _one(self, item: object, owner: str) -> dict | None:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            self.problems.append(f"{owner}: dropped a location that isn't an object with a path.")
            return None
        path = item["path"].strip().removeprefix(str(self.worktree)).lstrip("/")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, int) or start < 1:
            start = None
        if not isinstance(end, int) or start is None or end < start:
            end = None
        side = "base" if item.get("side") == "base" else "head"
        if side == "head" and not (self.worktree / path).exists():
            self.problems.append(f"{owner}: `{path}` doesn't exist at the PR head.")
            return None
        return {
            "path": path,
            "start": start,
            "end": end,
            "side": side,
            "href": self._href(path, start, end, side),
        }

    def links(self, text: str, near: list[str]) -> dict[str, str]:
        """GitHub links for the line references in `text`, keyed by the reference as written.

        A partial path (`api.py:48`) is linked only when it picks out one file. See _resolve.
        """
        links = {}
        for m in REF_RE.finditer(text):
            path = self._resolve(m[1], near)
            if not path:
                continue
            start, end = int(m[2]), int(m[3]) if m[3] else None
            # "base api.py:55" means the merge base, as does a file the PR deleted.
            said_base = text[: m.start()].rstrip().lower().endswith("base")
            side = "head" if (self.worktree / path).is_file() and not said_base else "base"
            links[m[0]] = self._href(path, start, end if end and end > start else None, side)
        return links

    def _resolve(self, ref: str, near: list[str]) -> str | None:
        """The file a partial path means: one of the finding's own files, then a file the PR
        changed, then any file in the repo. Among several, the one in the same folder as the
        finding's files wins; a tie means it's ambiguous, and stays text."""
        ref = ref.removeprefix(str(self.worktree)).lstrip("/")
        if (self.worktree / ref).is_file() or ref in self.anchors:
            return ref
        for paths in (near, list(self.anchors), self._repo_files()):
            matches = [p for p in set(paths) if p.endswith("/" + ref)]
            if len(matches) == 1:
                return matches[0]
            if matches:
                return self._closest(matches, near)
        return None

    def _closest(self, matches: list[str], near: list[str]) -> str | None:
        def shared(path: str) -> int:
            # How many leading folders the path shares with the nearest of the finding's files.
            return max((len(commonpath([path, n]).split("/")) for n in near), default=0)

        ranked = sorted(matches, key=shared, reverse=True)
        return ranked[0] if shared(ranked[0]) > shared(ranked[1]) else None

    def _repo_files(self) -> list[str]:
        if self.files is None:
            out = run(["git", "-C", str(self.worktree), "ls-files"], check=False)
            self.files = out.splitlines()
        return self.files

    def _href(self, path: str, start: int | None, end: int | None, side: str) -> str:
        repo, pr = self.meta["repo"], self.meta["pr"]
        if path in self.anchors:
            line = f"{'L' if side == 'base' else 'R'}{start}" if start else ""
            return f"https://github.com/{repo}/pull/{pr}/files#{self.anchors[path]}{line}"
        sha = self.meta["base_sha"] if side == "base" else self.meta["sha"]
        lines = f"#L{start}" + (f"-L{end}" if end else "") if start else ""
        return f"https://github.com/{repo}/blob/{sha}/{path}{lines}"


class _Blame:
    """Which of the PR's commits last changed the lines a finding points at."""

    def __init__(self, meta: dict, commits: list[dict]) -> None:
        self.git = ["git", "-C", meta["main_repo"]]
        self.range = f"{meta['base_sha']}..{meta['sha']}"
        self.shorts = {c["sha"]: c["short"] for c in commits}
        self.cache: dict[tuple, list[str]] = {}

    def __call__(self, locations: list[dict]) -> list[str]:
        # Lines the PR changed say exactly where a finding is. Only when none of its
        # locations hit one does every commit that touched the files count.
        found = self._each(locations, self._blame) or self._each(locations, self._log)
        order = list(self.shorts.values())
        return sorted(found, key=order.index)

    def _each(self, locations: list[dict], how) -> list[str]:
        found: list[str] = []
        for loc in locations:
            key = (how.__name__, loc["path"], loc["start"], loc["end"], loc["side"])
            if key not in self.cache:
                self.cache[key] = how(loc)
            found += [short for short in self.cache[key] if short not in found]
        return found

    def _blame(self, loc: dict) -> list[str]:
        if loc["side"] != "head" or not loc["start"]:
            return []
        lines = f"{loc['start']},{loc['end'] or loc['start']}"
        out = run(
            [
                *self.git,
                "blame",
                "-s",
                "-l",
                "-L",
                lines,
                self.range,
                "--",
                loc["path"],
            ],
            check=False,
        )
        # Lines from before the PR start with "^" and match no PR commit.
        shas = {line.split()[0] for line in out.splitlines() if line.strip()}
        return [self.shorts[s] for s in shas if s in self.shorts]

    def _log(self, loc: dict) -> list[str]:
        # Deleted lines, a whole file, or lines the PR didn't change.
        out = run(
            [*self.git, "log", "--format=%H", self.range, "--", loc["path"]],
            check=False,
        )
        return [self.shorts[s] for s in out.split() if s in self.shorts]


def _findings(
    key: str,
    output: dict | None,
    places: _Places,
    reviewers: set[str],
    problems: list[str],
) -> list[dict]:
    findings = []
    for item in _list(output, "findings"):
        if not isinstance(item, dict):
            problems.append(f"{key}: dropped a finding that isn't an object.")
            continue
        body = _text(item.get("body"))
        title = _text(item.get("title")) or body.split(". ")[0][:120]
        if not title:
            problems.append(f"{key}: dropped a finding with no title or body.")
            continue
        severity = item.get("severity")
        if severity not in SEVERITIES:
            problems.append(
                f"{key}: finding '{title[:40]}' had severity {severity!r}; shown as a question."
            )
            severity = "question"
        raised_by = _text(item.get("already_raised_by")).lstrip("@")
        if raised_by and raised_by not in reviewers:
            problems.append(
                f"{key}: said @{raised_by} raised '{title[:40]}', but they haven't commented."
            )
            raised_by = ""
        findings.append(
            {
                "agent": key,
                "severity": severity,
                "title": title,
                "body": body,
                "where": _text(item.get("where")),
                "locations": places(item.get("locations"), key),
                "already_raised_by": raised_by,
                "earlier_id": _text(item.get("earlier_id")),
            }
        )
    return findings


def _follow_up(
    raw: list[dict], earlier: list[dict] | None, outputs: dict, problems: list[str]
) -> dict | None:
    """Give every finding an ID, mark it new or still open, and list the earlier ones now gone.

    An ID carries over from brief to brief while a persona keeps raising the finding. None
    when there's no earlier brief to compare with.
    """
    known = {e["id"]: e for e in earlier or []}
    numbers = Counter()
    for e in known.values():
        agent, _, n = e["id"].rpartition("-")
        numbers[agent] = max(numbers[agent], int(n) if n.isdigit() else 0)
    carried = set()
    for f in raw:
        previous = known.get(f["earlier_id"])
        if f["earlier_id"] and (
            not previous or previous["agent"] != f["agent"] or f["earlier_id"] in carried
        ):
            problems.append(
                f"{f['agent']}: '{f['title'][:40]}' follows up {f['earlier_id']!r}, which isn't one of its earlier findings."
            )
            previous = None
        if previous:
            f["id"], f["status"] = previous["id"], "still open"
            carried.add(previous["id"])
        else:
            numbers[f["agent"]] += 1
            f["id"] = f"{f['agent']}-{numbers[f['agent']]}"
            f["status"] = "new" if earlier is not None else ""
    if earlier is None:
        return None

    reasons = {}
    for output in outputs.values():
        for item in _list(output, "resolved"):
            if isinstance(item, dict) and _text(item.get("id")) in known:
                reasons[_text(item["id"])] = _text(item.get("why"))
    gone = []
    for e in earlier:
        # A persona that didn't run this time can't say whether its findings were fixed.
        if e["id"] in carried or outputs.get(e["agent"]) is None:
            continue
        gone.append({**e, "why": reasons.get(e["id"], "")})
    return {"count": len(earlier), "gone": gone}


def _merge(raw: list[dict]) -> list[dict]:
    """One card per problem: findings from different agents on overlapping lines share one."""
    groups: list[list[dict]] = []
    for finding in raw:
        for group in groups:
            if any(_overlap(finding, other) for other in group):
                group.append(finding)
                break
        else:
            groups.append([finding])

    order = {s: i for i, s in enumerate(SEVERITIES)}
    merged: list[dict] = []
    for group in groups:
        group.sort(key=lambda f: order[f["severity"]])
        locations, commits = [], []
        for f in group:
            locations += [loc for loc in f["locations"] if loc not in locations]
            commits += [c for c in f["commits"] if c not in commits]
        merged.append(
            {
                "severity": group[0]["severity"],
                "agents": list(dict.fromkeys(f["agent"] for f in group)),
                "items": [
                    {
                        k: f[k]
                        for k in (
                            "id",
                            "status",
                            "agent",
                            "severity",
                            "title",
                            "body",
                            "where",
                            "links",
                        )
                    }
                    | {
                        "locations": [
                            {k: loc[k] for k in ("path", "start", "end", "side")}
                            for loc in f["locations"]
                        ]
                    }
                    for f in group
                ],
                "status": "new" if any(f["status"] == "new" for f in group) else group[0]["status"],
                "locations": locations,
                "commits": commits,
                "already_raised_by": sorted({f["already_raised_by"] for f in group} - {""}),
            }
        )
    merged.sort(key=lambda f: (order[f["severity"]], -len(f["agents"])))
    return merged


def _overlap(a: dict, b: dict) -> bool:
    """Same problem: different agents whose first locations overlap.

    Only the first location counts. The rest are often context (a caller, a convention
    file), and matching on them merges unrelated findings.
    """
    if a["agent"] == b["agent"] or not a["locations"] or not b["locations"]:
        return False
    x, y = a["locations"][0], b["locations"][0]
    if x["path"] != y["path"] or x["side"] != y["side"] or not x["start"] or not y["start"]:
        return False
    return x["start"] <= (y["end"] or y["start"]) and y["start"] <= (x["end"] or x["start"])


def _commits(
    facts: list[dict], findings: list[dict], domain: dict | None, places: _Places
) -> list[dict]:
    """Focus, skim or skip per commit, worked out from git's facts and the findings."""
    described = (domain or {}).get("commits")
    described = described if isinstance(described, dict) else {}
    commits = []
    for fact in facts:
        summary = fact.get("summary") or {}
        own = [f for f in findings if fact["short"] in f["commits"]]
        serious = Counter(f["severity"] for f in own if f["severity"] in ("blocker", "should-fix"))
        code_lines = summary.get("code_lines", summary.get("substantive_lines"))
        risky = [s for s in summary.get("signals", []) if s in FOCUS_SIGNALS]

        if summary.get("mechanical"):
            tier, reason = "skip", f"git: {summary['mechanical']}"
        elif serious:
            tier = "focus"
            reason = ", ".join(f"{n} {severity}" for severity, n in serious.most_common())
        elif fact.get("merge"):
            tier, reason = (
                "focus",
                f"resolves merge conflicts in {summary.get('files', '?')} file(s)",
            )
        elif risky:
            tier, reason = "focus", f"touches: {', '.join(risky)}"
        elif code_lines is None:
            tier, reason = "skim", "not sized: too many commits"
        elif code_lines >= FOCUS_CODE_LINES:
            tier, reason = "focus", f"{code_lines} changed lines outside tests"
        elif code_lines == 0:
            tier, reason = "skim", "tests only"
        else:
            tier, reason = (
                "skim",
                f"{code_lines} changed lines outside tests, nothing serious found",
            )
        if summary.get("moved_lines") and tier != "skip":
            reason += f"; {summary['moved_lines']} more lines only moved"
        what = next(
            (
                _text(text)
                for sha, text in described.items()
                if len(sha) >= 7 and fact["sha"].startswith(sha)
            ),
            "",
        )
        commits.append(
            {
                "sha": fact["sha"],
                "short": fact["short"],
                "headline": fact["headline"],
                "merge": bool(fact.get("merge")),
                "additions": summary.get("additions"),
                "deletions": summary.get("deletions"),
                "tier": tier,
                "reason": reason,
                "what": what,
                "links": places.links(what, summary.get("paths", [])),
                "new": fact.get("new"),
                "findings": len(own),
            }
        )
    return commits


def _goal(domain: dict | None) -> dict | None:
    if domain is None or not _text(domain.get("goal")):
        return None
    ticket: dict = domain["ticket"] if isinstance(domain.get("ticket"), dict) else {}
    tasks = [
        {
            "id": _text(t.get("id")),
            "name": _text(t.get("name")),
            "url": _text(t.get("url")),
        }
        for t in _list(ticket, "tasks")
        if isinstance(t, dict)
    ]
    return {
        "text": _text(domain.get("goal")),
        "ticket": {
            "tasks": [t for t in tasks if t["url"].startswith("https://app.asana.com/")],
            "match": _pick(ticket.get("match"), MATCHES, "unavailable"),
            "summary": _text(ticket.get("summary")),
        },
    }


if __name__ == "__main__":
    main()
