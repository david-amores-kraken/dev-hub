// @ts-check
// A proof of concept: read a local branch commit by commit in VS Code's own diff editor, and
// comment on lines with VS Code's Comments API. It reads the repo with git and keeps comments in
// memory, so they are gone when the window reloads. It doesn't talk to the dev hub yet.
"use strict";

const vscode = require("vscode");
const { execFile } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");

// devhub:/<path in repo>?<commit>  is that file at that commit. An empty commit means the file
//                                  doesn't exist on that side of the diff (added or deleted).
// devhub-msg:/<name>?<commit>      is the commit's message, so it can be commented on too.
const FILE_SCHEME = "devhub";
const MESSAGE_SCHEME = "devhub-msg";
const BRANCH_KEY = "devHubReview.branch";

function setting(name, fallback) {
  return vscode.workspace.getConfiguration("devHubReview").get(name, fallback);
}

function repo() {
  return setting("repo", "~/Code/kraken-core").replace(/^~(?=$|\/)/, os.homedir());
}

function base() {
  return setting("base", "origin/master");
}

/** @returns {Promise<string>} */
function git(...args) {
  return new Promise((resolve, reject) => {
    execFile("git", ["-C", repo(), ...args], { maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) reject(new Error(stderr.trim() || error.message));
      else resolve(stdout);
    });
  });
}

const fileUri = (file, commit) => vscode.Uri.from({ scheme: FILE_SCHEME, path: `/${file}`, query: commit });

// --- what the diff editor shows

const contents = {
  async provideTextDocumentContent(/** @type {vscode.Uri} */ uri) {
    if (!uri.query) return "";
    if (uri.scheme === MESSAGE_SCHEME) return git("log", "-1", "--format=%B", uri.query);
    try {
      return await git("show", `${uri.query}:${uri.path.slice(1)}`);
    } catch {
      return "";
    }
  },
};

// --- the tree: All changes, then each commit with its message and files

/** @typedef {{ item: vscode.TreeItem, children?: () => Promise<Node[]> }} Node */

class BranchTree {
  constructor(/** @type {vscode.Memento} */ state) {
    this.state = state;
    this.changed = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.changed.event;
  }

  /** @returns {string | undefined} */
  get branch() {
    return this.state.get(BRANCH_KEY);
  }

  async setBranch(/** @type {string} */ branch) {
    await this.state.update(BRANCH_KEY, branch);
    this.changed.fire(undefined);
  }

  refresh() {
    this.changed.fire(undefined);
  }

  getTreeItem(/** @type {Node} */ node) {
    return node.item;
  }

  /** @returns {Promise<Node[]>} */
  async getChildren(/** @type {Node | undefined} */ node) {
    if (node) return node.children ? node.children() : [];
    const branch = this.branch;
    if (!branch) {
      const pick = new vscode.TreeItem("Pick a branch to review…");
      pick.iconPath = new vscode.ThemeIcon("git-branch");
      pick.command = { command: "devHubReview.pickBranch", title: "Pick a branch" };
      return [{ item: pick }];
    }
    const [tip, mergeBase, log] = await Promise.all([
      git("rev-parse", branch),
      git("merge-base", base(), branch),
      git("log", "--reverse", "--format=%H%x1f%s", `${base()}..${branch}`),
    ]);
    const commits = log.split("\n").filter(Boolean).map(line => line.split("\x1f"));
    const all = new vscode.TreeItem("All changes", vscode.TreeItemCollapsibleState.Collapsed);
    all.iconPath = new vscode.ThemeIcon("files");
    all.description = `${commits.length} commits`;
    return [
      { item: all, children: () => files(mergeBase.trim(), tip.trim(), "all changes") },
      ...commits.map(([sha, subject], i) => commitNode(sha, subject, i + 1)),
    ];
  }
}

