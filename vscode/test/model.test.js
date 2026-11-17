// @ts-check
"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const model = require("../src/model");

const ONE = "1".repeat(40);
const TWO = "2".repeat(40);

/** @returns {import("../src/model").Comment} */
function comment(/** @type {Partial<import("../src/model").Comment>} */ fields) {
  return {
    id: "c1",
    status: "open",
    text: "Why?",
    created: "2026-11-17T10:00:00+11:00",
    target: { kind: "line", commit: null, file: "a.py", side: "new", start: 2, end: 3, quote: "x\ny" },
    page: "changes",
    placed: true,
    ...fields,
  };
}

/** @returns {import("../src/model").Branch} */
function branch(/** @type {Partial<import("../src/model").Branch>} */ fields = {}) {
  return {
    branch: "team/thing",
    urls: { overview: "/diffs/team/thing", comments: "/diffs/team/thing/comments" },
    feature: null,
    description: { title: "", body: "" },
    commits: [
      { sha: ONE, subject: "One", message: "One", author: "A", date: "" },
      { sha: TWO, subject: "Two", message: "Two", author: "A", date: "" },
    ],
    files: {
      changes: [{ path: "a.py", old_path: "a.py", status: "modified", lines: { old: [4], new: [1, 2, 3, 7, 8] } }],
    },
    reviews: [],
    comments: [],
    ...fields,
  };
}

test("pages are named as the hub names them", () => {
  const data = branch();
  assert.equal(model.pageName(data, "changes"), "All changes");
  assert.equal(model.pageName(data, TWO), "commit 2");
});

test("only the lines the hub's diff page offers can take a comment, one range per run", () => {
  const data = branch();
  assert.deepEqual(model.commentable(data, { kind: "file", page: "changes", path: "a.py", side: "new" }), [[1, 3], [7, 8]]);
  assert.deepEqual(model.commentable(data, { kind: "file", page: "changes", path: "a.py", side: "old" }), [[4, 4]]);
  assert.deepEqual(model.commentable(data, { kind: "file", page: ONE, path: "a.py", side: "new" }), []);
  assert.equal(model.commentable(data, { kind: "description" }), undefined); // any line
});

test("a new comment's target is what the hub's pages send", () => {
  const lines = ["a", "b", "c"];
  assert.deepEqual(model.targetFor({ kind: "file", page: "changes", path: "a.py", side: "old" }, 2, 3, lines), {
    kind: "line", commit: null, file: "a.py", side: "old", start: 2, end: 3, quote: "b\nc",
  });
  assert.deepEqual(model.targetFor({ kind: "file", page: ONE, path: "a.py", side: "new" }, 1, 1, lines).commit, ONE);
  assert.deepEqual(model.targetFor({ kind: "message", sha: ONE }, 1, 1, lines), {
    kind: "message", commit: ONE, start: 1, end: 1, quote: "a",
  });
  assert.deepEqual(model.targetFor({ kind: "description" }, 3, 3, lines), {
    kind: "pr_body", commit: null, start: 3, end: 3, quote: "c",
  });
});

test("a comment is shown in the document of its page", () => {
  assert.deepEqual(model.docOf(comment({ page: ONE })), { kind: "file", page: ONE, path: "a.py", side: "new" });
  const message = { kind: /** @type {const} */ ("message"), commit: ONE, start: 1, end: 1, quote: "One" };
  assert.deepEqual(model.docOf(comment({ page: ONE, target: message })), { kind: "message", sha: ONE });
  const body = { kind: /** @type {const} */ ("pr_body"), commit: null, start: 1, end: 1, quote: "" };
  assert.deepEqual(model.docOf(comment({ page: "overview", target: body })), { kind: "description" });
});

test("open counts are per page, and leave out resolved and dismissed comments", () => {
  const data = branch({
    comments: [
      comment({ id: "a" }),
      comment({ id: "a", page: ONE, mirror: { label: "All changes", url: "" } }),
      comment({ id: "b", status: "resolved" }),
      comment({ id: "c", triage: "dismiss" }),
    ],
  });
  assert.deepEqual(model.openCounts(data), { changes: 1, [ONE]: 1 });
});

test("reviews are grouped by persona, latest review first, then mine, each comment once", () => {
  const data = branch({
    reviews: [
      { id: "r3", persona: "tests", name: "Tests", emoji: "🧪", verdict: "comments", latest: true },
      { id: "r2", persona: "naming", name: "Naming", emoji: "🏷️", verdict: "lgtm", latest: true },
      { id: "r1", persona: "tests", name: "Tests", emoji: "🧪", verdict: "lgtm", latest: false },
    ],
    comments: [
      comment({ id: "mine" }),
      comment({ id: "t1", persona: "tests", author: "🧪 Tests", finding_id: "TS-1" }),
      comment({ id: "t1", persona: "tests", page: ONE, mirror: { label: "All changes", url: "" } }),
      comment({ id: "x1", persona: "ux", author: "👤 UX", finding_id: "UX-1" }),
    ],
  });
  const groups = model.reviewGroups(data);
  assert.deepEqual(groups.map(g => [g.label, g.review?.id, g.comments.map(c => c.id)]), [
    ["🧪 Tests", "r3", ["t1"]],
    ["🏷️ Naming", "r2", []],
    ["👤 UX", undefined, ["x1"]],
    ["Your comments", undefined, ["mine"]],
  ]);
});

test("a thread's label has the finding, its triage and where it was made", () => {
  const data = branch();
  const finding = comment({ finding_id: "TS-1", severity: "nit", triage: "address", mirror: { label: "All changes", url: "" } });
  assert.equal(model.threadLabel(data, finding), "TS-1 · nit · to address · made on All changes");
  assert.equal(model.threadLabel(data, comment({})), undefined);
});

test("the feature is named after its plan, else the PR, else the branch", () => {
  assert.equal(model.title(branch()), "team/thing");
  assert.equal(model.title(branch({ description: { title: "Do it", body: "" } })), "Do it");
});
