"""The hub's JSON API, for clients other than its own pages (the VS Code extension)."""

from dev_hub.api.views import blueprint

__all__ = ["blueprint"]