/** @returns {Node} */
function commitNode(/** @type {string} */ sha, /** @type {string} */ subject, /** @type {number} */ number) {
  const item = new vscode.TreeItem(`${number}  ${subject}`, vscode.TreeItemCollapsibleState.Collapsed);
  item.description = sha.slice(0, 10);
  item.iconPath = new vscode.ThemeIcon("git-commit");
  item.tooltip = subject;
  return {
    item,
    children: async () => {
      const message = new vscode.TreeItem("Commit message");
      message.iconPath = new vscode.ThemeIcon("note");
      const uri = vscode.Uri.from({ scheme: MESSAGE_SCHEME, path: `/Commit ${number} message`, query: sha });
      message.command = { command: "vscode.open", title: "Open", arguments: [uri, { preview: true }] };
      return [{ item: message }, ...(await files(`${sha}^`, sha, `commit ${number}`))];
    },
  };
}

const STATUS = {
  A: ["added", "diff-added"],
  D: ["deleted", "diff-removed"],
  M: ["changed", "diff-modified"],
  R: ["renamed", "diff-renamed"],
  C: ["copied", "diff-added"],
};

/** The files that changed from `left` to `right`, each opening its diff when clicked. */
async function files(/** @type {string} */ left, /** @type {string} */ right, /** @type {string} */ where) {
  const listing = await git("diff", "--name-status", "-M", left, right);
  return listing
    .split("\n")
    .filter(Boolean)
    .map(line => {
      const [code, oldPath, newPath = oldPath] = line.split("\t");
      const [label, icon] = STATUS[code[0]] ?? ["changed", "diff-modified"];
      const item = new vscode.TreeItem(path.basename(newPath));
      item.description = `${path.dirname(newPath)} · ${label}`;
      item.tooltip = code[0] === "R" ? `${oldPath} → ${newPath}` : newPath;
      item.iconPath = new vscode.ThemeIcon(icon);
      item.command = {
        command: "vscode.diff",
        title: "Open diff",
        arguments: [
          fileUri(oldPath, code[0] === "A" ? "" : left),
          fileUri(newPath, code[0] === "D" ? "" : right),
          `${path.basename(newPath)} (${where})`,
          { preview: true },
        ],
      };
      return /** @type {Node} */ ({ item });
    });
}

// --- comments, in memory

let nextId = 1;

class Note {
  constructor(/** @type {string} */ body, /** @type {vscode.CommentThread} */ thread, /** @type {string} */ author) {
    this.id = nextId++;
    this.body = new vscode.MarkdownString(body);
    this.savedBody = this.body;
    this.mode = vscode.CommentMode.Preview;
    this.author = { name: author };
    this.timestamp = new Date();
    this.parent = thread;
  }
}

/** Re-assign the thread's comments, which is how VS Code is told to redraw them. */
function update(/** @type {Note} */ note, /** @type {(n: Note) => void} */ change) {
  note.parent.comments = note.parent.comments.map(c => {
    if (/** @type {Note} */ (c).id === note.id) change(/** @type {Note} */ (c));
    return c;
  });
}

function registerComments(/** @type {vscode.ExtensionContext} */ context, /** @type {string} */ author) {
  const controller = vscode.comments.createCommentController("devhub-review", "Dev Hub review");
  controller.options = { placeHolder: "Comment on this line, or on the lines you selected", prompt: "Add a comment" };
  // Every line of a diff or commit message can take a comment.
  controller.commentingRangeProvider = {
    provideCommentingRanges(document) {
      if (![FILE_SCHEME, MESSAGE_SCHEME].includes(document.uri.scheme)) return [];
      return [new vscode.Range(0, 0, Math.max(document.lineCount - 1, 0), 0)];
    },
  };

  const add = (/** @type {vscode.CommentReply} */ reply) => {
    const thread = reply.thread;
    thread.canReply = true;
    thread.contextValue ??= "unresolved";
    thread.comments = [...thread.comments, new Note(reply.text, thread, author)];
  };

  const setState = (/** @type {vscode.CommentThread} */ thread, /** @type {boolean} */ resolved) => {
    thread.state = resolved ? vscode.CommentThreadState.Resolved : vscode.CommentThreadState.Unresolved;
    thread.contextValue = resolved ? "resolved" : "unresolved";
    thread.collapsibleState = resolved
      ? vscode.CommentThreadCollapsibleState.Collapsed
      : vscode.CommentThreadCollapsibleState.Expanded;
  };

  context.subscriptions.push(
    controller,
    vscode.commands.registerCommand("devHubReview.createNote", add),
    vscode.commands.registerCommand("devHubReview.replyNote", add),
    vscode.commands.registerCommand("devHubReview.editNote", (/** @type {Note} */ note) =>
      update(note, n => { n.mode = vscode.CommentMode.Editing; })),
    vscode.commands.registerCommand("devHubReview.saveNote", (/** @type {Note} */ note) =>
      update(note, n => { n.savedBody = n.body; n.mode = vscode.CommentMode.Preview; })),
    vscode.commands.registerCommand("devHubReview.cancelSaveNote", (/** @type {Note} */ note) =>
      update(note, n => { n.body = n.savedBody; n.mode = vscode.CommentMode.Preview; })),
    vscode.commands.registerCommand("devHubReview.deleteNote", (/** @type {Note} */ note) => {
      const thread = note.parent;
      thread.comments = thread.comments.filter(c => /** @type {Note} */ (c).id !== note.id);
      if (thread.comments.length === 0) thread.dispose();
    }),
    vscode.commands.registerCommand("devHubReview.deleteThread", (/** @type {vscode.CommentThread} */ t) => t.dispose()),
    vscode.commands.registerCommand("devHubReview.resolveThread", (/** @type {vscode.CommentThread} */ t) => setState(t, true)),
    vscode.commands.registerCommand("devHubReview.reopenThread", (/** @type {vscode.CommentThread} */ t) => setState(t, false)),
  );
}

