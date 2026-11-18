"""The PRs section: queue the PRs awaiting my review, brief them, and serve the briefs.

The `pr-brief` skill (`skills/pr-brief`) runs the command-line parts: `prepare`, `assemble`, and
the `poll` launchd job. The hub serves the blueprint in `views` at /prs.

This file imports nothing, so `python -m dev_hub.prs.poll` doesn't load the poller twice.
"""
