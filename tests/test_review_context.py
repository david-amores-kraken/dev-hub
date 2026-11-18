from __future__ import annotations

import pytest

from dev_hub.review_context import is_test


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("src/kraken/ledgers/tests/factories.py", True),
        ("src/app/__snapshots__/page.snap", True),
        ("src/app/api_test.py", True),
        ("frontend/Button.spec.tsx", True),
        ("src/kraken/ledgers/api.py", False),
        ("src/kraken/testing_tools.py", False),
    ],
)
def test_is_test(path: str, expected: bool) -> None:
    assert is_test(path) is expected
