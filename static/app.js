"use strict";

/* Shell: shared helpers, hash router, home view.
   The brief view lives in brief.js and timeline.js, both of which attach
   themselves to window.JL. Every string that comes from the server — article
   titles, feed snippets, model prose — is injected with textContent only. */

const JL = (window.JL = {});

const BRIEF_ROUTE = /^#\/brief\/([a-z0-9-]{1,64})$/;
const STATUS_RE = /^(empty|collected|analyzed)$/;
const NO_KEY_MESSAGE =
  "Browse-only: set ANTHROPIC_API_KEY on the server to enable analysis. " +
  "The brief and its articles stay readable without a key.";
const SENTIMENTS = ["positive", "neutral", "negative"];
const SENTIMENT_CLASS = { positive: "pos", neutral: "neu", negative: "neg" };

const noticeBar = document.getElementById("notice");
const views = {
  home: document.getElementById("view-home"),
  brief: document.getElementById("view-brief"),
};
const grid = document.getElementById("brief-grid");
const emptyNote = document.getElementById("brief-empty");
const countBadge = document.getElementById("brief-count");
const form = document.getElementById("new-brief-form");
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

/* Article links are third-party URLs: they open away from the app, in a tab
   that cannot reach back into this one. */
function externalLink(text, href) {
  const node = el("a", "link", text);
  node.href = href || "#";
  node.target = "_blank";
  node.rel = "noopener noreferrer";
  return node;
}

/* status drives a colour, so it is whitelisted before it reaches a class name */
function statusClass(status) {
  const value = String(status || "empty");
  return "pill pill-" + (STATUS_RE.test(value) ? value : "empty");
}

function statusPill(status) {
  return el("span", statusClass(status), String(status || "empty"));
}

function clearNotice() {
  noticeBar.replaceChildren();
  noticeBar.className = "notice hidden";
}

function showNotice(message, variant, actionLabel, action) {
  noticeBar.replaceChildren();
  noticeBar.className = "notice notice-" + (variant || "info");
  noticeBar.appendChild(el("span", "notice-text", message));
  if (actionLabel) noticeBar.appendChild(button(actionLabel, "btn btn-small", action));
  noticeBar.appendChild(button("Dismiss", "btn btn-small", clearNotice));
}

function counts(source) {
  const values = source || {};
  const tally = { total: 0 };
  SENTIMENTS.forEach((name) => {
    tally[name] = Number(values[name]) || 0;
    tally.total += tally[name];
  });
  return tally;
}

/* Positive, neutral and negative as one bar. Widths are shares of the
   classified articles — the only computed style in the app — so a brief that
   has not been analysed yet shows a dashed, empty rail instead of a lie. */
function ratioBar(source) {
  const bar = el("div", "ratio-bar");
  const tally = counts(source);
  if (!tally.total) {
    bar.appendChild(el("span", "ratio-empty"));
    return bar;
  }
  SENTIMENTS.forEach((name) => {
    if (!tally[name]) return;
    const part = el("span", "ratio-" + SENTIMENT_CLASS[name]);
    part.style.width = (tally[name] / tally.total) * 100 + "%";
    bar.appendChild(part);
  });
  return bar;
}

function shortDate(iso) {
  const value = String(iso || "");
  return value.length >= 10 ? value.slice(0, 10) : value;
}

Object.assign(JL, {
  NO_KEY_MESSAGE: NO_KEY_MESSAGE,
  SENTIMENTS: SENTIMENTS,
  SENTIMENT_CLASS: SENTIMENT_CLASS,
  request: request,
  el: el,
  button: button,
  externalLink: externalLink,
  statusClass: statusClass,
  statusPill: statusPill,
  showNotice: showNotice,
  clearNotice: clearNotice,
  counts: counts,
  ratioBar: ratioBar,
  shortDate: shortDate,
});

// -- home ------------------------------------------------------------------
function askDelete(card, actions, slug) {
  actions.classList.add("hidden");
  const bar = el("div", "confirm-bar");
  const restore = () => {
    bar.remove();
    actions.classList.remove("hidden");
  };
  bar.appendChild(el("span", "confirm-text", "Delete this brief?"));
  bar.appendChild(
    button("Delete", "btn btn-small btn-danger", async () => {
      try {
        await request("DELETE", "/api/briefs/" + slug);
        await loadBriefs();
      } catch (err) {
        restore();
        showNotice("Delete failed: " + err.message, "error");
      }
    })
  );
  bar.appendChild(button("Cancel", "btn btn-small", restore));
  card.appendChild(bar);
}

