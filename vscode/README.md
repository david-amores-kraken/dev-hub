# Dev Hub review for VS Code

Review a feature in VS Code instead of the browser: its plan, report and e2e results, the persona
reviews, and its commits in VS Code's diff editor, with comments on the lines.

The extension is a client of the dev hub. The hub works everything out and keeps everything
(`/api` in `src/dev_hub/api`), so the extension and the hub's pages always show the same thing.
A comment made, answered, resolved or triaged in one shows up in the other. The hub must be
running.

## What it shows

Pick a branch with the branch button at the top of the view. It lists the local branches with
commits that `origin/master` doesn't have, and those with a feature (a plan, say), so a feature
can be opened before its first commit.

The **Dev Hub review** icon in the activity bar shows three groups for the branch:

- **The feature**, under its plan's title: the plan, report and e2e results, the PR description,
  and a link to the feature in the hub. The plan, report and e2e results are HTML, so they open in
  a webview, with the hub's sandbox (no scripts, no network). They can't take comments, because
  VS Code's comments only work in text editors.
- **Reviews**: the comments, grouped by the persona that wrote them (latest review first), then
  yours. A persona's tooltip is its review summary. Clicking a comment opens it on its lines.
- **Changes**: "All changes", then each commit with its message and files, with the number of open
  comments on each, as in the hub.

Comments:

- A comment is shown on the pages the hub shows it on. A comment on a commit's lines is also on
  "All changes" if those lines are still there, and the other way round, as in the hub.
- A comment whose commit or lines have changed can't be shown on the code. It is listed under
  Reviews with a warning icon, and the hub's Overview shows it with its quote.
- Lines take comments where the hub's diff pages offer them: lines in the diff, with removed
  lines on the left. A commit message and the PR description take them on any line.
- Findings have **Address** and **Dismiss** buttons. Any thread can be resolved or reopened. Your
  comments and replies can be edited and deleted; a finding is answered with a reply, not edited.

It reads the hub again when you come back to the window, after each change, and on **Refresh**.
Open plan, report and e2e pages are read again only on Refresh, because e2e pages can be large.

## Install

```bash
cd vscode
npm ci
npm run install-extension
```

That packages `dev-hub-review.vsix` and installs it. Reload any open VS Code window to use the
new version. If the old proof of concept is installed, remove it:
`code --uninstall-extension local.dev-hub-review-poc`.

`devHubReview.hubUrl` is the hub's address (default `http://127.0.0.1:8765`).

## Open a branch from outside

The hub's diff and feature pages have an **Open in VS Code** link. It opens a link like this one,
which shows the branch and opens the first file of its first commit:

```bash
open "vscode://local.dev-hub-review/open?branch=debt/credit-checking/domestic-data-request-endpoint"
```

VS Code may ask once whether the extension can open it.

## Develop

Plain JavaScript with type comments, so there is no build step. `src/model.js` has what can be
worked out without VS Code, and its tests. The rest is thin: `hub.js` talks to the hub,
`review.js` keeps what it last said, and `tree.js`, `comments.js`, `documents.js` and `pages.js`
show it.

```bash
npm run check   # type-check
npm test        # unit tests
code --extensionDevelopmentPath="$PWD" ~/Code/kraken-core   # try it without installing
```
