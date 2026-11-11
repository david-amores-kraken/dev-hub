"""Review a branch with the reviewer personas, and keep their findings in the dev hub.

The personas (agents in ~/.claude/agents) only read a run folder and write a findings file, so
they work the same here as on a GitHub PR. What differs is what prepares the run folder (`prepare`)
and what takes the findings (`post`). `todo` and `address` are for the agent that acts on comments.
"""
