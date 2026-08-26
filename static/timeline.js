"use strict";

/* The dual timeline: one vertical time axis, favourable articles to its left,
   unfavourable to its right, and everything the model would not take a side on
   riding the axis itself as a slim chip. Day ticks break the run into readable
   groups; within a day the server's newest-first order is kept.

   The three columns are drawn by CSS (.tl-entry is the grid). This file only
   decides which column an article belongs in, and states that decision in
   words as well as colour — the tag is read out by the ≤860px stack, where
   left and right no longer exist. */

(function (JL) {
  const CITED_MS = 2600;
  const TAGS = {
    positive: "positive",
    negative: "negative",
    neutral: "neutral",
    unclassified: "unclassified",
  };
  const QUOTE_MARK = "❝";
  const NO_QUOTE_MARK = "◇";
  const APPROX_MARK = "~";

  const board = document.getElementById("timeline");
  const emptyNote = document.getElementById("timeline-empty");
  const index = new Map();
  let citedTimer = 0;

  function polarityOf(article) {
    const value = article.sentiment;
    return TAGS[value] ? value : "unclassified";
  }

  function dayOf(article) {
    return JL.shortDate(article.published) || "undated";
  }

  function tick(day) {
    const row = JL.el("div", "tl-tick");
    row.appendChild(JL.el("span", "tl-tick-date", day));
    return row;
  }

  function metaLine(article) {
    const meta = JL.el("div", "tl-meta");
    meta.appendChild(JL.el("span", null, article.source || "unknown"));
    const stamp = JL.shortDate(article.published);
    meta.appendChild(
      JL.el("span", null, article.date_approx ? APPROX_MARK + " " + stamp : stamp)
    );
    return meta;
  }

  /* Evidence is a passage the server checked against the article's own text.
     When it is missing the card says so rather than staying silent — an
     unsupported classification should look different from a supported one. */
  function grounding(article) {
    if (!article.evidence) return JL.el("p", "tl-noquote", NO_QUOTE_MARK + " no direct quote");
    const line = JL.el("p", "tl-quote");
    line.appendChild(JL.el("span", "tl-quote-mark", QUOTE_MARK));
    line.appendChild(document.createTextNode(String(article.evidence)));
    return line;
  }

  function titleLine(article, className) {
    const title = JL.el("h3", className || "tl-title");
    title.appendChild(JL.externalLink(article.title || article.link, article.link));
    return title;
  }

  function label(polarity) {
    return JL.el("span", "tl-tag tl-tag-" + (JL.SENTIMENT_CLASS[polarity] || "neu"), TAGS[polarity]);
  }

  function describe(article, polarity) {
    return [TAGS[polarity], article.title || "", article.source || ""].join(", ");
  }

  /* Neutral and not-yet-classified articles are kept, not dropped: the share of
     them is itself a reading of the query. They just do not get a side. */
  function chip(article, polarity) {
    const node = JL.el("article", "tl-chip");
    node.appendChild(label(polarity));
    node.appendChild(titleLine(article, "tl-title"));
    if (polarity === "neutral") node.appendChild(metaLine(article));
    return node;
  }

  function card(article, polarity) {
    const node = JL.el("article", "tl-card tl-" + JL.SENTIMENT_CLASS[polarity]);
    const head = JL.el("div", "tl-head");
    head.appendChild(label(polarity));
    node.appendChild(head);
    node.appendChild(titleLine(article));
    node.appendChild(metaLine(article));
    if (article.summary) node.appendChild(JL.el("p", "tl-summary", article.summary));
    node.appendChild(grounding(article));
    return node;
  }

  function entry(article) {
    const polarity = polarityOf(article);
    const sided = polarity === "positive" || polarity === "negative";
    const row = JL.el("div", "tl-entry");
    const body = sided ? card(article, polarity) : chip(article, polarity);
    body.dataset.articleId = article.id || "";
    body.setAttribute("aria-label", describe(article, polarity));
    row.appendChild(body);
    if (sided) row.appendChild(JL.el("span", "tl-node tl-node-" + JL.SENTIMENT_CLASS[polarity]));
    index.set(article.id, body);
    return row;
  }

  function render(articles) {
    board.replaceChildren();
    index.clear();
    const list = articles || [];
    emptyNote.classList.toggle("hidden", list.length > 0);
    let day = null;
    list.forEach((article) => {
      const stamp = dayOf(article);
      if (stamp !== day) {
        day = stamp;
        board.appendChild(tick(day));
      }
      board.appendChild(entry(article));
    });
  }

  /* A citation points at a card: bring it into view and hold a mark on it long
     enough to be found, then let it go. */
  function jumpTo(articleId) {
    const node = index.get(articleId);
    if (!node) return;
    if (citedTimer) window.clearTimeout(citedTimer);
    index.forEach((other) => other.classList.remove("is-cited"));
    node.scrollIntoView({ block: "center" });
    node.classList.add("is-cited");
    citedTimer = window.setTimeout(() => node.classList.remove("is-cited"), CITED_MS);
  }

  JL.renderTimeline = render;
  JL.jumpToArticle = jumpTo;
  JL.articleTitle = (articleId) => {
    const node = index.get(articleId);
    const title = node && node.querySelector(".tl-title");
    return title ? title.textContent : articleId;
  };
})(window.JL);
