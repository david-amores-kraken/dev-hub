---
name: local-review
description: Review one of the user's local branches with up to eight persona subagents (Conventions, Domain, Tests, Correctness, Writing, Cross-client, Naming, and UX when the branch changes something a user sees). Findings land as comments in the dev hub's Diffs section, not on GitHub, and no PR is needed.
when_to_use: Use when the user asks for a local review or a persona review of a branch before it has a PR, or to act on the comments they left in the dev hub ("local review", "review this branch in the hub", "address my comments in the hub"). Each run starts seven or eight agents.
argument-hint: "[branch] [final]"
arguments:
  - branch
  - final
---

# local-review

The local twin of `self-review`. The same personas review a branch, and their findings and
summaries are saved in the dev hub (`http://127.0.0.1:8765/diffs/<branch>`) instead of on a PR.
The personas are the same agents with the same brief. Only the folder they read and the command
that takes their findings differ, and both are in `python -m dev_hub.review`.

Don't review the branch yourself, and don't wait for the agents.

## Setup (once)

Not done by the repo itself, because it changes `~/.claude`:

1. Link the skill: `ln -s ~/Code/dev-hub/skills/local-review ~/.claude/skills/local-review`.
2. Allow the personas to post. Add to `permissions.allow` in `~/.claude/settings.json`:
   `Bash(/Users/davidamores/Code/dev-hub/.venv/bin/python -m dev_hub.review post:*)`.
   The run folder rules for self-review already cover where the run folders go.
3. `uv sync` in `~/Code/dev-hub`, so that python exists.

In the commands below, `PY` is `/Users/davidamores/Code/dev-hub/.venv/bin/python`.

## Rules

- **Local branches of the hub's repo only** (`DEV_HUB_REPO`, default kraken-core), and only ones
  with commits the base doesn't have.
- **Personas post; you don't.** Each runs `PY -m dev_hub.review post` as the last line of its brief.
- **Run from the branch's worktree**, like `self-review`: the personas read code from where they start.
- **Nothing goes to GitHub.** This skill never pushes or opens a PR.

## Steps

### 1. Find the branch

If `$branch` is empty, use the current branch (`git branch --show-current`).

### 2. Prepare the run

```bash
PY -m dev_hub.review prepare <branch> [--final]
```

Pass `--final` when `$final` is `final`, so the Writing persona also checks commit messages.
The last line printed is the run folder, and the one before it lists the personas to start. If it
prints `refusing:`, stop and say why.

### 3. Start the personas

Do exactly step 3 of the `self-review` skill: in one message, start the agents on the
`personas:` line in the background, one Agent call each, with the same table of `subagent_type`
values. Give each the same short prompt:

> Review branch `<branch>` as the `<persona key>` persona. Run folder: `<run folder>`. Read
> `<run folder>/brief.md` first and follow it, then `<run folder>/pr-context.md`. Post with the
> command in the brief and finish with the line it prints.

### 4. Report

Say which personas are reviewing the branch, and that their findings will appear in the hub as
they finish. When they do, relay one line per persona: LGTM or N findings.

## Acting on comments

When the user says they have left comments in the hub:

```bash
PY -m dev_hub.review todo <branch>
```

It prints the open comments to act on as JSON: the ones the user wrote, and persona findings they
marked **Address**. Findings they haven't marked, or marked **Dismiss**, are not to be touched.
Each item has its `id`, where it is, the lines and quote it is about, the text, and any replies.
Work through them as the `feature` skill's Phase 2 does, one commit per comment. After each commit:

```bash
PY -m dev_hub.review address <branch> <id> --commit <sha> --as "<persona name>" --reply "<what was done>"
```

That records the reply and marks the comment resolved. The reply says what was done and links the
commit, or says why nothing was changed. Comments follow rebases, so it is safe to rebase and
squash afterwards.
