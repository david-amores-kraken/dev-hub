> [!NOTE]
> **Note on AI Assistance:** This document was drafted with the assistance of an LLM. While I am fully and solely responsible for all contents, reasoning, claims, and judgments, some AI "slop" or awkward phrasing may have slipped through. If you spot any, please gently point it out so I can refine my workflow!
>
> Please note: If this is marked as a draft, or sits in a section that says it isn't ready for review, please don't treat it as ready for review. It may be largely or fully AI-generated, and I don't intend to share fully AI-generated work for review.

# AGENTS.md

How to work in this repo. For what the hub is and how it fits together, see `README.md`.

## Commits

- Keep commits small. Each one does one thing and leaves the tests passing.
- Write a short subject, then a few lines on **what** changed and **how**, and **why** it was needed.
- Use simple words. Name a class, file or method only when it makes the message easier to read.

## Pull requests

- Keep the description short and in simple language: what changed, why, and anything the reviewer should look at first.
- Don't list every file or function. The diff does that.
- Open the PR so it is ready to review, and make sure the checks below pass first.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```
