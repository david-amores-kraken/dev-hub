// Save the PR title and body without leaving the page.
const form = document.getElementById("description");
const status = document.getElementById("status");
const button = form.querySelector("button");

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
  } catch {
    status.textContent = "Not saved (can't reach the hub)";
  } finally {
    button.disabled = false;
  }
});
