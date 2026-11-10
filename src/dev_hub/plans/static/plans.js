// Filter the list of plans as you type. The list itself is rendered by the server.
const filter = document.getElementById("filter");
const items = document.querySelectorAll("#plans li");
const none = document.getElementById("none");

filter.addEventListener("input", () => {
  const needle = filter.value.toLowerCase();
  let shown = 0;
  items.forEach(li => {
    const match = li.dataset.text.includes(needle);
    li.hidden = !match;
    if (match) shown++;
  });
  if (none) none.hidden = shown > 0;
});
