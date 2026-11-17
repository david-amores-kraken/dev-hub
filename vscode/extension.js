// @ts-check
// A proof of concept: review a feature in VS Code. The view shows what the hub has for the branch
// (its plan, report, e2e results and PR description), the comments on it grouped by who wrote
// them, then its commits. Files open in VS Code's own diff editor, and lines take comments with
// VS Code's Comments API.
//
// It reads the hub's folders and the repo directly, and never writes to them. The comments the
// hub has saved are loaded into threads, but anything done to them here (replies, resolving,
// triage, new comments) is kept in memory, so it is gone when the window reloads.
"use strict";

const vscode = require("vscode");
const { execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

// devhub:/<path in repo>?<commit>     is that file at that commit. An empty commit means the file
//                                     doesn't exist on that side of the diff (added or deleted).
// devhub-msg:/<name>?<commit>         is the commit's message, so it can be commented on too.
// devhub-pr:/PR description?<branch>  is the PR description the hub keeps for the branch.
const FILE_SCHEME = "devhub";
const MESSAGE_SCHEME = "devhub-msg";
const PR_SCHEME = "devhub-pr";
const BRANCH_KEY = "devHubReview.branch";

// The parts of a feature that are HTML pages, each saved as <folder>/<slug>.html by a skill.
const PARTS = [
  { label: "Plan", setting: "plans", fallback: "~/Plans", icon: "book" },
  { label: "Report", setting: "reports", fallback: "~/Reports", icon: "output" },
  { label: "E2E results", setting: "e2e", fallback: "~/E2E", icon: "beaker" },
];

function setting(name, fallback) {
  return vscode.workspace.getConfiguration("devHubReview").get(name, fallback);
}

function folder(name, fallback) {
  return setting(name, fallback).replace(/^~(?=$|\/)/, os.homedir());
}

const repo = () => folder("repo", "~/Code/kraken-core");
const base = () => setting("base", "origin/master");

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
const messageUri = (/** @type {Commit} */ c) =>
  vscode.Uri.from({ scheme: MESSAGE_SCHEME, path: `/Commit ${c.number} message`, query: c.sha });
const prUri = (/** @type {string} */ branch) =>
  vscode.Uri.from({ scheme: PR_SCHEME, path: "/PR description", query: branch });

// --- what the hub has saved for a branch

/** The hub's review file: `quote(branch, safe="")` in Python, which also encodes !'()*. */
function reviewFile(/** @type {string} */ branch) {
  const name = encodeURIComponent(branch).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
  return path.join(folder("reviews", "~/Reviews"), `${name}.json`);
}

async function readJson(/** @type {string} */ file) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return {};
  }
}

