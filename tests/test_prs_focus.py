"""The user's focus instructions, from the poller to prepare.py and from the agents to the report."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dev_hub.prs import poll
from dev_hub.prs.assemble import assemble


def write_run(run_dir: Path, focus: str, outputs: dict[str, dict]) -> None:
    (run_dir / "out").mkdir(parents=True)
    meta = {
        "pr": 5,
        "repo": "o/r",
        "sha": "abc1234",
        "base_sha": "def5678",
        "worktree": str(run_dir / "wt"),
        "main_repo": str(run_dir / "repo"),
        "personas": ["correctness", "tests"],
        "focus": focus,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta))
    (run_dir / "facts.json").write_text(json.dumps({"files": [], "commits": []}))
    (run_dir / "discussion.json").write_text("[]")
    for key, output in outputs.items():
        (run_dir / "out" / f"{key}.json").write_text(json.dumps(output))


def finding(title: str, **extra: object) -> dict:
    return {"severity": "question", "title": title, "body": "Why?", **extra}


def test_report_collects_answers_and_marks_focus_findings(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        "Is the retry safe?",
        {
            "correctness": {
                "summary": "ok",
                "focus": "The retry can run twice.",
                "findings": [finding("Runs twice?", focus=True), finding("Other")],
            },
            "tests": {"summary": "ok", "findings": []},
            # Not on the personas list: the skill started it for the focus.
            "ux": {"summary": "ok", "focus": "The error is clear.", "findings": []},
            "stray": {"summary": "not an agent"},
        },
    )
    report = assemble(tmp_path)
    assert report["focus"]["text"] == "Is the retry safe?"
    assert [(a["agent"], a["text"]) for a in report["focus"]["answers"]] == [
        ("correctness", "The retry can run twice."),
        ("ux", "The error is clear."),
    ]
    assert {f["items"][0]["title"]: f["focus"] for f in report["findings"]} == {
        "Runs twice?": True,
        "Other": False,
    }
    assert list(report["agents"]) == ["correctness", "tests", "ux"]


def test_report_has_no_focus_when_none_was_given(tmp_path: Path) -> None:
    write_run(tmp_path, "", {"correctness": {"summary": "ok", "focus": "ignored"}})
    assert assemble(tmp_path)["focus"] is None


def test_poller_passes_the_focus_to_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "refusing: test")

    monkeypatch.setattr(poll.subprocess, "run", fake_run)
    monkeypatch.setattr(poll, "log", lambda message: None)
    pr = {"number": 5, "title": "t", "updatedAt": "2026-11-01T00:00:00Z"}
    assert poll.brief(pr, {}, {}, "standard", "Check the retry") == "refused"
    assert calls[0][-4:] == ["--tier", "standard", "--focus", "Check the retry"]
