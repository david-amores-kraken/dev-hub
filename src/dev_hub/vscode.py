"""Links that open a branch in the VS Code extension (`vscode/`), which reads it from /api."""

from __future__ import annotations

from urllib.parse import urlencode

# The extension's id: "publisher.name" in vscode/package.json.
EXTENSION = "local.dev-hub-review"


def open_link(branch: str) -> str:
    """A vscode:// link that shows the branch in the extension and opens its first file."""
    return f"vscode://{EXTENSION}/open?{urlencode({'branch': branch})}"
