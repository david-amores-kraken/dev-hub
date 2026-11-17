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
