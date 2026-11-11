# dev-hub

One local web page for the dev work around the code. It runs at http://127.0.0.1:8765 and has a
section per tool:

| Section | URL | What it shows | Lives in |
|---|---|---|---|
| PRs | `/prs/` | PRs waiting for my review, and the briefs made for them | the `pr-brief` skill (`~/.claude/skills/pr-brief`) |
| Features | `/features/` | One page per feature, with its plan and report side by side as tabs | `src/dev_hub/features` |
| Diffs | `/diffs/` | A branch of kraken-core commit by commit, with a PR title and body to write | `src/dev_hub/diffs` |
| Plans | `/plans/` | Plans the `feature` skill saved in `~/Plans` | `src/dev_hub/plans` |

## How it fits together

- `src/dev_hub/app.py` builds the Flask app. It owns the safety checks, the nav and the URL prefix
  of each section. A section is a Flask blueprint.
- The PR section is a blueprint exported by the `pr-brief` package, which stays under
  `~/.claude/skills/pr-brief` because its `SKILL.md`, poller and CLI belong to the skill. The hub
  depends on it (`[tool.uv.sources]` in `pyproject.toml`); it doesn't depend on the hub.
- Sections extend `templates/base.html`, which has the blocks `title`, `head`, `content`, `scripts`.
  `static/hub.css` has the shared look; a section adds its own CSS next to its templates.
- Data stays where its tool writes it (`~/pr-reviews`, `~/Plans`, `~/Reports`). The only data the hub owns is what I write in the Diffs section, in `~/Reviews`.

## Safety

It listens on `127.0.0.1` only. Any web page can send requests to localhost, so every request must
carry the hub's own `Host`, and every POST must be JSON from the hub's own origin. Some sections
spend money when posted to (PR briefs), so don't weaken this. Plans and reports are model-written HTML, so they
are shown in a sandboxed frame (no scripts, no network).

## Features

A feature is a branch. The feature skill names its plan and its report after the branch, and the
Features section joins them by that name. A feature with only a plan or only a report is still
listed. To show another part of a feature (a PR, a review), add it to the tab list in
`features/views.py` and to the store. `DEV_HUB_REPORTS` changes where reports are read from.

## Diffs

A local version of a GitHub PR page, for reading my own branches before I push. It reads the repo
at `DEV_HUB_REPO` (default `~/Code/kraken-core`) and lists local branches that have commits the
base doesn't. The base is `DEV_HUB_BASE` (default `origin/master`).

- A branch's commits are `base..branch`, as a PR lists them, so a rebase or a base that has moved on
  doesn't change the list. "All changes" is `base...branch`.
- Nothing is checked out. Branches and commits are read from the refs.
- The overview has a title and description box for the PR. It saves to `~/Reviews/<branch>.json`
  (`DEV_HUB_REVIEWS` changes the folder; `/` in the branch name is written as `%2F`).
- Diffs are drawn in the browser by [diff2html](https://diff2html.xyz) 3.4.52, with highlight.js
  colours. Both are vendored under `diffs/static/vendor`; there is no build step. To update them,
  download the same files from the new version.

## Running it

It starts at login through launchd (`~/Library/LaunchAgents/com.davidamores.dev-hub.plist`, logs in
`~/Library/Logs/dev-hub.{out,err}`) and restarts if it crashes.

```bash
uv sync                                   # first time, or after changing dependencies
uv run python -m dev_hub                  # run it by hand (stop the launchd job first)
launchctl kickstart -k gui/$(id -u)/com.davidamores.dev-hub   # restart the launchd job
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

GitHub Actions runs the same checks on every PR (`.github/workflows/ci.yml`). The `pr-brief` package
only exists on my machine, so CI installs a small stand-in from `.github/ci/pr-brief`. If the PR
section's tests start to need more of the real one, grow the stand-in.

`DEV_HUB_PORT` changes the port. If you do, set `hub_url` in the pr-brief `config.json` to match.

## Adding a section

1. Make a package with a `Blueprint` (templates in `templates/<name>/`, extending `base.html`).
2. Add it to `SECTIONS` in `app.py`.
3. Add a test that it renders inside the hub.
