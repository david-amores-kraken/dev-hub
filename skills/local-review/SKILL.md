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

Up to eight persona agents review a branch, and their findings and summaries are saved in the dev
hub (`http://127.0.0.1:8765/diffs/<branch>`). There is no PR. The agents read a run folder and
write a findings file, and `python -m dev_hub.review` makes the folder and takes the findings.
Their brief is `reference/brief.md` in this skill.

Don't review the branch yourself, and don't wait for the agents.

## Setup (once)

Not done by the repo itself, because it changes `~/.claude`:

1. Link the skill: `ln -s ~/Code/dev-hub/skills/local-review ~/.claude/skills/local-review`.
2. Allow the commands. Add to `permissions.allow` in `~/.claude/settings.json`, along with the
   run folder rules below:
   `Bash(/Users/davidamores/Code/dev-hub/.venv/bin/python -m dev_hub.review:*)`.
   The personas run in the background and can't answer a prompt, so they need this to post. The
   commands only write the review files in `~/Reviews`, the e2e pages in `~/E2E`, and run folders.
3. Run folders are made in the repo's main checkout, so the personas need
   `Read`, `Write` and `Edit` on `//Users/davidamores/Code/kraken-core/.claude/local/local-review/**`.
4. `uv sync` in `~/Code/dev-hub`, so that python exists.

In the commands below, `PY` is `/Users/davidamores/Code/dev-hub/.venv/bin/python`.

## Rules

- **Local branches of the hub's repo only** (`DEV_HUB_REPO`, default kraken-core), and only ones
  with commits the base doesn't have.
- **Personas post; you don't.** Each runs `PY -m dev_hub.review post` as the last line of its brief.
- **Run from the branch's worktree.** The personas read code from where they start.
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

In **one message**, start the agents on the `personas:` line in the background, one Agent call
each:

| `subagent_type` | Persona key |
|---|---|
| `review-conventions` | `conventions` |
| `review-domain` | `domain` |
| `review-tests` | `tests` |
| `review-correctness` | `correctness` |
| `review-writing` | `writing` |
| `review-cross-client` | `cross-client` |
| `review-naming` | `naming` |
| `review-ux` | `ux` (only when listed) |

Give each the same short prompt, and add nothing of your own view of the branch (each persona
starts fresh on purpose):

> Review branch `<branch>` as the `<persona key>` persona. Run folder: `<run folder>`. Read
> `<run folder>/brief.md` first and follow it, then `<run folder>/pr-context.md`. Post with the
> command in the brief and finish with the line it prints.

### 4. Report

Say which personas are reviewing the branch, and that their findings will appear in the hub as
they finish. When they do, relay one line per persona: LGTM or N findings.

## What the personas do with a finding

- On a diff line: a comment on the "All changes" page. On "PR description" or "commit <sha>": a
  comment on that text. With no place: it stays in the persona's review on the overview.
- The user marks a finding **Address** to have it acted on, or **Dismiss** to hide it.
- On a re-run, personas don't repeat open findings, never re-raise dismissed ones, and list the
  ones they see fixed as resolved.

## The PR title and description

The draft PR text is saved in the hub, so it is ready to copy when the branch is pushed to origin.

```bash
PY -m dev_hub.review pr show <branch>
PY -m dev_hub.review pr set <branch> --title "<one line>" --body-file -
```

`--body-file -` reads the description from stdin. A part that is left out stays as it was.

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
