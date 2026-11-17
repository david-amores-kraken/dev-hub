// @ts-check
// The read-only documents the diff editor and the comments are on: one side of a file on a page,
// a commit message, and the PR description. Their text comes from the hub.
//
//   devhub-review:/<path>?branch=…&kind=file&page=…&side=old|new
//   devhub-review:/Commit 3 message?branch=…&kind=message&sha=…
//   devhub-review:/PR description?branch=…&kind=description
"use strict";

const vscode = require("vscode");
const path = require("node:path");
const { pageName } = require("./model");

const SCHEME = "devhub-review";

/** @typedef {import("./model").Doc} Doc */

/** @returns {vscode.Uri} */
function uriOf(/** @type {import("./model").Branch} */ data, /** @type {Doc} */ doc) {
  const params = new URLSearchParams({ branch: data.branch, kind: doc.kind });
  let name;
  if (doc.kind === "file") {
    params.set("page", doc.page);
    params.set("side", doc.side);
    name = doc.path;
  } else if (doc.kind === "message") {
    params.set("sha", doc.sha);
    name = `${pageName(data, doc.sha).replace(/^c/, "C")} message`;
  } else {
    name = "PR description";
  }
  return vscode.Uri.from({ scheme: SCHEME, path: `/${name}`, query: params.toString() });
}

/** The branch and document a URI is about, or undefined if it isn't one of ours. */
function docOf(/** @type {vscode.Uri} */ uri) {
  if (uri.scheme !== SCHEME) return undefined;
  const params = new URLSearchParams(uri.query);
  const branch = params.get("branch") ?? "";
  const kind = params.get("kind");
  /** @type {Doc | undefined} */
  let doc;
  if (kind === "file") {
    const side = params.get("side") === "old" ? "old" : "new";
    doc = { kind, page: params.get("page") ?? "", path: uri.path.slice(1), side };
  } else if (kind === "message") {
    doc = { kind, sha: params.get("sha") ?? "" };
  } else if (kind === "description") {
    doc = { kind };
  }
  return doc && { branch, doc };
}

/** The diff of a file on a page, as the command that opens it. */
function diffCommand(/** @type {import("./model").Branch} */ data, /** @type {string} */ page, /** @type {import("./model").File} */ file, /** @type {vscode.TextDocumentShowOptions} */ options = {}) {
  /** @type {(side: "old" | "new") => vscode.Uri} */
  const side = side => uriOf(data, { kind: "file", page, path: file.path, side });
  return {
    command: "vscode.diff",
    title: "Open diff",
    arguments: [side("old"), side("new"), `${path.basename(file.path)} (${pageName(data, page)})`, { preview: true, ...options }],
  };
}

class Documents {
  constructor(/** @type {import("./review").Review} */ review) {
    this.review = review;
    this.changed = new vscode.EventEmitter();
    this.onDidChange = this.changed.event;
    // A commit never changes, but the PR description can, and "All changes" moves with the
    // branch. So those are read again after each reload.
    review.onDidChange(() => {
      for (const document of vscode.workspace.textDocuments) {
        const doc = docOf(document.uri)?.doc;
        if (doc?.kind === "description" || (doc?.kind === "file" && doc.page === "changes")) {
          this.changed.fire(document.uri);
        }
      }
    });
  }

  async provideTextDocumentContent(/** @type {vscode.Uri} */ uri) {
    const found = docOf(uri);
    if (!found) return "";
    const { branch, doc } = found;
    if (doc.kind === "file") {
      const answer = await this.review.hub.get("/api/file", { branch, page: doc.page, path: doc.path, side: doc.side });
      return answer.text ?? "";
    }
    if (this.review.branch !== branch || !this.review.data) await this.review.loading;
    const data = this.review.data?.branch === branch ? this.review.data : await this.review.hub.get("/api/branch", { branch });
    if (doc.kind === "message") return data.commits.find((/** @type {any} */ c) => c.sha === doc.sha)?.message ?? "";
    return data.description.body;
  }
}

module.exports = { Documents, SCHEME, diffCommand, docOf, uriOf };
