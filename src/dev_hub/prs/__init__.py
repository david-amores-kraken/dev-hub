"""The PRs section: queue the PRs awaiting my review, brief them, and serve the briefs.

The `pr-brief` skill (`skills/pr-brief`) runs the command-line parts: `prepare`, `assemble`, and
the `poll` launchd job. The hub serves the blueprint at /prs.
"""

import sys
from pathlib import Path

# review_context.py is shared with local-review, so it lives in ~/.claude/lib, not in this package.
_SHARED = str(Path.home() / ".claude" / "lib")
if _SHARED not in sys.path:
    sys.path.append(_SHARED)

from dev_hub.prs.views import blueprint  # noqa: E402

__all__ = ["blueprint"]
