// @ts-check
// Review a feature in VS Code: its plan, report and e2e results, the persona reviews, and its
// commits in VS Code's diff editor. The dev hub does the work and keeps everything; this shows
// what it says and sends it each change. See README.md.
"use strict";

const vscode = require("vscode");
const { Threads } = require("./src/comments");
const { Documents, SCHEME, diffCommand, docOf } = require("./src/documents");
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

/** The repo path of the file a diff or a row under Changes is about. From the diff's title bar
 * VS Code passes the diff's URI; from the view it passes the row. */
function changedPath(/** @type {vscode.Uri | import("./src/tree").Node | undefined} */ target) {
  if (target && !(target instanceof vscode.Uri)) return target.file;
  const uri = target ?? vscode.window.activeTextEditor?.document.uri;
  const doc = uri && docOf(uri)?.doc;
  return doc?.kind === "file" ? doc.path : undefined;
}

/** Show a changed file in the Explorer. The hub doesn't say where the repo is, so this looks for
 * the file in each workspace folder. It is the working copy's file, which may be on another
 * branch than the one under review. */
async function revealFile(/** @type {vscode.Uri | import("./src/tree").Node | undefined} */ target) {
  const file = changedPath(target);
  if (!file) return;
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const uri = vscode.Uri.joinPath(folder.uri, file);
    try {
      await vscode.workspace.fs.stat(uri);
    } catch {
      continue;
    }
    await vscode.commands.executeCommand("revealInExplorer", uri);
    return;
  }
  vscode.window.showWarningMessage(`${file} isn't in this workspace. The repo may not be open here, or the file isn't in the working copy.`);
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
    vscode.commands.registerCommand("devHubReview.revealFile", revealFile),
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
