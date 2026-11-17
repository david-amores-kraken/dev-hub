# Dev Hub review in VS Code (proof of concept)

A look at what reviewing a branch in VS Code could be like, instead of the hub's Diffs section.
It is UI only: it reads the repo with git and keeps comments in memory, so they are lost when the
window reloads. It doesn't read or write the hub's comments in `~/Reviews` yet.

- The **Dev Hub review** icon in the activity bar lists the branch: "All changes", then each
  commit with its message and changed files, as the hub does (`base..branch`).
- Clicking a file opens it in VS Code's diff editor, with syntax highlighting.
- Hover a line number and click **+** to comment on it, or select lines first to comment on a
  range. Comments can be replied to, edited, deleted and resolved. Commit messages can be
  commented on too. The Comments panel lists every thread.

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

It shows that branch and opens the first file of its first commit. `devHubReview.repo` (default
`~/Code/kraken-core`) and `devHubReview.base` (default `origin/master`) are settings.
