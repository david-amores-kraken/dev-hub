"""Where the hub listens and where it reads things from."""

from __future__ import annotations

import os
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("DEV_HUB_PORT", "8765"))


def plans_dir() -> Path:
    """Where the feature skill saves plans (and their index.html)."""
    return Path(os.environ.get("DEV_HUB_PLANS") or Path.home() / "Plans")
