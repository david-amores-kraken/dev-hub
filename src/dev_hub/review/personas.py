"""The reviewer personas. Keep this in step with PERSONAS in the self-review skill's common.py."""

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
