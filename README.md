# dev-hub

One local web page for the dev work around the code. It runs at http://127.0.0.1:8765 and has a
section per tool:

| Section | URL | What it shows | Lives in |
|---|---|---|---|
| PRs | `/prs/` | PRs waiting for my review, and the briefs made for them | the `pr-brief` skill (`~/.claude/skills/pr-brief`) |
| Plans | `/plans/` | Plans the `feature` skill saved in `~/Plans` | `src/dev_hub/plans` |

## How it fits together

- `src/dev_hub/app.py` builds the Flask app. It owns the safety checks, the nav and the URL prefix
  of each section. A section is a Flask blueprint.
- The PR section is a blueprint exported by the `pr-brief` package, which stays under
  `~/.claude/skills/pr-brief` because its `SKILL.md`, poller and CLI belong to the skill. The hub
  depends on it (`[tool.uv.sources]` in `pyproject.toml`); it doesn't depend on the hub.
- Sections extend `templates/base.html`, which has the blocks `title`, `head`, `content`, `scripts`.
  `static/hub.css` has the shared look; a section adds its own CSS next to its templates.
- Data stays where its tool writes it (`~/pr-reviews`, `~/Plans`). The hub keeps none of its own.

## Safety

It listens on `127.0.0.1` only. Any web page can send requests to localhost, so every request must
carry the hub's own `Host`, and every POST must be JSON from the hub's own origin. Some sections
spend money when posted to (PR briefs), so don't weaken this. Plans are model-written HTML, so they
are shown in a sandboxed frame (no scripts, no network).

## Running it

It starts at login through launchd (`~/Library/LaunchAgents/com.davidamores.dev-hub.plist`, logs in
`~/Library/Logs/dev-hub.{out,err}`) and restarts if it crashes.

```bash
uv sync                                   # first time, or after changing dependencies
uv run python -m dev_hub                  # run it by hand (stop the launchd job first)
launchctl kickstart -k gui/$(id -u)/com.davidamores.dev-hub   # restart the launchd job
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

`DEV_HUB_PORT` changes the port. If you do, set `hub_url` in the pr-brief `config.json` to match.

## Adding a section

1. Make a package with a `Blueprint` (templates in `templates/<name>/`, extending `base.html`).
2. Add it to `SECTIONS` in `app.py`.
3. Add a test that it renders inside the hub.
