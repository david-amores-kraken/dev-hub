"""The reviewer personas. The agents are in ~/.claude/agents (review-*.md)."""

from __future__ import annotations

# key: (emoji, display name, finding-ID prefix)
PERSONAS = {
    "conventions": ("📐", "Conventions", "CV"),
    "domain": ("🏛️", "Domain", "DM"),
    "tests": ("🧪", "Tests", "TS"),
    "correctness": ("🧠", "Correctness", "CR"),
    "writing": ("✍️", "Writing", "WR"),
    "cross-client": ("🌍", "Cross-client", "XC"),
    "naming": ("🏷️", "Naming", "NM"),
    "ux": ("👤", "UX", "UX"),
}
# Personas that run only when the branch changes something an end user sees.
USER_FACING_PERSONAS = ("ux",)
