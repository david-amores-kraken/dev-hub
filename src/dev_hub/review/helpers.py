"""The helpers the self-review skill and pr-brief share (~/.claude/lib/review_context.py).

They know Kraken's layout: which files an end user sees, where the guidance files are, where
Asana links are. They are loaded when needed and not copied here, so there is one copy to keep up
to date. `prepare` takes them as an argument, so tests can pass a stand-in.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

LIB = Path.home() / ".claude" / "lib"


def load_helpers() -> ModuleType:
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    return importlib.import_module("review_context")
