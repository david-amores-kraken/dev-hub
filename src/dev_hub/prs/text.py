"""Patterns for the text personas write: `code` spans and `path:line` references."""

from __future__ import annotations

import re

CODE_RE = re.compile(r"`([^`]+)`")
# A line reference in prose: `src/kraken/ledgers/api.py:48`, `api.py:40-57`. assemble.py
# resolves each one to a GitHub link, and only those are linked.
REF_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z]\w*):(\d+)(?:-(\d+))?(?!\w)")
