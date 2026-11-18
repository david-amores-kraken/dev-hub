"""The PRs section: queue the PRs awaiting my review, brief them, and serve the briefs.

The `pr-brief` skill (`skills/pr-brief`) runs the command-line parts: `prepare`, `assemble`, and
the `poll` launchd job. The hub serves the blueprint at /prs.
"""

from dev_hub.prs.views import blueprint

__all__ = ["blueprint"]