async function exists(/** @type {string} */ file) {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

/** The page's first <h1> or <title>, as the hub reads a plan's title. */
async function pageTitle(/** @type {string} */ file) {
  const match = (await fs.readFile(file, "utf8")).match(/<(?:h1|title)[^>]*>([\s\S]*?)<\/(?:h1|title)>/i);
  const text = match ? match[1].replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").trim() : "";
  return text.replace(/^Report:\s*/, "") || undefined;
}

/** @typedef {{ sha: string, subject: string, number: number }} Commit */
/** @typedef {{ label: string, icon: string, file: string }} Part */
/**
 * @typedef {{
 *   branch: string, slug: string, title: string, tip: string, mergeBase: string,
 *   commits: Commit[], parts: Part[], pr: { title?: string, body?: string },
 *   comments: any[], reviews: any[],
 * }} Branch
 */

/** @returns {Promise<Branch>} */
async function loadBranch(/** @type {string} */ branch) {
  const slug = branch.replaceAll("/", "-");
  const [tip, mergeBase, log, saved, parts] = await Promise.all([
    git("rev-parse", branch),
    git("merge-base", base(), branch),
    git("log", "--reverse", "--format=%H%x1f%s", `${base()}..${branch}`),
    readJson(reviewFile(branch)),
    Promise.all(
      PARTS.map(async part => {
        const file = path.join(folder(part.setting, part.fallback), `${slug}.html`);
        return (await exists(file)) ? { label: part.label, icon: part.icon, file } : undefined;
      }),
    ),
  ]);
  const found = /** @type {Part[]} */ (parts.filter(Boolean));
  const pr = saved.pr ?? {};
  return {
    branch,
    slug,
    title: (found[0] && (await pageTitle(found[0].file))) || pr.title || slug,
    tip: tip.trim(),
    mergeBase: mergeBase.trim(),
    commits: log.split("\n").filter(Boolean).map((line, i) => {
      const [sha, subject] = line.split("\x1f");
      return { sha, subject, number: i + 1 };
    }),
    parts: found,
    pr,
    comments: saved.comments ?? [],
    reviews: saved.reviews ?? [],
  };
}

// --- what the editors show

const contents = {
  async provideTextDocumentContent(/** @type {vscode.Uri} */ uri) {
    if (uri.scheme === PR_SCHEME) {
      const pr = (await readJson(reviewFile(uri.query))).pr ?? {};
      return String(pr.body ?? "").replace(/\r\n/g, "\n");
    }
    if (!uri.query) return "";
    if (uri.scheme === MESSAGE_SCHEME) return git("log", "-1", "--format=%B", uri.query);
    try {
      return await git("show", `${uri.query}:${uri.path.slice(1)}`);
    } catch {
      return "";
    }
  },
};

/** @type {Map<string, vscode.WebviewPanel>} */
const pages = new Map();

/** Show a plan, report or e2e page. They are documents a model wrote, so, as in the hub, they get
 * no scripts and no network: only inline styles and data: images and fonts. */
async function openPage(/** @type {Part} */ part, /** @type {string} */ title) {
  const open = pages.get(part.file);
  if (open) return open.reveal();
  const panel = vscode.window.createWebviewPanel(
    "devHubReview.page",
    `${part.label}: ${title}`,
    vscode.ViewColumn.Active,
    { enableScripts: false, enableFindWidget: true, localResourceRoots: [] },
  );
  const csp =
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; ` +
    `style-src 'unsafe-inline'; img-src data:; font-src data:">`;
  const html = await fs.readFile(part.file, "utf8");
  panel.webview.html = /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, m => m + csp) : csp + html;
  pages.set(part.file, panel);
  panel.onDidDispose(() => pages.delete(part.file));
}

// --- the tree: the feature, its comments, then its changes

/** @typedef {{ item: vscode.TreeItem, children?: () => Promise<Node[]> | Node[] }} Node */

/** @returns {Node} */
const node = (/** @type {string} */ label, /** @type {string} */ icon, more = {}) => {
  const item = new vscode.TreeItem(label);
  item.iconPath = new vscode.ThemeIcon(icon);
  return { item: Object.assign(item, more) };
};

/** @returns {Node} */
const group = (/** @type {string} */ label, /** @type {string} */ icon, /** @type {() => Node[]} */ children, more = {}) => ({
  ...node(label, icon, { collapsibleState: vscode.TreeItemCollapsibleState.Expanded, ...more }),
  children,
});

class BranchTree {
  constructor(/** @type {vscode.Memento} */ state, /** @type {HubComments} */ hub) {
    this.state = state;
    this.hub = hub;
    /** @type {Branch | undefined} */
    this.data = undefined;
    /** @type {string | undefined} */
    this.error = undefined;
    this.changed = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.changed.event;
    this.loading = this.reload();
  }

  /** @returns {string | undefined} */
  get branch() {
    return this.state.get(BRANCH_KEY);
  }

  async setBranch(/** @type {string} */ branch) {
    await this.state.update(BRANCH_KEY, branch);
    await this.refresh();
  }

  /** Read the branch and the hub's files again. */
  async refresh() {
    this.loading = this.reload();
    this.changed.fire(undefined);
    await this.loading;
  }

  /** Draw the tree again, after a comment changed here. */
  redraw() {
    this.changed.fire(undefined);
  }

  async reload() {
    const branch = this.branch;
    this.data = this.error = undefined;
    if (!branch) return;
    try {
      this.data = await loadBranch(branch);
      await this.hub.load(this.data);
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    }
  }

