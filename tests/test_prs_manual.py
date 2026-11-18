from __future__ import annotations

import pytest

from dev_hub.prs.manual import parse_pr_link

REPO = "octoenergy/kraken-core"


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("https://github.com/octoenergy/kraken-core/pull/123", 123),
        ("https://github.com/octoenergy/kraken-core/pull/123/files#diff-1", 123),
        (" #123 ", 123),
        ("123", 123),
        ("https://github.com/someone/else/pull/123", None),
        ("https://github.com/octoenergy/kraken-core/issues/123", None),
        ("", None),
    ],
)
def test_parse_pr_link(text: str, number: int | None) -> None:
    assert parse_pr_link(text, REPO) == number
