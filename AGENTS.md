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