  getTreeItem(/** @type {Node} */ node) {
    return node.item;
  }

  /** @returns {Promise<Node[]>} */
  async getChildren(/** @type {Node | undefined} */ parent) {
    if (parent) return parent.children ? parent.children() : [];
    if (!this.branch) {
      return [node("Pick a branch to review…", "git-branch", { command: { command: "devHubReview.pickBranch", title: "Pick" } })];
    }
    await this.loading;
    if (!this.data) return [node(`Couldn't read ${this.branch}: ${this.error}`, "error")];
    return [featureNode(this.data), this.hub.reviewsNode(this.data), changesNode(this.data)];
  }
}

function featureNode(/** @type {Branch} */ data) {
  const children = data.parts.map(part =>
    node(part.label, part.icon, {
      tooltip: part.file,
      command: { command: "devHubReview.openPage", title: "Open", arguments: [part, data.title] },
    }),
  );
  if (data.pr.body) {
    const uri = prUri(data.branch);
    children.push(
      node("PR description", "git-pull-request", {
        description: data.pr.title,
        command: { command: "vscode.open", title: "Open", arguments: [uri, { preview: true }] },
      }),
    );
  }
  if (children.length === 0) children.push(node("No plan, report or e2e results yet", "info"));
  return group(data.title, "package", () => children, { tooltip: data.slug });
}

function changesNode(/** @type {Branch} */ data) {
  const all = {
    item: Object.assign(new vscode.TreeItem("All changes", vscode.TreeItemCollapsibleState.Collapsed), {
      iconPath: new vscode.ThemeIcon("files"),
    }),
    children: () => files(data.mergeBase, data.tip, "all changes"),
  };
  return group("Changes", "git-compare", () => [all, ...data.commits.map(commitNode)], {
    description: `${data.commits.length} commits`,
  });
}

/** @returns {Node} */
function commitNode(/** @type {Commit} */ commit) {
  const item = new vscode.TreeItem(`${commit.number}  ${commit.subject}`, vscode.TreeItemCollapsibleState.Collapsed);
  item.description = commit.sha.slice(0, 10);
  item.iconPath = new vscode.ThemeIcon("git-commit");
  item.tooltip = commit.subject;
  return {
    item,
    children: async () => {
      const uri = messageUri(commit);
      const message = node("Commit message", "note", {
        command: { command: "vscode.open", title: "Open", arguments: [uri, { preview: true }] },
      });
      return [message, ...(await files(`${commit.sha}^`, commit.sha, `commit ${commit.number}`))];
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
      return node(path.basename(newPath), icon, {
        description: `${path.dirname(newPath)} · ${label}`,
        tooltip: code[0] === "R" ? `${oldPath} → ${newPath}` : newPath,
        command: {
          command: "vscode.diff",
          title: "Open diff",
          arguments: [
            fileUri(oldPath, code[0] === "A" ? "" : left),
            fileUri(newPath, code[0] === "D" ? "" : right),
            `${path.basename(newPath)} (${where})`,
            { preview: true },
          ],
        },
      });
    });
}

// --- comments

let nextId = 1;

class Note {
  constructor(
    /** @type {string} */ body,
    /** @type {vscode.CommentThread} */ thread,
    /** @type {string} */ author,
    /** @type {Date} */ timestamp = new Date(),
  ) {
    this.id = nextId++;
    this.body = new vscode.MarkdownString(body);
    this.savedBody = this.body;
    this.mode = vscode.CommentMode.Preview;
    this.author = { name: author };
    this.timestamp = timestamp;
    this.parent = thread;
  }
}

/**
 * How a thread looks. `finding` is a persona's finding, which can be triaged, `label` its ID and
 * severity, and `moved` says its lines have changed since it was made.
 * @typedef {{ resolved: boolean, finding?: boolean, triage?: string, label?: string, moved?: boolean }} Look
 */
/** @type {WeakMap<vscode.CommentThread, Look>} */
const looks = new WeakMap();
const TRIAGE = { address: "to address", dismiss: "dismissed" };

/** Apply the thread's look. Its contextValue is "open" or "done", then " finding" for a finding,
 * which is what package.json's menus test with =~. */
