from __future__ import annotations

from dev_hub.review.prepare import BRIEF, POST_PLACEHOLDER


def test_the_real_brief_has_the_post_command_and_no_github_commands() -> None:
    text = BRIEF.read_text()
    assert text.count(POST_PLACEHOLDER) == 1
    assert "post.py" not in text
    assert "gh pr" not in text
