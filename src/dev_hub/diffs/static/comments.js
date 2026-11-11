// Point-and-click comments. Click a line number to pick a line, shift-click another to pick a
// range, write the comment, and it is saved at once (no review to submit).
//
// A "surface" is anything with numbered lines: one file of a diff drawn by diff2html, a commit
// message, or the PR description. Each row of a surface is { el, gutter, oldNo, newNo, text }.
// Removed lines only have an oldNo, added lines only a newNo, unchanged lines have both.

const review = document.getElementById("review");
if (review) start(review);

function start(review) {
  const base = review.dataset.base; // POST here to add; /<id> to change; /<id>/delete to remove
  const commit = review.dataset.commit || null; // null on the overview and the "All changes" page
  const unplaced = document.getElementById("unplaced");
  const editing = new Set(); // ids of the comments being edited
  let comments = JSON.parse(document.getElementById("comments").textContent);
  let surfaces = [];
  let selection = null; // { surface, anchor, to, side }
  let composer = null;

  document.querySelectorAll(".text-lines").forEach(drawText);
  refresh();

  document.addEventListener("mousedown", event => {
    if (event.shiftKey && event.target.closest("td.d2h-code-linenumber, td.gutter")) event.preventDefault();
  });
  document.addEventListener("click", event => {
    const gutter = event.target.closest("td.d2h-code-linenumber, td.gutter");
    if (!gutter || !review.contains(gutter)) return;
    for (const surface of surfaces) {
      const index = surface.rows.findIndex(row => row.gutter === gutter);
      if (index >= 0) return choose(surface, index, event.shiftKey);
    }
  });
  document.addEventListener("description-saved", event => {
    const box = document.getElementById("body-lines");
    if (!box) return;
    box.dataset.text = event.detail;
    drawText(box);
    refresh();
  });

  // ---- finding the lines on the page ----

  function refresh() {
    closeComposer();
    surfaces = [...diffSurfaces(), ...textSurfaces()];
    render();
  }

  function number(element) {
    const value = parseInt(element?.textContent ?? "", 10);
    return Number.isNaN(value) ? null : value;
  }

  function diffSurfaces() {
    return [...document.querySelectorAll("#diff .d2h-file-wrapper")].map(wrapper => {
      const name = wrapper.querySelector(".d2h-file-name").textContent.trim();
      const rows = [];
      wrapper.querySelectorAll("tr").forEach(el => {
        const gutter = el.querySelector("td.d2h-code-linenumber");
        if (!gutter) return;
        const oldNo = number(gutter.querySelector(".line-num1"));
        const newNo = number(gutter.querySelector(".line-num2"));
        if (oldNo === null && newNo === null) return; // a "@@ ... @@" header row
        const text = el.querySelector(".d2h-code-line-ctn")?.textContent ?? "";
        rows.push({ el, gutter, oldNo, newNo, text });
      });
      // A renamed file is shown as "old → new". Comments are about the new name.
      return { kind: "line", file: name.split(" → ").at(-1), rows };
    });
  }

  function textSurfaces() {
    return [...document.querySelectorAll(".text-lines")].map(box => {
      const rows = [...box.querySelectorAll("tr")].map(el => ({
        el,
        gutter: el.querySelector("td.gutter"),
        oldNo: null,
        newNo: Number(el.dataset.line),
        text: el.querySelector("td.text").textContent,
      }));
      return { kind: box.dataset.kind, file: null, rows };
    });
  }

  // A commit message or the PR description, with a number beside each line.
  function drawText(box) {
    const text = box.dataset.text ?? "";
    box.replaceChildren();
    if (!text.trim()) {
      box.textContent = "Nothing here yet.";
      box.classList.add("empty");
      return;
    }
    box.classList.remove("empty");
    const table = document.createElement("table");
    text.split("\n").forEach((line, index) => {
      const row = table.insertRow();
      row.dataset.line = String(index + 1);
      row.insertCell().className = "gutter";
      row.cells[0].textContent = String(index + 1);
      row.insertCell().className = "text";
      row.cells[1].textContent = line;
    });
    box.append(table);
  }

  // ---- choosing lines and writing a comment ----

  function sideKey(side) {
    return side === "old" ? "oldNo" : "newNo";
  }

  function choose(surface, index, extend) {
    let side, anchor = index;
    if (extend && selection?.surface === surface) {
      ({ side, anchor } = selection);
    } else {
      side = surface.rows[index].newNo === null ? "old" : "new";
    }
    selection = { surface, anchor, to: index, side };
    const key = sideKey(side);
    const [from, to] = [Math.min(anchor, index), Math.max(anchor, index)];
    const chosen = surface.rows.slice(from, to + 1).filter(row => row[key] !== null);
    document.querySelectorAll("tr.selected").forEach(row => row.classList.remove("selected"));
    chosen.forEach(row => row.el.classList.add("selected"));
    openComposer(surface, side, chosen);
  }

  function clearSelection() {
    selection = null;
    document.querySelectorAll("tr.selected").forEach(row => row.classList.remove("selected"));
  }

  function openComposer(surface, side, chosen) {
    closeComposer();
    const key = sideKey(side);
    const target = {
      kind: surface.kind,
      commit: surface.kind === "pr_body" ? null : commit,
      start: chosen[0][key],
      end: chosen.at(-1)[key],
      quote: chosen.map(row => row.text).join("\n"),
    };
    if (surface.kind === "line") Object.assign(target, { file: surface.file, side });

    const { box, textarea } = editor("Comment", "Cancel", async text => {
      const created = await post(base, { target, text });
      comments.push(created);
      clearSelection();
      refresh();
    }, () => { clearSelection(); closeComposer(); });
    const heading = document.createElement("div");
    heading.className = "meta";
    heading.textContent = describe(target);
    box.prepend(heading);

    composer = document.createElement("tr");
    composer.className = "composer-row";
    const cell = composer.insertCell();
    cell.colSpan = 2;
    cell.append(box);
    placeAfter(chosen.at(-1).el, composer);
    textarea.focus();
  }

  function closeComposer() {
    composer?.remove();
    composer = null;
  }

  // A form with a text box and two buttons. `submit(text)` may throw; the message is shown.
  function editor(doLabel, cancelLabel, submit, cancel, text = "") {
    const box = document.createElement("form");
    box.className = "editor";
    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.value = text;
    textarea.setAttribute("aria-label", "Comment");
    const buttons = document.createElement("div");
    buttons.className = "controls";
    const go = button(doLabel, "act");
    go.type = "submit";
    const stop = button(cancelLabel, "plain");
    stop.addEventListener("click", cancel);
    const error = document.createElement("span");
    error.className = "err";
    buttons.append(go, stop, error);
    box.append(textarea, buttons);
    box.addEventListener("submit", async event => {
      event.preventDefault();
      if (!textarea.value.trim()) return;
      go.disabled = true;
      error.textContent = "";
      try {
        await submit(textarea.value);
      } catch (problem) {
        error.textContent = problem.message;
        go.disabled = false;
      }
    });
    textarea.addEventListener("keydown", event => {
      if (event.key === "Escape") cancel();
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) box.requestSubmit();
    });
    return { box, textarea, error };
  }

  function button(label, kind) {
    const element = document.createElement("button");
    element.type = "button";
    element.className = kind;
    element.textContent = label;
    return element;
  }

  // ---- showing the comments ----

  function render() {
    document.querySelectorAll("tr.comments-row").forEach(row => row.remove());
    const list = unplaced.querySelector(".comments");
    list.replaceChildren();
    for (const comment of comments) {
      const row = findRow(comment.target);
      if (row) holder(row).append(card(comment, false));
      else list.append(card(comment, true));
    }
    unplaced.hidden = !list.children.length;
  }

  // The row a comment sits under: the last line of its range. The lines on the page must still
  // be the quoted ones; if they aren't, the comment is listed as one that couldn't be placed
  // instead of being shown against the wrong code.
  function findRow(target) {
    const surface = surfaces.find(s => s.kind === target.kind && (s.kind !== "line" || s.file === target.file));
    if (!surface) return undefined;
    const key = sideKey(target.side ?? "new");
    const quote = target.quote.split("\n").map(line => line.trimEnd());
    const lines = surface.rows.filter(row => row[key] !== null && row[key] >= target.start && row[key] <= target.end);
    const same = lines.length === quote.length && lines.every((row, i) => row.text.trimEnd() === quote[i]);
    return same ? lines.at(-1) : undefined;
  }

  function holder(row) {
    let next = row.el.nextElementSibling;
    if (!next?.classList.contains("comments-row")) {
      next = document.createElement("tr");
      next.className = "comments-row";
      const cell = next.insertCell();
      cell.colSpan = 2;
      cell.append(Object.assign(document.createElement("div"), { className: "comments" }));
      row.el.after(next);
    }
    return next.querySelector(".comments");
  }

  function placeAfter(rowEl, element) {
    const next = rowEl.nextElementSibling;
    (next?.classList.contains("comments-row") ? next : rowEl).after(element);
  }

  function describe(target) {
    const lines = target.start === target.end ? `Line ${target.start}` : `Lines ${target.start}–${target.end}`;
    const where = { line: target.file, message: "commit message", pr_body: "description" }[target.kind];
    return `${where} · ${lines}${target.side === "old" ? " (removed)" : ""}`;
  }

  function card(comment, showWhere) {
    const el = document.createElement("div");
    const dismissed = comment.triage === "dismiss";
    el.className = "comment" + (comment.status === "resolved" ? " resolved" : "") + (dismissed ? " dismissed" : "");
    if (comment.severity) el.dataset.severity = comment.severity;
    const head = document.createElement("div");
    head.className = "meta";
    const when = comment.created.slice(0, 16).replace("T", " ");
    const commitName = showWhere && comment.target.subject ? `“${comment.target.subject}”` : null;
    const who = comment.finding_id ? `${comment.author} ${comment.finding_id} · ${comment.severity}` : null;
    const state = dismissed ? "dismissed" : comment.status === "resolved" ? "resolved" : comment.triage === "address" ? "to address" : null;
    head.textContent = [who, commitName, showWhere ? describe(comment.target) : null, when, state]
      .filter(Boolean).join(" · ");
    el.append(head);
    if (showWhere) {
      const quote = document.createElement("pre");
      quote.className = "quote";
      quote.textContent = comment.target.quote;
      el.append(quote);
    }
    if (editing.has(comment.id)) {
      const { box, textarea } = editor("Save", "Cancel", async text => {
        replace(await post(`${base}/${comment.id}`, { text }));
        editing.delete(comment.id);
        render();
      }, () => { editing.delete(comment.id); render(); }, comment.text);
      el.append(box);
      queueMicrotask(() => textarea.focus());
      return el;
    }
    const text = document.createElement("div");
    text.className = "text";
    text.textContent = comment.text;
    el.append(text);
    for (const reply of comment.replies ?? []) {
      const answer = document.createElement("div");
      answer.className = "reply";
      const by = document.createElement("div");
      by.className = "meta";
      by.textContent = [reply.author, reply.commit ? `in ${reply.commit}` : null, reply.created.slice(0, 16).replace("T", " ")]
        .filter(Boolean).join(" · ");
      const words = document.createElement("div");
      words.className = "text";
      words.textContent = reply.text;
      answer.append(by, words);
      el.append(answer);
    }
    const actions = document.createElement("div");
    actions.className = "controls";
    if (comment.finding_id) {
      // A reviewer's finding is only worked on if I say so.
      for (const [choice, label] of [["address", "Address"], ["dismiss", "Dismiss"]]) {
        const on = comment.triage === choice;
        const mark = button(on ? `Undo ${label.toLowerCase()}` : label, "plain");
        mark.addEventListener("click", () => act(async () => {
          replace(await post(`${base}/${comment.id}`, { triage: on ? null : choice }));
        }));
        actions.append(mark);
      }
    }
    const resolve = button(comment.status === "open" ? "Resolve" : "Reopen", "plain");
    resolve.addEventListener("click", () => act(async () => {
      replace(await post(`${base}/${comment.id}`, { status: comment.status === "open" ? "resolved" : "open" }));
    }));
    const edit = button("Edit", "plain");
    edit.addEventListener("click", () => { editing.add(comment.id); render(); });
    const remove = button("Delete", "plain");
    remove.addEventListener("click", () => act(async () => {
      if (!confirm("Delete this comment?")) return;
      await post(`${base}/${comment.id}/delete`, {});
      comments = comments.filter(c => c.id !== comment.id);
    }));
    actions.append(resolve, edit, remove);
    el.append(actions);
    return el;
  }

  function replace(updated) {
    comments = comments.map(c => (c.id === updated.id ? updated : c));
  }

  async function act(change) {
    try {
      await change();
      render();
    } catch (problem) {
      alert(problem.message);
    }
  }

  async function post(url, payload) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new Error("Can't reach the hub");
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error ?? `Failed (${response.status})`);
    return body;
  }
}