function paint(/** @type {vscode.CommentThread} */ thread) {
  const look = looks.get(thread) ?? { resolved: false };
  thread.state = look.resolved ? vscode.CommentThreadState.Resolved : vscode.CommentThreadState.Unresolved;
  thread.contextValue = `${look.resolved ? "done" : "open"}${look.finding ? " finding" : ""}`;
  thread.label =
    [look.label, TRIAGE[look.triage ?? ""], look.moved ? "lines changed since" : undefined].filter(Boolean).join(" · ") ||
    undefined;
  thread.collapsibleState =
    look.resolved || look.triage === "dismiss"
      ? vscode.CommentThreadCollapsibleState.Collapsed
      : vscode.CommentThreadCollapsibleState.Expanded;
}

/** Re-assign the thread's comments, which is how VS Code is told to redraw them. */
function update(/** @type {Note} */ note, /** @type {(n: Note) => void} */ change) {
  note.parent.comments = note.parent.comments.map(c => {
    if (/** @type {Note} */ (c).id === note.id) change(/** @type {Note} */ (c));
    return c;
  });
}

/** @typedef {(selection: vscode.Range) => [string, ...any[]]} Opener */

/**
 * Where a hub comment goes: the document it is on, and how to open that document at its lines.
 * Undefined when its commit is no longer on the branch, which the hub calls "couldn't place".
 * @returns {{ uri: vscode.Uri, open: Opener } | undefined}
 */
function placeOf(/** @type {Branch} */ data, /** @type {any} */ target) {
  const view = (/** @type {vscode.Uri} */ uri) => ({
    uri,
    /** @type {Opener} */ open: selection => ["vscode.open", uri, { preview: true, selection }],
  });
  if (target.kind === "pr_body") return view(prUri(data.branch));
  const commit = data.commits.find(c => c.sha === target.commit);
  if (target.commit && !commit) return undefined;
  if (target.kind === "message") return commit && view(messageUri(commit));
  const [left, right, where] = commit
    ? [`${commit.sha}^`, commit.sha, `commit ${commit.number}`]
    : [data.mergeBase, data.tip, "all changes"];
  return {
    uri: fileUri(target.file, target.side === "old" ? left : right),
    open: selection => [
      "vscode.diff",
      fileUri(target.file, left),
      fileUri(target.file, right),
      `${path.basename(target.file)} (${where})`,
      { preview: true, selection },
    ],
  };
}

/** The comment's lines now. If its quote isn't at its lines any more, the first place the quote
 * is, as the hub moves a comment. If the quote is nowhere, its old lines, marked as moved. */
function anchor(/** @type {string[]} */ lines, /** @type {any} */ target) {
  const quote = String(target.quote ?? "").replace(/\r/g, "").replace(/\n$/, "").split("\n");
  const at = (/** @type {number} */ i) => quote.every((text, k) => lines[i + k]?.replace(/\r$/, "") === text);
  let start = target.start - 1;
  let moved = false;
  if (target.quote && !at(start)) {
    const found = lines.findIndex((_, i) => at(i));
    if (found >= 0) start = found;
    else moved = true;
  }
  return { range: new vscode.Range(start, 0, start + (target.end - target.start), 0), moved };
}

/** The comments the hub saved for the branch, as threads in the editors and as the Reviews node. */
class HubComments {
  constructor(/** @type {vscode.CommentController} */ controller, /** @type {string} */ me) {
    this.controller = controller;
    this.me = me;
    /** @type {Map<string, { thread: vscode.CommentThread, open: Opener }>} */
    this.placed = new Map();
    this.onChange = () => {};
  }

