// @ts-check
// Review a feature in VS Code: its plan, report and e2e results, the persona reviews, and its
// commits in VS Code's diff editor. The dev hub does the work and keeps everything; this shows
// what it says and sends it each change. See README.md.
"use strict";

const vscode = require("vscode");
const { Threads } = require("./src/comments");
const { Documents, SCHEME, diffCommand } = require("./src/documents");
const { Hub } = require("./src/hub");
const { Pages } = require("./src/pages");
const { Review } = require("./src/review");
const { Tree } = require("./src/tree");

const VIEW = "devHubReview.feature";

const hubUrl = () => vscode.workspace.getConfiguration("devHubReview").get("hubUrl", "http://127.0.0.1:8765");

async function pickBranch(/** @type {Review} */ review) {
  /** @type {{ name: string, commits: number, updated: string, subject: string, feature: boolean }[]} */
  let branches;
  try {
    branches = await review.hub.get("/api/branches");
  } catch (error) {
    vscode.window.showErrorMessage(error instanceof Error ? error.message : String(error));
    return;
  }
  const picked = await vscode.window.showQuickPick(
    branches.map(b => ({
      label: b.name,
      description: [b.commits ? `${b.commits} commits · ${b.updated}` : "no commits yet", b.feature ? "feature" : ""]
        .filter(Boolean)
        .join(" · "),
      detail: b.commits ? b.subject : undefined,
    })),
    { placeHolder: "A local branch with commits to review, or with a feature", matchOnDetail: true },
  );
  if (picked) await review.setBranch(picked.label);
}

/** Show a branch and open its first changed file, so the review starts straight away. This is
 * what the hub's "Open in VS Code" links do. */
async function openBranch(/** @type {Review} */ review, /** @type {string} */ branch) {
  await review.setBranch(branch);
  await vscode.commands.executeCommand(`${VIEW}.focus`);
  const data = review.data;
  if (!data) {
    if (review.error) vscode.window.showErrorMessage(review.error);
    return;
  }
  const first = data.commits[0];
  const file = first && data.files[first.sha]?.[0];
  if (file) {
    const open = diffCommand(data, first.sha, file);
    await vscode.commands.executeCommand(open.command, ...open.arguments);
  }
}

function activate(/** @type {vscode.ExtensionContext} */ context) {
  const hub = new Hub(hubUrl);
  const review = new Review(hub, context.workspaceState);
  const threads = new Threads(review);
  const pages = new Pages(review);
  const tree = new Tree(review);
  const view = vscode.window.createTreeView(VIEW, { treeDataProvider: tree, showCollapseAll: true });
  const describe = () => { view.description = review.branch; };
  review.onDidChange(describe);
  describe();
  threads.register(context);

  context.subscriptions.push(
    view,
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, new Documents(review)),
    vscode.commands.registerCommand("devHubReview.pickBranch", () => pickBranch(review)),
    vscode.commands.registerCommand("devHubReview.refresh", () => Promise.all([review.reload(), pages.refresh()])),
    vscode.commands.registerCommand("devHubReview.openPage", part => pages.open(part)),
    vscode.commands.registerCommand("devHubReview.openInHub", () => {
      const data = review.data;
      if (data) vscode.env.openExternal(vscode.Uri.parse(hub.link(data.feature?.url ?? data.urls.overview)));
    }),
    // Agents and skills add findings and pages while I'm away, so look again on coming back.
    vscode.window.onDidChangeWindowState(state => { if (state.focused && view.visible) review.reloadIfStale(); }),
    view.onDidChangeVisibility(event => { if (event.visible) review.reloadIfStale(); }),
    vscode.workspace.onDidChangeConfiguration(event => { if (event.affectsConfiguration("devHubReview.hubUrl")) review.reload(); }),
    // vscode://local.dev-hub-review/open?branch=<branch> brings the window up on that branch.
    vscode.window.registerUriHandler({
      handleUri(uri) {
        const branch = new URLSearchParams(uri.query).get("branch");
        if (uri.path === "/open" && branch) return openBranch(review, branch);
      },
    }),
  );
  review.reload();
}

module.exports = { activate, deactivate() {} };
