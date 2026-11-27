// The index page: the table is rendered by the server (/rows). This script only sends clicks,
// swaps in fresh rows, and applies the filters and the date sort.
const live = document.getElementById("live");
const filter = document.getElementById("filter");
const team = document.getElementById("team");
const addForm = document.getElementById("add-form");
const addLink = document.getElementById("add-link");
const message = document.getElementById("message");
const base = live.dataset.base;  // where this section is mounted, e.g. /prs/
let timer = null;

const busy = () => !!live.querySelector('tr[data-status="queued"], tr[data-status="running"]');

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  message.textContent = response.ok ? "" : (await response.json().catch(() => ({}))).error || "request failed";
  return response.ok;
}

async function refresh() {
  clearTimeout(timer);
  const picking = dialog.open
    || (live.contains(document.activeElement) && document.activeElement.tagName === "SELECT");
  if (!picking) {
    const chosen = {};
    live.querySelectorAll("select[data-pr]").forEach(s => { chosen[s.dataset.pr] = s.value; });
    try {
      const response = await fetch(base + "rows", { cache: "no-store" });
      if (response.ok) live.innerHTML = await response.text();
    } catch (e) {
      message.textContent = "Can't reach the pr-brief server.";
    }
    live.querySelectorAll("select[data-pr]:not(:disabled)").forEach(s => {
      const value = chosen[s.dataset.pr];
      if (value && [...s.options].some(o => o.value === value)) s.value = value;
    });
    applySort();
  }
  timer = setTimeout(refresh, busy() ? 4000 : 30000);
}

live.addEventListener("click", async event => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr");
  const pr = Number(row.dataset.pr);
  if (button.dataset.action === "brief") {
    openBrief(row);
    return;
  }
  button.disabled = true;
  await post(base + "api/mark", { pr, state: button.dataset.state || null });
  refresh();
});

// Brief opens a dialog for optional focus instructions. Confirm sends them with the tier;
// Cancel, Escape or a click outside the box sends nothing. A retry starts with the last focus.
const dialog = document.getElementById("brief-dialog");
const briefForm = document.getElementById("brief-form");
const focusBox = document.getElementById("brief-focus");
let briefing = null;

function openBrief(row) {
  const tier = row.querySelector("select").value;
  briefing = { pr: Number(row.dataset.pr), tier };
  document.getElementById("brief-pr").textContent = `#${row.dataset.pr}`;
  document.getElementById("brief-what").textContent = `${row.dataset.title} · ${tier} review`;
  focusBox.value = row.dataset.focus || "";
  document.getElementById("brief-error").textContent = "";
  dialog.showModal();
  focusBox.focus();
}

document.getElementById("brief-cancel").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", event => {
  if (event.target === dialog) dialog.close();  // the backdrop
});
focusBox.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) briefForm.requestSubmit();
});
briefForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!briefing) return;
  const confirm = document.getElementById("brief-confirm");
  confirm.disabled = true;
  const ok = await post(base + "api/brief", { ...briefing, focus: focusBox.value.trim() });
  confirm.disabled = false;
  if (!ok) {
    document.getElementById("brief-error").textContent = message.textContent;
    return;
  }
  dialog.close();
  briefing = null;
  refresh();
});

// Sorting by a date column: click once for newest first, again for oldest first, a third time to
// go back to the server's order. Rows without a date always go last. The table is replaced on
// every refresh, so the sort is applied again each time.
let sort = { key: "", dir: "desc" };
try {
  const [key, dir] = (localStorage.getItem("pr-brief-sort") || "").split(":");
  if (key === "created" || key === "updated") sort = { key, dir: dir === "asc" ? "asc" : "desc" };
} catch (e) {}

function applySort() {
  live.querySelectorAll("th[data-sort]").forEach(th => {
    th.dataset.dir = th.dataset.sort === sort.key ? sort.dir : "";
  });
  const body = live.querySelector("tbody");
  if (!body) return;
  const sign = sort.dir === "asc" ? 1 : -1;
  const rows = [...body.rows].sort((a, b) => {
    const x = a.dataset[sort.key] || "", y = b.dataset[sort.key] || "";
    if (sort.key && x !== y) return !x ? 1 : !y ? -1 : (x < y ? -1 : 1) * sign;
    return a.dataset.i - b.dataset.i;
  });
  rows.forEach(row => body.append(row));
}

live.addEventListener("click", event => {
  const header = event.target.closest("th[data-sort]");
  if (!header) return;
  if (sort.key !== header.dataset.sort) sort = { key: header.dataset.sort, dir: "desc" };
  else if (sort.dir === "desc") sort.dir = "asc";
  else sort = { key: "", dir: "desc" };
  try { localStorage.setItem("pr-brief-sort", sort.key ? `${sort.key}:${sort.dir}` : ""); } catch (e) {}
  applySort();
});

// The add box stays hidden until "Add a PR…" is clicked. Cancel, Escape or a successful add hide it.
const addToggle = document.getElementById("add-toggle");
function showAdd(show) {
  addForm.hidden = !show;
  addToggle.setAttribute("aria-expanded", String(show));
  if (show) {
    addLink.focus();
  } else {
    addLink.value = "";
  }
}
addToggle.addEventListener("click", () => showAdd(addForm.hidden));
document.getElementById("add-cancel").addEventListener("click", () => showAdd(false));
addLink.addEventListener("keydown", event => {
  if (event.key === "Escape") showAdd(false);
});

addForm.addEventListener("submit", async event => {
  event.preventDefault();
  const link = addLink.value.trim();
  if (!link) return;
  message.textContent = "adding…";
  const response = await fetch(base + "api/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ link }),
  });
  const body = await response.json().catch(() => ({}));
  if (response.ok) {
    showAdd(false);
    message.textContent = `Added #${body.number}`;
    refresh();
  } else {
    message.textContent = body.error || "request failed";
  }
});

document.getElementById("refresh").addEventListener("click", async () => {
  const stamp = () => document.getElementById("refreshed")?.textContent;
  const before = stamp();
  message.textContent = "refreshing…";
  if (!(await post(base + "api/refresh", {}))) return;
  message.textContent = "refreshing…";
  // The poller runs in the background, so check the rows until the refreshed time changes.
  for (let waited = 0; waited < 90000; waited += 3000) {
    await new Promise(resolve => setTimeout(resolve, 3000));
    await refresh();
    if (stamp() !== before) {
      message.textContent = "List refreshed.";
      return;
    }
  }
  message.textContent = "Refresh is taking a while. See ~/pr-reviews/server.log.";
});

// Which rows to show is a per-viewer convenience, so it lives in the browser.
try { filter.value = localStorage.getItem("pr-brief-filter") || "open"; } catch (e) {}
live.dataset.filter = filter.value;
try { team.value = localStorage.getItem("pr-brief-team") || "all"; } catch (e) {}
live.dataset.team = team.value;
team.addEventListener("change", () => {
  live.dataset.team = team.value;
  try { localStorage.setItem("pr-brief-team", team.value); } catch (e) {}
});
filter.addEventListener("change", () => {
  live.dataset.filter = filter.value;
  try { localStorage.setItem("pr-brief-filter", filter.value); } catch (e) {}
});

applySort();
refresh();