// --- picking a branch, and opening one from a vscode:// link

async function pickBranch(/** @type {BranchTree} */ tree) {
  const names = (await git("for-each-ref", "--format=%(refname:short)", "refs/heads")).split("\n").filter(Boolean);
  const counted = await Promise.all(
    names.map(async name => {
      const ahead = await git("rev-list", "--count", `${base()}..${name}`).catch(() => "0");
      return { label: name, description: `${ahead.trim()} commits`, ahead: Number(ahead) };
    }),
  );
  const picked = await vscode.window.showQuickPick(
    counted.filter(b => b.ahead > 0),
    { placeHolder: `Local branches with commits that ${base()} doesn't have` },
  );
  if (picked) await tree.setBranch(picked.label);
}

/** Show the branch, and open its first changed file, so the review starts straight away. */
async function openBranch(/** @type {BranchTree} */ tree, /** @type {string} */ branch) {
  try {
    await git("rev-parse", "--verify", "--quiet", `refs/heads/${branch}`);
  } catch {
    vscode.window.showErrorMessage(`There's no local branch called ${branch} in ${repo()}.`);
    return;
  }
  await tree.setBranch(branch);
  await vscode.commands.executeCommand("devHubReview.commits.focus");
  // The roots are All changes, then the commits. A commit's children are its message, then files.
  const firstCommit = (await tree.getChildren(undefined))[1];
  const [message, firstFile] = (await firstCommit?.children?.()) ?? [];
  const command = (firstFile ?? message)?.item.command;
  if (command) await vscode.commands.executeCommand(command.command, ...(command.arguments ?? []));
}

async function activate(/** @type {vscode.ExtensionContext} */ context) {
  const tree = new BranchTree(context.workspaceState);
  const view = vscode.window.createTreeView("devHubReview.commits", { treeDataProvider: tree });
  const describe = () => { view.description = tree.branch; };
  describe();
  tree.onDidChangeTreeData(describe);

  const author = (await git("config", "user.name").catch(() => os.userInfo().username)).trim();
  registerComments(context, author);

  context.subscriptions.push(
    view,
    vscode.workspace.registerTextDocumentContentProvider(FILE_SCHEME, contents),
    vscode.workspace.registerTextDocumentContentProvider(MESSAGE_SCHEME, contents),
    vscode.commands.registerCommand("devHubReview.pickBranch", () => pickBranch(tree)),
    vscode.commands.registerCommand("devHubReview.refresh", () => tree.refresh()),
    // vscode://local.dev-hub-review-poc/open?branch=<branch> brings the window up on that branch.
    vscode.window.registerUriHandler({
      handleUri(uri) {
        const branch = new URLSearchParams(uri.query).get("branch");
        if (uri.path === "/open" && branch) return openBranch(tree, branch);
      },
    }),
  );
}

module.exports = { activate, deactivate() {} };
