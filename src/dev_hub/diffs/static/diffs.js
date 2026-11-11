// Draw the patch the server put in the page. diff2html parses it, lays it out and highlights it.
const patch = JSON.parse(document.getElementById("patch").textContent);
const button = document.getElementById("layout");
const target = document.getElementById("diff");

function read() {
  try { return localStorage.getItem("diffs.layout") || "line-by-line"; } catch { return "line-by-line"; }
}

function draw(layout) {
  const ui = new Diff2HtmlUI(target, patch, {
    outputFormat: layout,
    drawFileList: true,
    matching: "lines",
    colorScheme: "auto",
    highlight: true,
  });
  ui.draw();
  ui.highlightCode();
  button.textContent = layout === "line-by-line" ? "Side by side" : "Line by line";
  button.dataset.layout = layout;
}

button.addEventListener("click", () => {
  const next = button.dataset.layout === "line-by-line" ? "side-by-side" : "line-by-line";
  try { localStorage.setItem("diffs.layout", next); } catch { /* the choice just isn't remembered */ }
  draw(next);
});

draw(read());
