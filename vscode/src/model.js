// @ts-check
// What the extension works out from the hub's /api/branch answer. Nothing here touches VS Code,
// so it can be tested with plain Node.
"use strict";

/**
 * @typedef {{ sha: string, subject: string, message: string, author: string, date: string }} Commit
 * @typedef {{ old: number[], new: number[] }} Lines
 * @typedef {{ path: string, old_path: string, status: string, lines: Lines }} File
 * @typedef {{ key: string, label: string, url: string }} Part
 * @typedef {{ slug: string, title: string, url: string, parts: Part[], content_policy: string }} Feature
 * @typedef {{ id: string, author: string, text: string, created: string, commit?: string | null }} Reply
 * @typedef {{
 *   kind: "line" | "message" | "pr_body", commit: string | null, start: number, end: number,
 *   quote: string, file?: string, side?: "old" | "new",
 * }} Target
 * @typedef {{
 *   id: string, status: "open" | "resolved", text: string, created: string, target: Target,
 *   page: string, placed: boolean, persona?: string, author?: string, finding_id?: string,
 *   severity?: string, triage?: "address" | "dismiss", replies?: Reply[],
 *   mirror?: { label: string, url: string },
 * }} Comment
 * @typedef {{
 *   id: string, persona: string, name?: string, emoji?: string, verdict?: string,
 *   summary?: string, latest: boolean, findings?: string[],
 * }} Review
 * @typedef {{
 *   branch: string, urls: { overview: string, comments: string }, feature: Feature | null,
 *   description: { title: string, body: string }, commits: Commit[],
 *   files: Record<string, File[]>, reviews: Review[], comments: Comment[],
 * }} Branch
 *
 * A document the extension shows. `page` is "changes" (All changes) or a commit's sha.
 * @typedef {{ kind: "file", page: string, path: string, side: "old" | "new" }
 *   | { kind: "message", sha: string }
 *   | { kind: "description" }} Doc
 */

const ME = "me";
const CHANGES = "changes";

/** "All changes", or "commit 3". */
function pageName(/** @type {Branch} */ data, /** @type {string} */ page) {
  if (page === CHANGES) return "All changes";
  const number = data.commits.findIndex(c => c.sha === page) + 1;
  return number ? `commit ${number}` : "a commit that has gone";
}

/** A comment's thread is one per page it is shown on. */
const threadKey = (/** @type {Comment} */ c) => `${c.id}@${c.page}`;

/** Each comment once, on the page it was made on (not where it is mirrored). */
const ownEntries = (/** @type {Comment[]} */ comments) => comments.filter(c => !c.mirror);

/** Open and not dismissed: still something to do, as the hub counts it. */
const isOpen = (/** @type {Comment} */ c) => c.status === "open" && c.triage !== "dismiss";

/** How many open comments each page shows, as the hub's badges count them. */
function openCounts(/** @type {Branch} */ data) {
  /** @type {Record<string, number>} */
  const counts = {};
  for (const c of data.comments) if (isOpen(c)) counts[c.page] = (counts[c.page] ?? 0) + 1;
  return counts;
}

/** The document a comment is shown in. */
function docOf(/** @type {Comment} */ c) {
  const t = c.target;
  if (t.kind === "pr_body") return /** @type {Doc} */ ({ kind: "description" });
  if (t.kind === "message") return /** @type {Doc} */ ({ kind: "message", sha: c.page });
  return /** @type {Doc} */ ({ kind: "file", page: c.page, path: t.file ?? "", side: t.side ?? "new" });
}

/** Where a new comment goes, as the hub's POST /comments wants it. Lines are numbered from 1. */
function targetFor(/** @type {Doc} */ doc, /** @type {number} */ start, /** @type {number} */ end, /** @type {string[]} */ lines) {
  const quote = lines.slice(start - 1, end).join("\n");
  if (doc.kind === "description") return { kind: "pr_body", commit: null, start, end, quote };
  if (doc.kind === "message") return { kind: "message", commit: doc.sha, start, end, quote };
  return {
    kind: "line",
    commit: doc.page === CHANGES ? null : doc.page,
    file: doc.path,
    side: doc.side,
    start,
    end,
    quote,
  };
}

/** Line numbers as runs of consecutive lines, [first, last], so each hunk is one range. */
function runs(/** @type {number[]} */ lines) {
  /** @type {[number, number][]} */
  const found = [];
  for (const line of [...lines].sort((a, b) => a - b)) {
    const last = found.at(-1);
    if (last && line === last[1] + 1) last[1] = line;
    else if (!last || line > last[1]) found.push([line, line]);
  }
  return found;
}

/** The lines of a document that can take a comment, as the hub's pages offer them. A commit
 * message and the PR description can take one on any line, so they give undefined. */
function commentable(/** @type {Branch} */ data, /** @type {Doc} */ doc) {
  if (doc.kind !== "file") return undefined;
  const file = (data.files[doc.page] ?? []).find(f => f.path === doc.path);
  return runs(file ? file.lines[doc.side] : []);
}

/** What is said about a thread in its header: the finding, its triage, and where it was made. */
function threadLabel(/** @type {Branch} */ data, /** @type {Comment} */ c) {
  const triage = c.triage === "address" ? "to address" : c.triage === "dismiss" ? "dismissed" : undefined;
  const from = c.mirror ? `made on ${c.mirror.label}` : undefined;
  const finding = c.finding_id ? [c.finding_id, c.severity].filter(Boolean).join(" · ") : undefined;
  return [finding, triage, from].filter(Boolean).join(" · ") || undefined;
}

/**
 * @typedef {{ key: string, label: string, review?: Review, comments: Comment[] }} Group
 * Comments by who wrote them: each persona with a review (latest first, as the hub lists them),
 * any other persona with comments, then mine.
 * @returns {Group[]}
 */
function reviewGroups(/** @type {Branch} */ data) {
  /** @type {Map<string, Group>} */
  const groups = new Map();
  for (const review of data.reviews) {
    if (!review.latest) continue;
    const label = [review.emoji, review.name ?? review.persona].filter(Boolean).join(" ");
    groups.set(review.persona, { key: review.persona, label, review, comments: [] });
  }
  for (const c of ownEntries(data.comments)) {
    const key = c.persona ?? ME;
    if (!groups.has(key)) groups.set(key, { key, label: c.author ?? key, comments: [] });
    groups.get(key)?.comments.push(c);
  }
  const mine = groups.get(ME);
  groups.delete(ME);
  if (mine) groups.set(ME, { ...mine, label: "Your comments" });
  return [...groups.values()];
}

/** The feature's name: its plan's title, else the PR title, else the branch. */
const title = (/** @type {Branch} */ data) => data.feature?.title || data.description.title || data.branch;

module.exports = {
  CHANGES,
  ME,
  commentable,
  docOf,
  isOpen,
  openCounts,
  ownEntries,
  pageName,
  reviewGroups,
  runs,
  targetFor,
  threadKey,
  threadLabel,
  title,
};
