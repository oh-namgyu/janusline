"use strict";

/* Shell: create a brief, list the saved ones. The dual timeline view lands in a
   later stage. Every string that comes from the server is injected with
   textContent only — article titles are untrusted third-party text. */

const JL = (window.JL = {});

const noticeBar = document.getElementById("notice");
const grid = document.getElementById("brief-grid");
const emptyNote = document.getElementById("brief-empty");
const countBadge = document.getElementById("brief-count");
const form = document.getElementById("new-brief-form");
const queryInput = document.getElementById("f-query");
const periodInput = document.getElementById("f-period");
const langInput = document.getElementById("f-lang");
const submitBtn = document.getElementById("f-submit");
const formNote = document.getElementById("form-note");

async function request(method, path, payload) {
  const options = { method: method, headers: { Accept: "application/json" } };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({ ok: false, error: "bad response" }));
  if (!res.ok || !body.ok) {
    const err = new Error(body.error || "request failed");
    err.status = res.status;
    throw err;
  }
  return body.data;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function button(label, className, onClick) {
  const node = el("button", className || "btn", label);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

function notify(message) {
  noticeBar.textContent = message || "";
  noticeBar.classList.toggle("hidden", !message);
}

/* Share of positive / neutral / negative as one bar. Widths are percentages of
   the classified articles, so an unanalysed brief shows an empty rail. */
function ratioBar(counts) {
  const bar = el("div", "ratio-bar");
  const total =
    (counts.positive || 0) + (counts.negative || 0) + (counts.neutral || 0);
  if (!total) return bar;
  [
    ["ratio-pos", counts.positive || 0],
    ["ratio-neutral", counts.neutral || 0],
    ["ratio-neg", counts.negative || 0],
  ].forEach(([className, value]) => {
    const part = el("span", className);
    part.style.width = (value / total) * 100 + "%";
    bar.appendChild(part);
  });
  return bar;
}

function briefCard(brief) {
  const card = el("article", "card");
  card.appendChild(el("h3", "card-title", brief.query));
  const meta = el("div", "card-meta");
  meta.appendChild(
    el("span", null, brief.article_count + " articles · " + brief.period_days + "d · ")
  );
  meta.appendChild(el("span", "pill", brief.status));
  card.appendChild(meta);
  card.appendChild(ratioBar(brief.sentiment_counts || {}));
  if (brief.data_loss) {
    card.appendChild(
      el("p", "card-meta", "recovered after a damaged file — contents were lost")
    );
  } else if (brief.recovered) {
    card.appendChild(el("p", "card-meta", "restored from backup"));
  }
  const actions = el("div", "card-actions");
  actions.appendChild(
    button("Delete", "btn btn-danger", () => removeBrief(brief.slug))
  );
  card.appendChild(actions);
  return card;
}

async function refresh() {
  let briefs = [];
  try {
    briefs = await request("GET", "/api/briefs");
    notify("");
  } catch (err) {
    notify(err.message);
    return;
  }
  grid.replaceChildren();
  briefs.forEach((brief) => grid.appendChild(briefCard(brief)));
  countBadge.textContent = String(briefs.length);
  emptyNote.classList.toggle("hidden", briefs.length > 0);
}

async function removeBrief(slug) {
  try {
    await request("DELETE", "/api/briefs/" + slug);
  } catch (err) {
    notify(err.message);
  }
  await refresh();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;
  submitBtn.disabled = true;
  formNote.textContent = "creating…";
  try {
    await request("POST", "/api/briefs", {
      query: query,
      period_days: Number(periodInput.value),
      lang: langInput.value.split(","),
    });
    queryInput.value = "";
    formNote.textContent = "";
    notify("");
  } catch (err) {
    formNote.textContent = "";
    notify(err.message);
  }
  submitBtn.disabled = false;
  await refresh();
});

JL.request = request;
JL.refresh = refresh;
refresh();
