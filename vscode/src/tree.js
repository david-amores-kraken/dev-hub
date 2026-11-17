// @ts-check
// The side view: the feature, its reviews, then its changes, as the hub's Features and Diffs
// sections show them.
"use strict";

const vscode = require("vscode");
const path = require("node:path");
const { diffCommand, uriOf } = require("./documents");
const model = require("./model");

/** @typedef {{ item: vscode.TreeItem, children?: () => Node[] }} Node */
/** @typedef {import("./model").Branch} Branch */
/** @typedef {import("./model").Comment} Comment */

const STATUS_ICONS = { added: "diff-added", deleted: "diff-removed", renamed: "diff-renamed", modified: "diff-modified" };

/** @returns {Node} */
function leaf(/** @type {string} */ label, /** @type {string} */ icon, /** @type {Partial<vscode.TreeItem>} */ more = {}) {
  const item = new vscode.TreeItem(label);
  item.iconPath = new vscode.ThemeIcon(icon);
  return { item: Object.assign(item, more) };
}

/** @returns {Node} */
function group(
  /** @type {string} */ label,
  /** @type {string} */ icon,
  /** @type {() => Node[]} */ children,
  /** @type {Partial<vscode.TreeItem>} */ more = {},
  expanded = true,
) {
  const state = expanded ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed;
  const node = leaf(label, icon, { collapsibleState: state, ...more });
  return { ...node, children };
}

const command = (/** @type {string} */ name, /** @type {string} */ title, /** @type {unknown[]} */ args = []) => ({ command: name, title, arguments: args });
const openInHub = (/** @type {string} */ url) => command("vscode.open", "Open in the dev hub", [vscode.Uri.parse(url)]);
const badge = (/** @type {number | undefined} */ n) => (n ? `${n} open` : undefined);

class Tree {
  constructor(/** @type {import("./review").Review} */ review) {
    this.review = review;
    this.changed = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.changed.event;
    review.onDidChange(() => this.changed.fire(undefined));
  }

  getTreeItem(/** @type {Node} */ node) {
    return node.item;
  }

  /** @returns {Promise<Node[]>} */
  async getChildren(/** @type {Node | undefined} */ parent) {
    if (parent) return parent.children ? parent.children() : [];
    const { branch, data, error } = this.review;
    if (!branch) return [leaf("Pick a branch to review…", "git-branch", { command: command("devHubReview.pickBranch", "Pick") })];
    if (!data && !error) await this.review.loading;
    const nodes = [];
    if (this.review.error) {
      nodes.push(leaf(this.review.error, "error", { tooltip: this.review.error, command: command("devHubReview.refresh", "Try again") }));
    }
    const current = this.review.data;
    if (current) nodes.push(this.feature(current), this.reviews(current), this.changes(current));
    return nodes;
  }

  feature(/** @type {Branch} */ data) {
    const hub = this.review.hub;
    return group(model.title(data), "package", () => {
      const parts = (data.feature?.parts ?? []).map(part =>
        leaf(part.label, { plan: "book", report: "output", e2e: "beaker" }[part.key] ?? "file", {
          command: command("devHubReview.openPage", "Open", [part]),
        }),
      );
      const description = leaf("PR description", "git-pull-request", {
        description: data.description.title || "none yet",
        command: command("vscode.open", "Open", [uriOf(data, { kind: "description" }), { preview: true }]),
      });
      const counts = model.openCounts(data);
      const where = data.feature ? hub.link(data.feature.url) : hub.link(data.urls.overview);
      const inHub = leaf("Open in the dev hub", "link-external", {
        description: badge(counts.overview),
        tooltip: "The hub's Overview lists comments that can't be shown on the code.",
        command: openInHub(where),
      });
      return [...parts, description, inHub];
    }, { id: "feature", tooltip: data.branch });
  }

  reviews(/** @type {Branch} */ data) {
    const groups = model.reviewGroups(data);
    const open = model.ownEntries(data.comments).filter(model.isOpen).length;
    return group("Reviews", "comment-discussion", () => {
      if (!groups.length) return [leaf("No reviews or comments yet", "info")];
      return groups.map(g => {
        const count = g.comments.filter(model.isOpen).length;
        const item = new vscode.TreeItem(
          g.label,
          g.comments.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None,
        );
        item.id = `reviews/${g.key}`;
        item.description = g.comments.length ? `${count} open of ${g.comments.length}` : g.review?.verdict;
        if (g.review) item.tooltip = new vscode.MarkdownString(`**${g.review.verdict ?? ""}**\n\n${g.review.summary ?? ""}`);
        return { item, children: () => g.comments.map(c => this.comment(c)) };
      });
    }, { id: "reviews", description: badge(open) ?? "none open" });
  }

  comment(/** @type {Comment} */ c) {
    const icon = !c.placed ? "warning" : c.status === "resolved" ? "pass" : c.triage === "dismiss" ? "circle-slash" : "comment-unresolved";
    const state = [
      c.severity,
      c.triage === "address" ? "to address" : c.triage === "dismiss" ? "dismissed" : undefined,
      c.status === "resolved" ? "resolved" : undefined,
      c.placed ? undefined : "couldn't place",
    ];
    return leaf([c.finding_id, c.text.split("\n")[0]].filter(Boolean).join("  "), icon, {
      description: state.filter(Boolean).join(" · "),
      tooltip: new vscode.MarkdownString(c.text),
      command: command("devHubReview.showComment", "Show", [c]),
    });
  }

  changes(/** @type {Branch} */ data) {
    const counts = model.openCounts(data);
    const files = (/** @type {string} */ page) =>
      (data.files[page] ?? []).map(file =>
        leaf(path.basename(file.path), STATUS_ICONS[/** @type {keyof STATUS_ICONS} */ (file.status)] ?? "diff-modified", {
          description: `${path.dirname(file.path)} · ${file.status}`,
          tooltip: file.status === "renamed" ? `${file.old_path} → ${file.path}` : file.path,
          command: diffCommand(data, page, file),
        }),
      );
    const all = group("All changes", "files", () => files(model.CHANGES), { id: "changes/all", description: badge(counts.changes) }, false);
    const commits = data.commits.map((c, i) =>
      group(`${i + 1}  ${c.subject}`, "git-commit", () => [
        leaf("Commit message", "note", {
          command: command("vscode.open", "Open", [uriOf(data, { kind: "message", sha: c.sha }), { preview: true }]),
        }),
        ...files(c.sha),
      ], { id: `changes/${c.sha}`, description: [c.sha.slice(0, 7), badge(counts[c.sha])].filter(Boolean).join(" · "), tooltip: `${c.subject}\n${c.author}, ${c.date}` }, false),
    );
    return group("Changes", "git-compare", () => [all, ...commits], { id: "changes", description: `${data.commits.length} commits` });
  }
}

module.exports = { Tree };
