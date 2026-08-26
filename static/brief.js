"use strict";

/* The brief view: summary bar, the dual timeline (timeline.js draws it) and the
   two readings underneath. Nothing here trusts the server's prose — every
   string lands through textContent. */

(function (JL) {
  const AMBIGUOUS_AT = 0.6;
  const SIDES = [
    { name: "positive", node: "synth-positive", title: "Favourable reading" },
    { name: "negative", node: "synth-negative", title: "Unfavourable reading" },
  ];
  const IF_LABEL = "IF this narrative holds →";
  const UNGROUNDED = "insufficient citations";
  const NO_SYNTHESIS = "Run Analyze to read both sides of this coverage.";
  const CITE_MAX = 64;

  const dom = {
    query: document.getElementById("bv-query"),
    status: document.getElementById("bv-status"),
    meta: document.getElementById("bv-meta"),
    gauge: document.getElementById("bv-gauge"),
    ambiguous: document.getElementById("bv-ambiguous"),
    collect: document.getElementById("bv-collect"),
    analyze: document.getElementById("bv-analyze"),
    exportBtn: document.getElementById("bv-export"),
    caveat: document.getElementById("synth-caveat"),
  };

  let current = null;

  // -- summary bar ---------------------------------------------------------
  function gauge(tally) {
    dom.gauge.replaceChildren();
    dom.gauge.appendChild(JL.ratioBar(tally));
    const legend = JL.el("div", "gauge-legend");
    JL.SENTIMENTS.forEach((name) => {
      const item = JL.el("span", "gauge-item");
      item.appendChild(JL.el("span", "gauge-dot gauge-dot-" + JL.SENTIMENT_CLASS[name]));
      item.appendChild(JL.el("span", "gauge-count", tally[name]));
      // a real space, so the legend reads "4 positive" to a screen reader too
      item.appendChild(document.createTextNode(" "));
      item.appendChild(JL.el("span", null, name));
      legend.appendChild(item);
    });
    dom.gauge.appendChild(legend);
  }

  /* A brief that comes back mostly neutral usually means the query, not the
     coverage: the model could not tell which stories were about this subject. */
  function ambiguity(brief, tally) {
    const share = tally.total ? tally.neutral / tally.total : 0;
    const flag = brief.status === "analyzed" && share >= AMBIGUOUS_AT;
    dom.ambiguous.classList.toggle("hidden", !flag);
  }

  function summary(brief) {
    const articles = brief.articles || [];
    const tally = JL.counts(sentimentCounts(articles));
    dom.query.textContent = brief.query || brief.slug;
    dom.status.className = JL.statusClass(brief.status);
    dom.status.textContent = String(brief.status || "empty");
    dom.meta.textContent = [
      articles.length + " articles",
      "last " + brief.period_days + " days",
      (brief.lang || []).join(" + ") || "no editions",
      "updated " + JL.shortDate(brief.updated),
    ].join(" · ");
    gauge(tally);
    ambiguity(brief, tally);
  }

  function sentimentCounts(articles) {
    const tally = {};
    articles.forEach((article) => {
      const name = article.sentiment;
      if (name) tally[name] = (tally[name] || 0) + 1;
    });
    return tally;
  }

  function buttons(brief) {
    const has = (brief.articles || []).length > 0;
    dom.collect.textContent = has ? "Re-collect" : "Collect";
    dom.analyze.textContent = brief.status === "analyzed" ? "Re-analyze" : "Analyze";
    dom.analyze.disabled = !has;
    dom.exportBtn.disabled = !has;
  }

  // -- synthesis -----------------------------------------------------------
  function citeLabel(articleId) {
    const title = String(JL.articleTitle(articleId) || articleId);
    return title.length > CITE_MAX ? title.slice(0, CITE_MAX) + "…" : title;
  }

  function citations(ids) {
    const row = JL.el("div", "synth-cites");
    (ids || []).forEach((articleId) => {
      const cite = JL.button(citeLabel(articleId), "synth-cite", () =>
        JL.jumpToArticle(articleId)
      );
      cite.title = "Jump to this article on the timeline";
      row.appendChild(cite);
    });
    return row;
  }

  function sideHead(side, block) {
    const head = JL.el("div", "synth-head");
    head.appendChild(JL.el("h3", "synth-title", side.title));
    if (block && block.ungrounded) {
      head.appendChild(JL.el("span", "badge badge-warn", UNGROUNDED));
    }
    return head;
  }

  function renderSide(side, block) {
    const panel = document.getElementById(side.node);
    panel.replaceChildren(sideHead(side, block));
    if (!block) {
      panel.appendChild(JL.el("p", "synth-empty", NO_SYNTHESIS));
      return;
    }
    panel.appendChild(JL.el("p", "synth-text", block.narrative || ""));
    const scenario = JL.el("div", "synth-if");
    scenario.appendChild(JL.el("span", "synth-if-label", IF_LABEL));
    scenario.appendChild(JL.el("p", "synth-if-text", block.if_scenario || ""));
    panel.appendChild(scenario);
    panel.appendChild(citations(block.citations));
  }

  function synthesis(brief) {
    const found = brief.synthesis || null;
    SIDES.forEach((side) => renderSide(side, found ? found[side.name] : null));
    dom.caveat.textContent = found ? found.caveat || "" : "";
  }

  // -- actions -------------------------------------------------------------
  function paint(brief) {
    current = brief;
    summary(brief);
    buttons(brief);
    JL.renderTimeline(brief.articles);
    synthesis(brief);
  }

  async function run(node, label, path, onError) {
    const previous = node.textContent;
    node.disabled = true;
    node.textContent = label;
    try {
      paint(await JL.request("POST", path));
      JL.clearNotice();
    } catch (err) {
      node.textContent = previous;
      onError(err);
    } finally {
      node.disabled = false;
    }
  }

  function collect() {
    if (!current) return;
    run(dom.collect, "Collecting…", "/api/briefs/" + current.slug + "/collect", (err) =>
      JL.showNotice("Collection failed: " + err.message, "error", "Retry", collect)
    );
  }

  /* A server with no key still serves the brief: the app degrades to browsing
     rather than breaking, and says which switch turns analysis on. */
  function analyze() {
    if (!current) return;
    run(dom.analyze, "Analyzing…", "/api/briefs/" + current.slug + "/analyze", (err) => {
      if (err.status === 503) JL.showNotice(JL.NO_KEY_MESSAGE, "warn");
      else JL.showNotice("Analysis failed: " + err.message, "error", "Retry", analyze);
    });
  }

  function exportBrief() {
    if (current) window.open("/api/briefs/" + current.slug + "/export", "_blank");
  }

  dom.collect.addEventListener("click", collect);
  dom.analyze.addEventListener("click", analyze);
  dom.exportBtn.addEventListener("click", exportBrief);

  JL.openBrief = async (slug) => {
    try {
      paint(await JL.request("GET", "/api/briefs/" + slug));
    } catch (err) {
      current = null;
      JL.showNotice("Could not open this brief: " + err.message, "error", "Briefs", () => {
        location.hash = "#/";
      });
    }
  };
})(window.JL);
