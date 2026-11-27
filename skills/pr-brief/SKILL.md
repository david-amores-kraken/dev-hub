---
name: pr-brief
description: Prepare the user to review someone else's PR. Six or seven of the local-review personas (UX only when the PR changes something a user sees) review it without posting, and their findings, the PR's goal and a focus/skim/skip call per commit go into an HTML brief under ~/pr-reviews. Never posts, approves or runs the PR's code.
when_to_use: Use when the user asks for a brief or a review prep of a PR they've been asked to review ("brief PR 311070", "/pr-brief 311070", "help me review 311070", "what should I look at in this PR"), or when the pr-brief poller starts it. Not for the user's own branches (that's local-review). Each run starts six or seven agents.
argument-hint: "<pr-number> [again] [what to focus on]"
arguments:
  - pr
  - again
---

# pr-brief

Write a brief that helps the user review PR **#$pr** themselves. Six or seven local-review
personas review it in pr-brief mode: they write JSON instead of posting. `assemble.py` merges their
findings, works out which commits deserve the user's time, and writes `report.json`. The dev hub
(http://127.0.0.1:8765/prs/) renders it.

## Setup (once)

Not done by the repo itself, because it changes `~/.claude` and launchd:

1. Link the skill: `ln -s ~/Code/dev-hub/skills/pr-brief ~/.claude/skills/pr-brief`.
2. Copy `config.example.json` to `~/pr-reviews/config.json` and fill it in.
3. `uv sync` in `~/Code/dev-hub`, so that python exists.
4. The poller's launchd job (`com.davidamores.pr-brief`) runs
   `/Users/davidamores/Code/dev-hub/.venv/bin/python -m dev_hub.prs.poll` every 15 minutes from
   the kraken-core checkout.

## Rules

- **Never post anything** to GitHub, Asana or Slack, and never approve or request changes.
- **Never run the PR's code.** It's checked out in its own worktree for reading only, with git
  hooks off. No tests, `inv`, scripts or installs from it.
- **Don't brief the PR yourself.** You run the steps; each persona starts fresh, with only the
  run folder. Don't add your own view of the PR to their prompts.
- **One brief per PR unless the user asks for another.** Pass `--again` only when the user's
  own message asks for a re-brief (`/pr-brief 311070 again`, "re-brief 311070", "brief it
  again"). Never pass it when the poller started you, or to get past a refusal.
- **Run from the kraken-core checkout** (or any worktree of it). `prepare.py` fetches the PR
  into the main repo.

## Steps

### 1. Prepare the run

```bash
/Users/davidamores/Code/dev-hub/.venv/bin/python -m dev_hub.prs.prepare <pr> [--again] [--tier note|light|standard|large] [--focus "<text>"]
```

If the user's message says what to look at more closely ("brief 311070, focus on the
migration"), pass their words as `--focus`, unchanged.

**If your instructions say the poller already prepared the run, skip this step** and use the run
folder and personas you were given. Never prepare it twice.

It fetches the PR, checks the head out at `~/pr-reviews/worktrees/pr<n>`, and works out the
mechanical facts with git. It takes about a minute. The last line is the run folder. If it
prints `refusing:`, stop and report why. A draft PR is refused unless the user passes `--tier`
(only when their own message asks to brief a draft). When the PR already has a brief, give the user the
URL of its brief (`http://127.0.0.1:8765/prs/<pr>`) and say they can ask for `/pr-brief <pr> again`. The `personas:`
line lists the personas to start. The `tier:` line says how much review the PR gets (see
**Tiers** below). UX is on it only when the diff changes something an end
user sees (`pr-context.md` lists the files that matched, and why). The `focus:` line says whether
the user gave focus instructions; if so they're in `<run folder>/focus.md`.

### 2. Start the personas

In **one message**, start the agents on the `personas:` line, one Agent call each, so they
run at once:

| `subagent_type` | Key |
|---|---|
| `review-domain` | `domain` |
| `review-correctness` | `correctness` |
| `review-cross-client` | `cross-client` |
| `review-tests` | `tests` |
| `review-conventions` | `conventions` |
| `review-naming` | `naming` |
| `review-ux` | `ux` (only when listed) |
| `brief-general` | `general` (light tier only, and the only agent there) |

On the **note** tier the `personas:` line is `none`: don't start anything, go to step 3.

Writing doesn't run here: it checks against the user's own writing preferences, which don't
apply to someone else's PR.

Give each the same short prompt:

> This is a **pr-brief** run, not local-review: don't post anything. Review PR #<pr> as the
> `<key>` persona. Run folder: `<run folder>`. Read `<run folder>/brief.md` first: where it
> differs from your agent file, it wins. Write `<run folder>/out/<key>.json` and finish with
> the line `wrote out/<key>.json`.

Wait for all of them.

**If there's a `focus.md`**, read it before starting anyone. The personas read it themselves
(`brief.md` tells them how), so don't add it to their prompts. You only decide whether anyone
is missing, on the **standard** and **large** tiers:

- If it asks about something a user sees and `ux` isn't on the `personas:` line, start
  `review-ux` too, with the same prompt.
- If part of it fits no persona on the list (for example "is the commit history easy to
  follow?"), also start `brief-general` with key `general`, and add to its prompt: "Your lane
  is only the user's focus in `focus.md`: the other personas cover the rest. Leave out `goal`,
  `ticket` and `commits`."

Start these in the same message as the others. `assemble.py` picks up their output. Don't add
agents for any other reason, and never drop one from the list.

### 3. Assemble and render

```bash
/Users/davidamores/Code/dev-hub/.venv/bin/python -m dev_hub.prs.assemble <run folder>
```

It writes `report.json` in the run folder and prints the brief's URL. The report has four parts:

- **Your focus**, only when the user gave one: their words, each persona's answer, and which
  findings are about it.
- **Goal**, from the Domain persona, with the ticket match.
- **Findings** from every persona, most severe first (blocker, should-fix, question, nit).
  Findings from different personas on the same lines share one card. A finding a reviewer
  already raised in the PR is tagged. On a re-run, each card is marked new or still open, and
  the last brief's findings that nobody raised again are listed as gone.
- **Open threads**: unresolved review threads other reviewers started, and whether the
  author has replied.
- **Commits**, each with a line from Domain on what it does, marked focus, skim or skip, and
  new if it wasn't in the last brief (a rebased commit with the same patch isn't new). Skip
  needs git to prove the commit mechanical. Focus means it has a blocker or should-fix
  finding, resolves merge conflicts, touches a migration, raw SQL, a transaction or
  permissions, or changes 40+ lines outside tests. Everything else is skim. `git blame` links
  each finding to its commit.

Line references in the personas' text (`path:line`) become links to the PR diff.

Malformed persona output is dropped and listed in the report, not fatal.

### 4. Report

Tell the user in a few lines: the PR's goal, what the personas said about the focus (if any), the finding counts by severity and the commit
tiers the script printed, on a re-run what's new and what's gone, any problems it listed, and
the URL it printed. If a persona
failed, say which.

## Tiers

`prepare.py` picks the tier from what git worked out about the diff, and the thresholds are in
`config.json`.

| Tier | When | Who reviews |
|---|---|---|
| note | every change is mechanical (renames, whitespace, lockfiles) | nobody; the report just says so |
| light | about 40 substantive lines or fewer, 3 files or fewer, nothing risky | one `brief-general` agent, so a short report |
| standard | everything between | the personas above |
| large | about 600 substantive lines or more, or 25 files or more | the personas above, each told to cover the whole diff in order |

Anything risky (a migration, raw SQL, a transaction, permissions, settings) rules out light,
whatever the size. A different tier can be forced with `--tier`: the index page's Brief button
does this with the level the user picks, and then asks for optional focus instructions, which
become `--focus`. The page suggests one from the PR's size alone
(`suggest_tier` in `tiers.py`) and explains each level under "What each review level does".

## Cost

The poller passes `--max-budget-usd` for the tier (`budget_usd` in `config.json`) and, after the
session, `usage.py` estimates the spend per agent from the transcripts into `cost.json`. The
report shows it under Run. The caps are deliberately high until there is real data to set them.

## Files

The code is the `dev_hub.prs` package in `~/Code/dev-hub`, checked with the rest of the hub (see
its `AGENTS.md`).

- `~/.claude/agents/review-*.md`: what each persona reviews. They're shared with local-review.
- `reference/brief.md`: the pr-brief rules every persona follows, and the JSON they write.
  It's copied into the run folder, and it overrides the local-review parts of the agent files.
- `~/pr-reviews/config.json`: the tier thresholds, spending caps, review groups,
  `auto_brief_authors` and the team. `config.example.json` shows every key.
- `src/dev_hub/prs/` in the repo:
  - `prepare.py`, `facts.py`: gather the PR and its mechanical facts.
  - `tiers.py`: the tier a PR gets, and the one suggested from its size.
  - `assemble.py`: merge the personas' output into `report.json`.
  - `usage.py`: estimates what a run cost, per agent.
  - `poll.py`: every 15 minutes (launchd `com.davidamores.pr-brief`) refreshes
    `~/pr-reviews/queue.json` with the open PRs awaiting the user's review (from anyone, directly or
    through `reviewer_groups`) and runs each queued request headlessly. PRs by
    `auto_brief_authors` are briefed without a request.
  - `store.py`: the files under `~/pr-reviews` (queue, requests, marks, history, runs).
  - `views.py`: the PR section of the dev hub, as a Flask blueprint (served at
    http://127.0.0.1:8765/prs/, from launchd `com.davidamores.dev-hub`). `templates/` and `static/`
    hold the HTML, CSS and JS; `rows.py` builds the one table of PRs; `report.py` holds the filters
    the brief page uses. The Brief button posts the PR, the tier and any focus, which becomes
    `~/pr-reviews/requests/<pr>.json` and starts `poll --requests-only`. The hub does the host and
    origin checks, because a brief costs money; don't serve this blueprint any other way.
- `src/dev_hub/review_context.py`: helpers shared with local-review.
- `~/pr-reviews/`: `runs/pr<n>/<time>-<sha>/` per brief, `worktrees/pr<n>` (the PR's code, large),
  `marks.json` (reviewed or won't review), `history.json` (briefs removed to save space).
