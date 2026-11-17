// Draw the patch the server put in the page. diff2html parses it and lays it out.
// Only the line-by-line layout is used: comments.js reads its rows to let me comment on lines.
//
// diff2html highlights each line on its own, so anything that spans lines (a docstring, a
// multi-line string) comes out wrong. Instead, each side of each file is highlighted whole, then
// cut back into lines. The server sends the whole files; where it couldn't (a new file's old
// side, a binary or huge file), the lines in the diff stand in for the file.
const patch = JSON.parse(document.getElementById("patch").textContent);
const versions = JSON.parse(document.getElementById("versions")?.textContent ?? "[]");

const ui = new Diff2HtmlUI(document.getElementById("diff"), patch, {
  outputFormat: "line-by-line",
  drawFileList: true,
  matching: "lines",
  colorScheme: "auto",
  highlight: false,
  fileContentToggle: false,
});
ui.draw();
highlight(ui.hljs);
addCopyButtons();

// A button after each file's path, in the list of files and in each file's header, that copies
// the path. For a renamed file it copies the new path.
function addCopyButtons() {
  const copyIcon = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/><path fill="currentColor" d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/></svg>';
  const doneIcon = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"/></svg>';
  document.querySelectorAll("#diff .d2h-file-name").forEach(name => {
    const path = newPath(name.textContent.trim());
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-path";
    button.title = `Copy ${path}`;
    button.setAttribute("aria-label", `Copy path ${path}`);
    button.innerHTML = copyIcon;
    button.addEventListener("click", async event => {
      event.preventDefault();
      event.stopPropagation();
      try {
        await navigator.clipboard.writeText(path);
        button.innerHTML = doneIcon;
        button.title = "Copied";
      } catch {
        button.title = "Couldn't copy";
      }
      setTimeout(() => { button.innerHTML = copyIcon; button.title = `Copy ${path}`; }, 1500);
    });
    name.after(button);
  });
}

// diff2html names a renamed file "old → new", or "dir/{old → new}/rest" when the paths share
// a start or an end. Give the new path.
function newPath(name) {
  const braced = name.replace(/\{[^{}]* → ([^{}]*)\}/, "$1").replace(/\/\/+/g, "/");
  return braced.split(" → ").at(-1);
}

function highlight(hljs) {
  const wrappers = document.querySelectorAll("#diff .d2h-file-wrapper");
  wrappers.forEach((wrapper, index) => {
    const lang = wrapper.dataset.lang;
    const language = lang && hljs.getLanguage(lang) ? lang : "plaintext";
    const rows = diffRows(wrapper);
    const files = wrappers.length === versions.length ? versions[index] : {};
    for (const side of ["old", "new"]) {
      const mine = rows.filter(row => row.side === side);
      if (!mine.length) continue;
      const lines = splitLines(hljs.highlight(fileText(files[side], mine), { language, ignoreIllegals: true }).value);
      for (const row of mine) paint(row, lines[row.number - 1]);
    }
  });
}

// Each code row with the side it belongs to: removed lines are old, the others are new.
function diffRows(wrapper) {
  const rows = [];
  wrapper.querySelectorAll("tr").forEach(tr => {
    const cell = tr.querySelector(".d2h-code-line-ctn");
    const oldNo = parseInt(tr.querySelector(".line-num1")?.textContent ?? "", 10);
    const newNo = parseInt(tr.querySelector(".line-num2")?.textContent ?? "", 10);
    if (!cell || (Number.isNaN(oldNo) && Number.isNaN(newNo))) return;
    const side = Number.isNaN(newNo) ? "old" : "new";
    rows.push({ cell, side, number: side === "old" ? oldNo : newNo });
  });
  return rows;
}

// The whole file if the server sent it, else the diff's lines at their line numbers.
function fileText(text, rows) {
  if (typeof text === "string") return text;
  const lines = [];
  for (const row of rows) lines[row.number - 1] = row.cell.textContent;
  return Array.from(lines, line => line ?? "").join("\n");
}

// highlight.js gives one string of HTML. Cut it at each newline, closing the spans that are
// open at the end of a line and opening them again on the next.
function splitLines(html) {
  const lines = [];
  const open = [];
  let line = "";
  for (const part of html.split(/(<[^>]*>)/)) {
    if (part.startsWith("</")) { open.pop(); line += part; continue; }
    if (part.startsWith("<")) { open.push(part); line += part; continue; }
    const pieces = part.split("\n");
    line += pieces[0];
    for (const piece of pieces.slice(1)) {
      lines.push(line + "</span>".repeat(open.length));
      line = open.join("") + piece;
    }
  }
  lines.push(line);
  return lines;
}

// Put the highlighted line in the cell, keeping diff2html's marks on the changed words.
function paint(row, html) {
  const text = row.cell.textContent;
  if (html === undefined) return;
  const marks = [];
  let offset = 0;
  for (const node of row.cell.childNodes) {
    const length = node.textContent.length;
    if (node.nodeType === Node.ELEMENT_NODE) marks.push({ start: offset, end: offset + length, node });
    offset += length;
  }
  const holder = document.createElement("span");
  holder.innerHTML = html;
  // The file and the diff should agree. If they don't (line endings, say), leave the line plain.
  if (holder.textContent !== text) return;
  for (const mark of marks) wrap(holder, mark);
  row.cell.replaceChildren(...holder.childNodes);
  row.cell.classList.add("hljs");
}

// Wrap the text between two offsets in a copy of `mark.node` (an <ins> or a <del>), one copy
// per piece of text, so the highlight spans stay as they are.
function wrap(holder, mark) {
  const walker = document.createTreeWalker(holder, NodeFilter.SHOW_TEXT);
  const pieces = [];
  let offset = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const start = offset, end = offset + node.data.length;
    offset = end;
    if (end <= mark.start || start >= mark.end) continue;
    pieces.push({ node, from: Math.max(mark.start - start, 0), to: Math.min(mark.end, end) - start });
  }
  for (const { node, from, to } of pieces) {
    let middle = node;
    if (from > 0) middle = middle.splitText(from);
    if (to - from < middle.data.length) middle.splitText(to - from);
    const box = mark.node.cloneNode(false);
    middle.replaceWith(box);
    box.append(middle);
  }
}
