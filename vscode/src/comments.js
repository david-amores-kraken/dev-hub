// @ts-check
// The hub's comments as VS Code comment threads, on the pages the hub shows them on. Every change
// (a new comment, a reply, resolving, triage, an edit, a delete) is sent to the hub, and the
// threads are then redrawn from what it says, so the extension and the hub pages always agree.
"use strict";

const vscode = require("vscode");
const { SCHEME, diffCommand, docOf, uriOf } = require("./documents");
const model = require("./model");

/** @typedef {import("./model").Comment} Comment */
/** @typedef {import("./model").Reply} Reply */

/** One comment or reply in a thread. `contextValue` picks its buttons in package.json:
 * "mine" and "reply-mine" can be edited and deleted, "finding" only deleted, "reply" neither. */
class Note {
  constructor(
    /** @type {vscode.CommentThread} */ thread,
    /** @type {Comment} */ comment,
    /** @type {Reply | undefined} */ reply,
  ) {
    const mine = reply ? reply.author === model.ME : !comment.finding_id;
    this.thread = thread;
    this.comment = comment;
    this.reply = reply;
    this.text = reply ? reply.text : comment.text;
    this.body = /** @type {string | vscode.MarkdownString} */ (new vscode.MarkdownString(this.text));
    this.mode = vscode.CommentMode.Preview;
    const name = reply ? reply.author : comment.author;
    this.author = { name: mine ? "You" : name || "Someone" };
    this.timestamp = new Date(reply ? reply.created : comment.created);
    this.contextValue = reply ? (mine ? "reply-mine" : "reply") : mine ? "mine" : "finding";
  }
}

/** Re-assign a thread's comments, which is how VS Code is told to redraw them. */
function redraw(/** @type {Note} */ note, /** @type {(n: Note) => void} */ change) {
  note.thread.comments = note.thread.comments.map(c => {
    if (c === note) change(note);
    return c;
  });
}

class Threads {
  constructor(/** @type {import("./review").Review} */ review) {
    this.review = review;
    this.controller = vscode.comments.createCommentController("devhub-review", "Dev Hub review");
    this.controller.options = {
      placeHolder: "Comment on this line, or on the lines you selected",
      prompt: "Add a comment",
    };
    this.controller.commentingRangeProvider = {
      provideCommentingRanges: document => this.commentingRanges(document),
    };
    /** @type {Map<string, vscode.CommentThread>} */
    this.threads = new Map();
    /** @type {WeakMap<vscode.CommentThread, Comment>} */
    this.comments = new WeakMap();
    review.onDidChange(() => this.sync());
  }

  /** The lines a comment can go on, the same ones the hub's diff pages offer. */
  commentingRanges(/** @type {vscode.TextDocument} */ document) {
    const found = docOf(document.uri);
    const data = this.review.data;
    if (!found || !data || data.branch !== found.branch) return [];
    const runs = model.commentable(data, found.doc);
    if (!runs) return [new vscode.Range(0, 0, Math.max(document.lineCount - 1, 0), 0)];
    return runs.map(([first, last]) => new vscode.Range(first - 1, 0, last - 1, 0));
  }

  /** Make the threads match what the hub last said: add new ones, update the rest in place (so
   * an expanded thread stays expanded), and remove the ones that have gone. */
  sync() {
    const data = this.review.data;
    if (!data) {
      for (const thread of this.threads.values()) thread.dispose();
      this.threads.clear();
      return;
    }
    const seen = new Set();
    for (const comment of data.comments) {
      if (!comment.placed) continue; // the tree lists it, and offers it in the hub
      const key = model.threadKey(comment);
      const uri = uriOf(data, model.docOf(comment));
      const range = new vscode.Range(comment.target.start - 1, 0, comment.target.end - 1, 0);
      let thread = this.threads.get(key);
      if (thread && thread.uri.toString() !== uri.toString()) {
        thread.dispose();
        thread = undefined;
      }
      const wasOpen = thread && this.comments.get(thread) && model.isOpen(/** @type {Comment} */ (this.comments.get(thread)));
      if (!thread) {
        thread = this.controller.createCommentThread(uri, range, []);
        this.threads.set(key, thread);
      } else {
        thread.range = range;
      }
      const open = model.isOpen(comment);
      if (wasOpen === undefined || wasOpen !== open) {
        thread.collapsibleState = open
          ? vscode.CommentThreadCollapsibleState.Expanded
          : vscode.CommentThreadCollapsibleState.Collapsed;
      }
      this.comments.set(thread, comment);
      const t = /** @type {vscode.CommentThread} */ (thread);
      t.canReply = true;
      t.label = model.threadLabel(data, comment);
      t.state = comment.status === "resolved" ? vscode.CommentThreadState.Resolved : vscode.CommentThreadState.Unresolved;
      // "open" or "resolved", then " finding" for a finding: package.json's menus test this.
      t.contextValue = `${comment.status}${comment.finding_id ? " finding" : ""}`;
      t.comments = [new Note(t, comment, undefined), ...(comment.replies ?? []).map(r => new Note(t, comment, r))];
      seen.add(key);
    }
    for (const [key, thread] of this.threads) {
      if (!seen.has(key)) {
        thread.dispose();
        this.threads.delete(key);
      }
    }
  }

