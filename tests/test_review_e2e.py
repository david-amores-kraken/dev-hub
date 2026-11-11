from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dev_hub.review.e2e import FEEDBACK_MARKER, publish

PAGE = (
    "<!doctype html><html><head><title>E2E: feature x</title></head><body>"
    '<h1>Results</h1><img src="{{IMG:01-before}}" alt="before"></body></html>'
)
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def run_dir(repo: Path, e2e: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "run"
    (folder / "shots").mkdir(parents=True)
    (folder / "shots" / "01-before.png").write_bytes(PNG)
    return folder


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_the_page_is_saved_as_the_features_e2e_part_with_the_screenshots_inside(
    tmp_path: Path, e2e: Path, run_dir: Path
) -> None:
    said = publish("feature/x", write(tmp_path, "results.html", PAGE), run_dir=run_dir)
    saved = (e2e / "feature-x.html").read_text()
    assert "{{IMG" not in saved
    assert f'src="data:image/png;base64,{base64.b64encode(PNG).decode()}"' in saved
    assert said.endswith("/features/feature-x?tab=e2e")
    assert not (e2e / "feature-x.feedback.md").exists()


def test_skill_feedback_is_saved_next_to_it(tmp_path: Path, e2e: Path, run_dir: Path) -> None:
    notes = write(tmp_path, "fb.md", f"{FEEDBACK_MARKER}\n\n- [ ] P1: do this\n")
    publish("feature/x", write(tmp_path, "r.html", PAGE), notes, run_dir)
    assert (
        e2e / "feature-x.feedback.md"
    ).read_text() == f"{FEEDBACK_MARKER}\n\n- [ ] P1: do this\n"


def test_a_rerun_replaces_the_page_but_keeps_feedback_it_has_no_new_version_of(
    tmp_path: Path, e2e: Path, run_dir: Path
) -> None:
    notes = write(tmp_path, "fb.md", f"{FEEDBACK_MARKER}\nold")
    publish("feature/x", write(tmp_path, "r.html", PAGE), notes, run_dir)
    publish(
        "feature/x",
        write(tmp_path, "r2.html", PAGE.replace("Results", "Second run")),
        None,
        run_dir,
    )
    assert "Second run" in (e2e / "feature-x.html").read_text()
    assert "old" in (e2e / "feature-x.feedback.md").read_text()


def test_the_api_token_is_never_published(tmp_path: Path, e2e: Path, run_dir: Path) -> None:
    (run_dir / "state.json").write_text(json.dumps({"token": "kraken-secret-token"}))
    leaky = PAGE.replace("Results", "Token kraken-secret-token")
    with pytest.raises(SystemExit, match="API token"):
        publish("feature/x", write(tmp_path, "r.html", leaky), run_dir=run_dir)
    notes = write(tmp_path, "fb.md", f"{FEEDBACK_MARKER}\nkraken-secret-token")
    with pytest.raises(SystemExit, match="API token"):
        publish("feature/x", write(tmp_path, "r.html", PAGE), notes, run_dir)
    assert list(e2e.iterdir()) == []


@pytest.mark.parametrize(
    ("page", "message"),
    [
        ("just text", "whole HTML page"),
        (PAGE.replace("01-before", "02-missing"), "02-missing"),
    ],
)
def test_a_bad_page_is_refused_and_nothing_is_saved(
    tmp_path: Path, e2e: Path, run_dir: Path, page: str, message: str
) -> None:
    with pytest.raises(SystemExit, match=message):
        publish("feature/x", write(tmp_path, "r.html", page), run_dir=run_dir)
    assert list(e2e.iterdir()) == []


def test_feedback_needs_its_marker_and_the_branch_must_exist(
    tmp_path: Path, e2e: Path, run_dir: Path
) -> None:
    page = write(tmp_path, "r.html", PAGE)
    with pytest.raises(SystemExit, match="lacks the"):
        publish("feature/x", page, write(tmp_path, "fb.md", "no marker"), run_dir)
    with pytest.raises(SystemExit, match="isn't a local branch"):
        publish("nope", page, run_dir=run_dir)
    with pytest.raises(SystemExit, match="can't read"):
        publish("feature/x", tmp_path / "missing.html", run_dir=run_dir)


def test_the_published_page_shows_up_in_the_feature(
    tmp_path: Path, e2e: Path, run_dir: Path, client: FlaskClient, base_url: str
) -> None:
    publish("feature/x", write(tmp_path, "r.html", PAGE), run_dir=run_dir)
    page = client.get("/features/feature-x?tab=e2e", base_url=base_url).get_data(as_text=True)
    assert 'src="/features/feature-x/e2e/raw"' in page
    raw = client.get("/features/feature-x/e2e/raw", base_url=base_url)
    assert "data:image/png;base64," in raw.get_data(as_text=True)
