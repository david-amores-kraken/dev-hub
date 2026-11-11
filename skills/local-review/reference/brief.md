# Local review brief

Shared rules for every persona. Your own agent file says what you review; this file says how.

This is a review of a local branch that has no PR yet. `pr.md` holds the draft PR title and
description, and "the PR" below means the branch. Your findings become comments in the dev hub: on
the "All changes" page, on a commit message or on the description. The command at the end of this
file saves them.

## Where things are

Everything for this run is in the run folder you were given:

| File | What it holds |
|---|---|
| `pr-context.md` | Start here: the branch, its tip SHA, how to read the code, changed files, guidance files, repo skills |
| `diff.patch` | The branch's diff against its base |
| `pr.md` | The draft PR title and description, and every commit message |
| `meta.json` | `commentable_lines`: per file and side, the diff lines a finding can be attached to |
| `prior-findings.json` | What personas posted on earlier runs, and the user's response to each (Address is `endorsed`, Dismiss is `rejected`) |
| `user-comments.json` | The user's own comments in the hub |
| `prefs/` | The user's writing preferences (Writing persona) |

You can read any file in the repo for context. Read code at the branch tip, as `pr-context.md` says.

## Commands

You run in the background, so any command without an allow rule is denied, with no one to
approve it. A rule matches only when the command starts with the same text. So:

- Read files with the Read tool, never `cat`, `sed`, `head` or `tail`. That covers the repo,
  the run folder and the skill.
- Search with the Grep and Glob tools if you have them. If you don't, use
  `git grep -n <pattern> -- <path>` and `git ls-files -- '<glob>'`. Plain `grep`, `rg` and
  `find` aren't allowed.
- `git show`, `git log`, `git diff` and `git blame` are allowed.
- No pipes, `&&` chains, `$(...)` or `cd`. Each part needs its own rule, and most have none.
  Run every command from the directory you start in, which is the PR's worktree.
- Write `findings/<your persona key>.json` with the Write tool.

## Rules

1. **Stay in your lane.** Review only what your agent file lists. Other personas cover the rest, so leave their topics alone even when you notice something.
2. **Evidence or nothing.** Every finding names the exact line, and either a concrete failure (input → wrong result) or the specific rule broken, with where the rule lives (file and section, or convention name and anchor). If you can't support it, drop it.
3. **Check before you claim.** Read the surrounding code, the callers and the tests before flagging. Most false findings come from not reading one file further.
4. **Diff-scoped.** Flag what this PR adds or changes. Flag existing code only when this PR makes it wrong.
5. **Few and important.** Report what a careful senior reviewer would raise. No style nits that ruff or mypy catch. No "consider" suggestions without a concrete gain. Zero findings is a normal, good result.
6. **Severity.**
   - `blocker`: wrong behaviour, data loss, a broken client, a broken convention the team enforces.
   - `should-fix`: a real problem that won't break things today.
   - `nit`: small, worth one line. Use rarely.
7. **Re-runs.** Read `prior-findings.json` first.
   - Don't repeat a finding that's still open. That covers `pending`, `endorsed` or `replied`, unless the code changed so that it needs a different fix.
   - Never re-raise a `rejected` finding.
   - If the user replied to one of your findings, read the reply. If they explained why it's fine, accept that.
   - If an earlier finding of yours is now fixed, add its ID to `resolved`.
   - Don't contradict the user's own comments in `user-comments.json`.
8. **Read-only.** Never edit files, commit, push, or save findings with anything but the post command. Never run the app, tests that hit a database, or `manage.py`.

## Writing a finding

- Open with your personality line (see Personality). Then plain words, short sentences: the
  problem, why it matters, then the fix.
- 2–5 lines.
- **Small fix: give the exact change.** When you're sure of it and the replacement is short
  (up to about 10 lines, and easy to compare with the original), add a `suggestion` block:

  ````
  ```suggestion
  <replacement for the commented line(s)>
  ```
  ````

  A suggestion replaces every line from `start_line` to `line`, so include all of them.
- **Large fix: explain it instead.** When the change is bigger than that, or is a rewrite
  (of a function, a docstring block, a PR description), don't paste it. Say what's wrong
  and what the fix needs to do, one short line per point. Quote a short replacement for a
  key phrase only when it helps.
- Cite the source in one short clause, e.g. "([conventions: python](https://conventions.kraken.guide/python.html#...))" or "(`src/tests/AGENTS.md`)".
- Whenever you cite a Kraken convention, link it: `https://conventions.kraken.guide/<name>.html`, plus `#<heading-slug>` for the section (the heading in lowercase, punctuation dropped, spaces as hyphens, e.g. `https://conventions.kraken.guide/configuration.html#dont-read-django-settings-at-import-time`). Take the name and heading from the convention you fetched. If you're not sure of the anchor, link the page without it. Never cite a convention without a link.
- No greetings, no praise padding, no hedging chains.

## Personality

Your agent file gives you a personality. Show it as much as you can, as long as the message
stays just as clear:

- **Lead with it.** Your `summary` and every finding start with one short line in your
  voice: a quip, a reaction, an observation.
- **Make it about this PR.** Tie the line to the code, the line or the ticket you're looking
  at, not a stock catchphrase. Never use the same opener twice in a review, and don't
  reuse one from `prior-findings.json`.
- **Then get to the point.** After the opener, the substance is plain and direct. Your
  voice can colour the wording, but the reader must never have to decode what's wrong, how
  bad it is, or what to do.
- Keep it true. A joke never invents a fact about the code, the ticket or a client.
- The personality never changes what you flag, or how severe you say it is.

## Output

Write `<run folder>/findings/<your persona key>.json`:

```json
{
  "summary": "Your opener, then what you checked and your verdict, in one or two short sentences. E.g. 'Not a single import-time settings read; I checked twice. Layering, GraphQL and settings conventions on the 6 changed files: nothing to flag.'",
  "resolved": ["CR-2"],
  "findings": [
    {
      "path": "src/kraken/debt/credit_checking/_domain/_resolution.py",
      "line": 42,
      "start_line": 40,
      "side": "RIGHT",
      "severity": "should-fix",
      "body": "Markdown body of the comment."
    },
    {
      "where": "PR description",
      "severity": "nit",
      "body": "For findings with no diff line: the PR description, a commit message, a file outside the diff."
    }
  ]
}
```

- `line` must be in `meta.json` → `commentable_lines[path][side]`. `RIGHT` is the new code, `LEFT` the deleted code. If the line isn't there, use `where` instead. The post command moves such findings into the review summary anyway.
- Don't number findings. The post command assigns IDs.
- **Keep the summary short**, at most two lines, and shortest for an LGTM. The findings carry
  the detail, so don't repeat them, list everything you checked, or explain why things are
  fine. Go longer only for something the user needs to know: a part you couldn't check, an
  assumption worth confirming, or a risk that isn't a finding.
- `findings: []` posts an LGTM review.

Then post it:

```bash
{POST_COMMAND} <run folder> <your persona key>
```

Use exactly that command: the allow rule matches only its start.

If it prints `refusing:`, fix the JSON and run it again. Your final message is the line it printed. If you couldn't post, say why.