  /** Replace the hub's threads with the branch's. Comments made here since are left alone. */
  async load(/** @type {Branch} */ data) {
    for (const { thread } of this.placed.values()) thread.dispose();
    this.placed.clear();
    /** @type {Map<string, Promise<string[]>>} */
    const texts = new Map();
    const linesOf = (/** @type {vscode.Uri} */ uri) => {
      const key = uri.toString();
      if (!texts.has(key)) texts.set(key, contents.provideTextDocumentContent(uri).then(t => t.split("\n")));
      return /** @type {Promise<string[]>} */ (texts.get(key));
    };
    const author = (/** @type {string | undefined} */ name) => (!name || name === "me" ? this.me : name);
    for (const comment of data.comments) {
      const place = placeOf(data, comment.target);
      if (!place) continue;
      const { range, moved } = anchor(await linesOf(place.uri), comment.target);
      const thread = this.controller.createCommentThread(place.uri, range, []);
      thread.canReply = true;
      thread.comments = [
        new Note(comment.text, thread, author(comment.author), new Date(comment.created)),
        ...(comment.replies ?? []).map(r => new Note(r.text, thread, author(r.author), new Date(r.created))),
      ];
      looks.set(thread, {
        resolved: comment.status === "resolved",
        finding: Boolean(comment.finding_id),
        triage: comment.triage,
        label: comment.finding_id && [comment.finding_id, comment.severity].filter(Boolean).join(" · "),
        moved,
      });
      paint(thread);
      this.placed.set(comment.id, { thread, open: place.open });
    }
  }

  /** The comment's look now, which may have changed here since the hub saved it. */
  lookOf(/** @type {any} */ comment) {
    const placed = this.placed.get(comment.id);
    return (placed && looks.get(placed.thread)) ?? { resolved: comment.status === "resolved", triage: comment.triage };
  }

  isOpen(/** @type {any} */ comment) {
    const look = this.lookOf(comment);
    return !look.resolved && look.triage !== "dismiss";
  }

  /** Comments grouped by who wrote them: each persona that reviewed, then mine. */
  reviewsNode(/** @type {Branch} */ data) {
    /** @type {Map<string, { label: string, review?: any, comments: any[] }>} */
    const groups = new Map();
    for (const review of data.reviews) {
      const known = groups.get(review.persona);
      if (known) known.review = review;
      else groups.set(review.persona, { label: `${review.emoji} ${review.name}`, review, comments: [] });
    }
    for (const comment of data.comments) {
      const key = comment.persona ?? "me";
      if (!groups.has(key)) groups.set(key, { label: key === "me" ? "💬 Your comments" : comment.author, comments: [] });
      groups.get(key)?.comments.push(comment);
    }
    const mine = groups.get("me");
    groups.delete("me");
    if (mine) groups.set("me", mine);

    const children = [...groups.values()].map(g => {
      const item = new vscode.TreeItem(
        g.label,
        g.comments.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None,
      );
      const open = g.comments.filter(c => this.isOpen(c)).length;
      item.description = g.comments.length ? `${open} open of ${g.comments.length}` : g.review?.verdict;
      if (g.review) item.tooltip = new vscode.MarkdownString(`**${g.review.verdict}**\n\n${g.review.summary ?? ""}`);
      return /** @type {Node} */ ({ item, children: () => g.comments.map(c => this.commentNode(c)) });
    });
    if (children.length === 0) children.push(node("No reviews or comments yet", "info"));
    const open = data.comments.filter(c => this.isOpen(c)).length;
    return group("Reviews", "comment-discussion", () => children, { description: `${open} open` });
  }

  commentNode(/** @type {any} */ comment) {
    const look = this.lookOf(comment);
    const placed = this.placed.has(comment.id);
    const icon = !placed
      ? "warning"
      : look.resolved
        ? "pass"
        : look.triage === "dismiss"
          ? "circle-slash"
          : "comment-unresolved";
    const firstLine = String(comment.text).split("\n")[0];
    return node([comment.finding_id, firstLine].filter(Boolean).join("  "), icon, {
      description: [
        comment.severity,
        TRIAGE[look.triage ?? ""],
        look.resolved ? "resolved" : undefined,
        placed ? undefined : "couldn't place",
      ]
        .filter(Boolean)
        .join(" · "),
      tooltip: new vscode.MarkdownString(comment.text),
      command: { command: "devHubReview.showComment", title: "Show", arguments: [comment] },
    });
  }