  /** Open a comment where it is, with its thread expanded. One that can't be placed is offered
   * in the hub, which lists it with its quote. */
  async show(/** @type {Comment} */ comment) {
    const data = this.review.data;
    if (!data) return;
    const thread = this.threads.get(model.threadKey(comment));
    if (!thread) {
      const choice = await vscode.window.showInformationMessage(
        "This comment's commit or lines have changed, so it can't be shown on the code.",
        { modal: true, detail: comment.text },
        "Open in the dev hub",
      );
      if (choice) await vscode.env.openExternal(vscode.Uri.parse(this.review.hub.link(data.urls.overview)));
      return;
    }
    const selection = thread.range ?? new vscode.Range(0, 0, 0, 0);
    const doc = model.docOf(comment);
    const file = doc.kind === "file" ? (data.files[doc.page] ?? []).find(f => f.path === doc.path) : undefined;
    if (doc.kind === "file" && file) {
      const command = diffCommand(data, doc.page, file, { selection });
      await vscode.commands.executeCommand(command.command, ...command.arguments);
    } else {
      await vscode.window.showTextDocument(thread.uri, { preview: true, selection });
    }
    thread.collapsibleState = vscode.CommentThreadCollapsibleState.Expanded;
  }

  /** The URL of a comment's routes in the hub. */
  url(/** @type {Comment} */ comment, /** @type {string} */ rest = "") {
    return `${this.review.data?.urls.comments}/${comment.id}${rest}`;
  }

  /** @returns {Comment | undefined} */
  commentOf(/** @type {vscode.CommentThread} */ thread) {
    return this.comments.get(thread);
  }

  register(/** @type {vscode.ExtensionContext} */ context) {
    const review = this.review;
    /** A thread made here has no comment until the hub has saved one. */
    const create = async (/** @type {vscode.CommentReply} */ reply) => {
      const comment = this.commentOf(reply.thread);
      if (comment) return review.change(this.url(comment, "/replies"), { text: reply.text });
      const found = docOf(reply.thread.uri);
      const data = review.data;
      if (!found || !data || !reply.thread.range) return;
      const lines = (await vscode.workspace.openTextDocument(reply.thread.uri)).getText().split("\n");
      const { start, end } = reply.thread.range;
      const target = model.targetFor(found.doc, start.line + 1, end.line + 1, lines);
      if (await review.change(data.urls.comments, { target, text: reply.text })) reply.thread.dispose();
    };
    const triage = (/** @type {vscode.CommentThread} */ thread, /** @type {"address" | "dismiss"} */ value) => {
      const comment = this.commentOf(thread);
      // Marking a finding the way it is already marked takes the mark off, as in the hub.
      if (comment) return review.change(this.url(comment), { triage: comment.triage === value ? null : value });
    };
    const status = (/** @type {vscode.CommentThread} */ thread, /** @type {"open" | "resolved"} */ value) => {
      const comment = this.commentOf(thread);
      if (comment) return review.change(this.url(comment), { status: value });
    };
    const noteUrl = (/** @type {Note} */ note) => this.url(note.comment, note.reply ? `/replies/${note.reply.id}` : "");

    context.subscriptions.push(
      this.controller,
      vscode.commands.registerCommand("devHubReview.createNote", create),
      vscode.commands.registerCommand("devHubReview.replyNote", create),
      vscode.commands.registerCommand("devHubReview.editNote", (/** @type {Note} */ note) =>
        redraw(note, n => { n.mode = vscode.CommentMode.Editing; })),
      vscode.commands.registerCommand("devHubReview.cancelSaveNote", (/** @type {Note} */ note) =>
        redraw(note, n => { n.body = new vscode.MarkdownString(n.text); n.mode = vscode.CommentMode.Preview; })),
      vscode.commands.registerCommand("devHubReview.saveNote", (/** @type {Note} */ note) => {
        const text = typeof note.body === "string" ? note.body : note.body.value;
        return review.change(noteUrl(note), { text });
      }),
      vscode.commands.registerCommand("devHubReview.deleteNote", async (/** @type {Note} */ note) => {
        const what = note.reply ? "reply" : "comment";
        const sure = await vscode.window.showWarningMessage(`Delete this ${what}? This can't be undone.`, { modal: true }, "Delete");
        if (sure) await review.change(`${noteUrl(note)}/delete`);
      }),
      vscode.commands.registerCommand("devHubReview.resolveThread", (/** @type {vscode.CommentThread} */ t) => status(t, "resolved")),
      vscode.commands.registerCommand("devHubReview.reopenThread", (/** @type {vscode.CommentThread} */ t) => status(t, "open")),
      vscode.commands.registerCommand("devHubReview.address", (/** @type {vscode.CommentThread} */ t) => triage(t, "address")),
      vscode.commands.registerCommand("devHubReview.dismiss", (/** @type {vscode.CommentThread} */ t) => triage(t, "dismiss")),
      vscode.commands.registerCommand("devHubReview.showComment", (/** @type {Comment} */ c) => this.show(c)),
    );
  }
}

module.exports = { SCHEME, Threads };
