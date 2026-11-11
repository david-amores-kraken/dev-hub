// Draw the patch the server put in the page. diff2html parses it, lays it out and highlights it.
// Only the line-by-line layout is used: comments.js reads its rows to let me comment on lines.
const patch = JSON.parse(document.getElementById("patch").textContent);

new Diff2HtmlUI(document.getElementById("diff"), patch, {
  outputFormat: "line-by-line",
  drawFileList: true,
  matching: "lines",
  colorScheme: "auto",
  highlight: true,
  fileContentToggle: false,
}).draw();