  /** Open the comment's diff at its lines, with its thread expanded. */
  async show(/** @type {any} */ comment) {
    const placed = this.placed.get(comment.id);
    if (!placed) {
      await vscode.window.showInformationMessage("This comment is on a commit that is no longer on the branch.", {
        modal: true,
        detail: comment.text,
      });
      return;
    }
    const [command, ...args] = placed.open(placed.thread.range ?? new vscode.Range(0, 0, 0, 0));
    await vscode.commands.executeCommand(command, ...args);
    placed.thread.collapsibleState = vscode.CommentThreadCollapsibleState.Expanded;
  }
}

function registerComments(/** @type {vscode.ExtensionContext} */ context, /** @type {HubComments} */ hub) {
  const controller = hub.controller;
  controller.options = { placeHolder: "Comment on this line, or on the lines you selected", prompt: "Add a comment" };
  // Every line of a diff, commit message or PR description can take a comment.
  controller.commentingRangeProvider = {
    provideCommentingRanges(document) {
      if (![FILE_SCHEME, MESSAGE_SCHEME, PR_SCHEME].includes(document.uri.scheme)) return [];
      return [new vscode.Range(0, 0, Math.max(document.lineCount - 1, 0), 0)];
    },
  };

  const add = (/** @type {vscode.CommentReply} */ reply) => {
    const thread = reply.thread;
    thread.canReply = true;
    if (!looks.has(thread)) {
      looks.set(thread, { resolved: false });
      paint(thread);
    }
    thread.comments = [...thread.comments, new Note(reply.text, thread, hub.me)];
  };

  const restyle = (/** @type {vscode.CommentThread} */ thread, /** @type {Partial<Look>} */ change) => {
    looks.set(thread, { resolved: false, ...looks.get(thread), ...change });
    paint(thread);
    hub.onChange();
  };
  // Marking a finding the way it is already marked takes the mark off, as in the hub.
  const triage = (/** @type {vscode.CommentThread} */ thread, /** @type {string} */ value) =>
    restyle(thread, { triage: looks.get(thread)?.triage === value ? undefined : value });

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
    vscode.commands.registerCommand("devHubReview.resolveThread", (/** @type {vscode.CommentThread} */ t) =>
      restyle(t, { resolved: true })),
    vscode.commands.registerCommand("devHubReview.reopenThread", (/** @type {vscode.CommentThread} */ t) =>
      restyle(t, { resolved: false })),
    vscode.commands.registerCommand("devHubReview.address", (/** @type {vscode.CommentThread} */ t) => triage(t, "address")),
    vscode.commands.registerCommand("devHubReview.dismiss", (/** @type {vscode.CommentThread} */ t) => triage(t, "dismiss")),
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
  const first = tree.data?.commits[0];
  if (!first) return;
  const [firstFile] = await files(`${first.sha}^`, first.sha, "commit 1");
  const command = firstFile?.item.command;
  if (command) await vscode.commands.executeCommand(command.command, ...(command.arguments ?? []));
}

async function activate(/** @type {vscode.ExtensionContext} */ context) {
  const me = (await git("config", "user.name").catch(() => os.userInfo().username)).trim();
  const hub = new HubComments(vscode.comments.createCommentController("devhub-review", "Dev Hub review"), me);
  registerComments(context, hub);

  const tree = new BranchTree(context.workspaceState, hub);
  hub.onChange = () => tree.redraw();
  const view = vscode.window.createTreeView("devHubReview.commits", { treeDataProvider: tree });
  const describe = () => { view.description = tree.branch; };
  describe();
  tree.onDidChangeTreeData(describe);

  context.subscriptions.push(
    view,
    vscode.workspace.registerTextDocumentContentProvider(FILE_SCHEME, contents),
    vscode.workspace.registerTextDocumentContentProvider(MESSAGE_SCHEME, contents),
    vscode.workspace.registerTextDocumentContentProvider(PR_SCHEME, contents),
    vscode.commands.registerCommand("devHubReview.pickBranch", () => pickBranch(tree)),
    vscode.commands.registerCommand("devHubReview.refresh", () => tree.refresh()),
    vscode.commands.registerCommand("devHubReview.openPage", openPage),
    vscode.commands.registerCommand("devHubReview.showComment", comment => hub.show(comment)),
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
