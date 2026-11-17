// Save the PR title and body without leaving the page.
const form = document.getElementById("description");
const status = document.getElementById("status");
const button = form.querySelector("button");

// Write and Preview tabs. The preview shows what is typed, saved or not.
const write = document.getElementById("tab-write");
const preview = document.getElementById("tab-preview");
const box = document.getElementById("body-preview");

function show(previewing) {
  write.setAttribute("aria-selected", String(!previewing));
  preview.setAttribute("aria-selected", String(previewing));
  form.body.hidden = previewing;
  box.hidden = !previewing;
}

write.addEventListener("click", () => show(false));
preview.addEventListener("click", async () => {
  show(true);
  box.textContent = "Rendering…";
  try {
    const response = await fetch(preview.dataset.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: form.body.value }),
    });
    // The server escapes raw HTML and drops images, so what comes back is safe to insert.
    if (response.ok) box.innerHTML = (await response.json()).html || "<p class='muted'>Nothing to preview.</p>";
    else box.textContent = `Can't preview (${response.status})`;
  } catch {
    box.textContent = "Can't preview (can't reach the hub)";
  }
});

form.addEventListener("input", () => { status.textContent = "Unsaved changes"; });

form.addEventListener("submit", async event => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = "Saving…";
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: form.title.value, body: form.body.value }),
    });
    status.textContent = response.ok ? "Saved" : `Not saved (${response.status})`;
    // Let comments.js show the lines that are now saved.
    if (response.ok) document.dispatchEvent(new CustomEvent("description-saved", { detail: form.body.value }));
  } catch {
    status.textContent = "Not saved (can't reach the hub)";
  } finally {
    button.disabled = false;
  }
});
