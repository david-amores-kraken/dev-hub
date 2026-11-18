from __future__ import annotations

from pathlib import Path

from dev_hub.files import write_atomic


def test_write_atomic_replaces_the_file_and_leaves_nothing_behind(tmp_path: Path) -> None:
    path = tmp_path / "new" / "data.json"
    write_atomic(path, "one")
    write_atomic(path, "two")
    assert path.read_text() == "two"
    assert [p.name for p in path.parent.iterdir()] == ["data.json"]
