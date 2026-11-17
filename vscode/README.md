# Dev Hub review in VS Code (proof of concept)

A look at what reviewing a feature could be like in VS Code, instead of the hub's Features and
Diffs sections. It reads the hub's folders (`~/Plans`, `~/Reports`, `~/E2E`, `~/Reviews`) and the
repo, and never writes to them. The hub's comments are loaded into VS Code, but replies,
resolving, triage and new comments are kept in memory only, so they are lost when the window
reloads.

The **Dev Hub review** icon in the activity bar shows three groups for the branch:

- **The feature**, under its title: the plan, report and e2e results the skills saved, and the PR
  description. Plan, report and e2e results are HTML, so they open in a webview. As in the hub,
  they get no scripts and no network. They can't take comments, because VS Code's Comments API
  only works in text editors. The PR description opens as text and can take comments.
- **Reviews**: the comments on the branch, grouped by the persona that wrote them, then yours.
  A persona's tooltip is its review summary. Clicking a comment opens its diff at its lines.
- **Changes**: "All changes", then each commit with its message and changed files, as the hub
  does (`base..branch`).

Comments:

- Clicking a file opens it in VS Code's diff editor, with syntax highlighting.
- Each hub comment shows as a thread on its lines, with the persona as author and the agent's
  replies under it. If its lines have changed, it moves to where its quoted text is now, or stays
  put and says "lines changed since". A comment on a commit that is no longer on the branch can't
  be placed, and is only listed under Reviews.
- A finding has **Address** and **Dismiss** buttons, as in the hub. Any thread can be resolved
  or reopened.
- Hover a line number and click **+** to comment on it, or select lines first to comment on a
  range. This works in diffs, commit messages and the PR description. The Comments panel lists
  every thread.

## Try it

There is no build step. To look around, open a window with the extension loaded:

```bash
code --extensionDevelopmentPath="$HOME/Code/dev-hub/vscode" ~/Code/kraken-core
```

Then pick a branch with the branch button at the top of the view.

A `vscode://` link only reaches installed extensions, not one loaded as above. To try the
pop-up, package and install it (`code --uninstall-extension local.dev-hub-review-poc` removes it):

```bash
npx @vscode/vsce@3.2.1 package --allow-missing-repository --skip-license -o /tmp/dev-hub-review-poc.vsix
code --install-extension /tmp/dev-hub-review-poc.vsix
```

Then, to see how a feature could pop up on its own when it's ready for review, open a link like
this one from a terminal. VS Code may ask once whether the extension can open it:

```bash
open "vscode://local.dev-hub-review-poc/open?branch=debt/credit-checking/domestic-data-request-endpoint"
```

It shows that branch and opens the first file of its first commit.

The settings match the hub's environment variables: `devHubReview.repo` (default
`~/Code/kraken-core`), `devHubReview.base` (default `origin/master`), and `devHubReview.plans`,
`.reports`, `.e2e` and `.reviews` for the hub's folders.
