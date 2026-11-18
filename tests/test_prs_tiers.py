from dev_hub.prs.config import load
from dev_hub.prs.tiers import choose_tier, suggest_tier


def files(*sizes: int, path: str = "src/a.py") -> list[dict]:
    return [{"path": path, "additions": n, "deletions": 0} for n in sizes]


def test_small_pr_suggests_light() -> None:
    assert suggest_tier(files(10), 1, load())[0] == "light"


def test_middle_pr_suggests_standard() -> None:
    assert suggest_tier(files(200), 5, load())[0] == "standard"


def test_many_files_suggests_large() -> None:
    assert suggest_tier(files(10), 30, load())[0] == "large"


def test_migration_rules_out_light() -> None:
    tier, reason = suggest_tier(files(5, path="src/app/migrations/0001_x.py"), 1, load())
    assert tier == "standard"
    assert "migration" in reason


def test_lockfile_only_suggests_note() -> None:
    assert suggest_tier(files(900, path="uv.lock"), 1, load())[0] == "note"


def test_unknown_size_suggests_standard() -> None:
    assert suggest_tier([], 0, load(), known=False) == ("standard", "size unknown")


def test_chosen_tier_overrides_size() -> None:
    assert choose_tier([], load(), "large") == ("large", "set by hand")
