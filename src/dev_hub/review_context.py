"""Helpers shared by the two review flows, local-review (dev_hub.review) and pr-brief (dev_hub.prs).

They know Kraken's layout: which files an end user sees, where the guidance files are, where
Asana links are. dev_hub.review.prepare takes them as an argument, so tests can pass a stand-in.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path, PurePosixPath

CONTEXT_FILE_NAMES = ("AGENTS.md", "CLAUDE.md", "context.md")
# What makes a changed file something an end user sees, for starting the UX persona. Errs on the
# side of starting it: a run with nothing to find costs one LGTM.
USER_FACING_PATHS = {
    "template": r"/templates/|\.(html|mjml|txt)$",
    "translations": r"\.ftl$",
    "GraphQL": r"/graphql/",
    "REST": r"(^|/)serializers?\.py$",
    "form": r"(^|/)forms(\.py$|/)",
    "admin": r"(^|/)admin\.py$|/djangoadmin/",
    "site": r"/interfaces/(supportsite|consumersite|authserver|documentationsite)/",
    "frontend": r"/static-src[^/]*/|\.(tsx?|jsx?|vue|s?css)$",
    "customer comms": r"/comms/|^src/kraken/messaging/",
}
USER_FACING_LINES = {
    "error message": r"\b(ValidationError|GraphQLError|PermissionDenied)\(",
    "flash message": r"\bmessages\.(success|error|warning|info|add_message)\(",
    "label or help text": r"\b(help_text|verbose_name|label|placeholder|error_messages)\s*=",
    "translated string": r"\bgettext(_lazy)?\(|\b_\(\s*[\"']",
}
NOT_USER_FACING = r"(^|/)(tests?|migrations)/|(^|/)(test_[^/]*|[^/]*_tests?\.py|conftest\.py)$"
# Matches both .../project/<id>/task/<id> and the older .../0/<project>/<task> links.
ASANA_TASK_RE = re.compile(r"https://app\.asana\.com/(?:[^\s)\]>\"']*/task/(\d+)|0/\d+/(\d+))")


class Refused(SystemExit):
    def __init__(self, message: str) -> None:
        print(f"refusing: {message}", flush=True)
        super().__init__(3)


def run(cmd: list[str], *, input: str | None = None, check: bool = True) -> str:
    result = subprocess.run(cmd, input=input, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd[:4])} ...` failed: {result.stderr.strip()}")
    return result.stdout


def gh_json(args: list[str]) -> object:
    return json.loads(run(["gh", *args]))


def gh_paginate(endpoint: str) -> list[dict]:
    pages = gh_json(["api", "--paginate", "--slurp", endpoint])
    assert isinstance(pages, list)
    return [item for page in pages for item in page]


def asana_tasks(texts: list[str]) -> list[dict[str, str]]:
    """Asana tasks linked from the PR description and commits, in order of first mention."""
    tasks: dict[str, str] = {}
    for text in texts:
        for m in ASANA_TASK_RE.finditer(text):
            tasks.setdefault(m[1] or m[2], m[0])
    return [{"id": task_id, "url": url} for task_id, url in tasks.items()]


def commentable_lines(diff: str) -> dict[str, dict[str, list[int]]]:
    """For each file, the lines GitHub accepts review comments on, per side of the diff."""
    lines: dict[str, dict[str, set[int]]] = {}
    path = None
    old = new = 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path = None
        elif raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
            if path:
                lines.setdefault(path, {"RIGHT": set(), "LEFT": set()})
        elif raw.startswith("--- ") and path is None:
            continue
        elif m := re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw):
            old, new = int(m[1]), int(m[2])
        elif path and raw[:1] == "+":
            lines[path]["RIGHT"].add(new)
            new += 1
        elif path and raw[:1] == "-":
            lines[path]["LEFT"].add(old)
            old += 1
        elif path and raw[:1] == " ":
            lines[path]["RIGHT"].add(new)
            lines[path]["LEFT"].add(old)
            old += 1
            new += 1
    return {p: {side: sorted(n) for side, n in sides.items()} for p, sides in lines.items()}


def user_facing(diff: str) -> list[dict[str, str]]:
    """Changed files an end user sees, and why: by path, or by what their changed lines touch."""
    found: dict[str, str] = {}
    path = old = None
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path = old = None
        elif raw.startswith("--- ") and path is None:
            source = raw[4:].rstrip("\t")
            old = None if source == "/dev/null" else source.removeprefix("a/")
        elif raw.startswith("+++ "):
            target = raw[4:].rstrip("\t")
            # A deleted file still counts: removing a screen or a message is a change users see.
            path = old if target == "/dev/null" else target.removeprefix("b/")
            if path and re.search(NOT_USER_FACING, path):
                path = None
            if path:
                for why, pattern in USER_FACING_PATHS.items():
                    if re.search(pattern, path):
                        found.setdefault(path, why)
                        break
        elif path and path not in found and raw[:1] in ("+", "-"):
            for why, pattern in USER_FACING_LINES.items():
                if re.search(pattern, raw[1:]):
                    found[path] = why
                    break
    return [{"path": p, "why": why} for p, why in found.items()]


def context_files(root: Path, changed: list[str]) -> list[str]:
    """AGENTS.md, CLAUDE.md and context.md files along each changed file's directory path."""
    found: set[str] = set()
    for path in changed:
        for parent in PurePosixPath(path).parents:
            for name in CONTEXT_FILE_NAMES:
                candidate = parent / name
                if (root / candidate).is_file():
                    found.add(str(candidate))
    return sorted(found, key=lambda p: (p.count("/"), p))


def matching_rules(root: Path, changed: list[str]) -> list[str]:
    """`.claude/rules/*.md` files whose `paths:` globs match a changed file."""
    matched = []
    for rule in sorted((root / ".claude" / "rules").glob("*.md")):
        text = rule.read_text()
        header = text.split("---", 2)[1] if text.startswith("---") else ""
        globs = re.findall(r"^\s*-\s*[\"']?([^\"'\n#]+?)[\"']?\s*$", header, re.MULTILINE)
        if any(PurePosixPath(p).full_match(g) for g in globs for p in changed):
            matched.append(str(rule.relative_to(root)))
    return matched


def repo_skills(root: Path) -> list[dict[str, str]]:
    """Name, path and description of each repo skill, for the Domain persona to pick from."""
    skills = []
    for skill in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
        if skill.parent.name == "local":
            continue
        text = skill.read_text()
        header = text.split("---", 2)[1] if text.startswith("---") else ""
        m = re.search(
            r"^description:\s*(?:>-?\s*\n)?(.+?)(?=^\w[\w-]*:|\Z)",
            header,
            re.MULTILINE | re.DOTALL,
        )
        description = " ".join(m[1].split()) if m else ""
        skills.append(
            {
                "name": skill.parent.name,
                "path": str(skill.relative_to(root)),
                "description": description[:300],
            }
        )
    return skills