function briefCard(brief) {
  const card = el("article", "card");
  card.dataset.slug = brief.slug;
  const body = el("div", "card-body");
  const title = el("h3", "card-title");
  const link = el("a", "link", brief.query || brief.slug);
  link.href = "#/brief/" + brief.slug;
  title.appendChild(link);
  body.appendChild(title);
  body.appendChild(ratioBar(brief.sentiment_counts));
  const meta = el("div", "card-meta");
  meta.appendChild(el("span", null, (brief.article_count || 0) + " articles"));
  meta.appendChild(el("span", null, brief.period_days + "d"));
  meta.appendChild(statusPill(brief.status));
  body.appendChild(meta);
  const stamp = el("div", "card-meta");
  stamp.appendChild(el("span", null, "created " + shortDate(brief.created)));
  if (brief.data_loss) stamp.appendChild(el("span", "badge badge-warn", "contents lost"));
  else if (brief.recovered) stamp.appendChild(el("span", "badge badge-warn", "restored"));
  body.appendChild(stamp);
  card.appendChild(body);
  const actions = el("div", "card-actions");
  actions.appendChild(
    button("Open", "btn btn-small", () => {
      location.hash = "#/brief/" + brief.slug;
    })
  );
  actions.appendChild(
    button("Delete", "btn btn-small btn-danger", () => askDelete(card, actions, brief.slug))
  );
  card.appendChild(actions);
  return card;
}

function renderBriefs(briefs) {
  grid.replaceChildren();
  countBadge.textContent = String(briefs.length);
  emptyNote.classList.toggle("hidden", briefs.length > 0);
  briefs.forEach((brief) => grid.appendChild(briefCard(brief)));
}

async function loadBriefs() {
  try {
    renderBriefs(await request("GET", "/api/briefs"));
  } catch (err) {
    grid.replaceChildren();
    emptyNote.classList.remove("hidden");
    emptyNote.textContent = "Could not load briefs: " + err.message;
  }
}

function setBusy(busy, label) {
  submitBtn.disabled = busy;
  formNote.textContent = busy ? label : "";
}

function chosenLangs() {
  return ["ko", "en"].filter((code) => document.getElementById("f-" + code).checked);
}

/* Collection is a second call after creation: a feed that is down leaves the
   saved brief in place, so the user lands on it and retries without retyping. */
async function collectThenOpen(slug) {
  setBusy(true, "Collecting…");
  try {
    await request("POST", "/api/briefs/" + slug + "/collect");
    clearNotice();
  } catch (err) {
    showNotice("Collection failed: " + err.message, "error");
  } finally {
    setBusy(false);
    location.hash = "#/brief/" + slug;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const lang = chosenLangs();
  if (!lang.length) {
    showNotice("Pick at least one edition to search.", "warn");
    return;
  }
  const payload = {
    query: document.getElementById("f-query").value,
    period_days: Number(document.getElementById("f-period").value),
    lang: lang,
  };
  setBusy(true, "Creating…");
  let created;
  try {
    created = await request("POST", "/api/briefs", payload);
    document.getElementById("f-query").value = "";
  } catch (err) {
    showNotice("Could not create the brief: " + err.message, "error");
    setBusy(false);
    return;
  }
  await collectThenOpen(created.slug);
});

// -- routing ---------------------------------------------------------------
function showView(name) {
  Object.keys(views).forEach((key) => views[key].classList.toggle("hidden", key !== name));
}

function route() {
  const match = BRIEF_ROUTE.exec(location.hash || "#/");
  if (match) {
    showView("brief");
    JL.openBrief(match[1]);
    return;
  }
  showView("home");
  loadBriefs();
}

JL.loadBriefs = loadBriefs;
window.addEventListener("hashchange", route);
// fires after brief.js has registered JL.openBrief (all three scripts are classic)
window.addEventListener("DOMContentLoaded", route);
