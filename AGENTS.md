# AGENTS.md

How to work in this repo. For what the hub is and how it fits together, see `README.md`.

## Commits

- Keep commits small. Each one does one thing and leaves the tests passing.
- Write a short subject, then a few lines on **what** changed and **how**, and **why** it was needed.
- Use simple words. Name a class, file or method only when it makes the message easier to read.

## Pull requests

- Every change to this repo goes in a PR for me to review, however small. When I ask for a change, branch off `master`, commit, push and open the PR, then give me the link. Don't stop at edits in the working copy.
- Code outside this repo has no PR. That means the skills and the `pr-brief` package under `~/.claude`, which aren't in git. Edit them in place and tell me what you changed. A request that touches both gets a PR for the repo part only.
- Keep the description short and in simple language: what changed, why, and anything the reviewer should look at first.
- Don't list every file or function. The diff does that.
- Open the PR so it is ready to review, and make sure the checks below pass first.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```
