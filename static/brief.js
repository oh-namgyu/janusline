"use strict";

/* The brief view's summary bar and its two long-running actions. The dual
   timeline and the two readings land here in the next stage; for now the view
   states what a brief holds and drives collection and analysis.
   Nothing here trusts the server's prose — every string lands through
   textContent. */

(function (JL) {
  const dom = {
    query: document.getElementById("bv-query"),
    status: document.getElementById("bv-status"),
    meta: document.getElementById("bv-meta"),
    gauge: document.getElementById("bv-gauge"),
    collect: document.getElementById("bv-collect"),
    analyze: document.getElementById("bv-analyze"),
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

  function sentimentCounts(articles) {
    const tally = {};
    articles.forEach((article) => {
      const name = article.sentiment;
      if (name) tally[name] = (tally[name] || 0) + 1;
    });
    return tally;
  }

  function summary(brief) {
    const articles = brief.articles || [];
    dom.query.textContent = brief.query || brief.slug;
    dom.status.className = JL.statusClass(brief.status);
    dom.status.textContent = String(brief.status || "empty");
    dom.meta.textContent = [
      articles.length + " articles",
      "last " + brief.period_days + " days",
      (brief.lang || []).join(" + ") || "no editions",
      "updated " + JL.shortDate(brief.updated),
    ].join(" · ");
    gauge(JL.counts(sentimentCounts(articles)));
  }

  function buttons(brief) {
    const has = (brief.articles || []).length > 0;
    dom.collect.textContent = has ? "Re-collect" : "Collect";
    dom.analyze.textContent = brief.status === "analyzed" ? "Re-analyze" : "Analyze";
    dom.analyze.disabled = !has;
  }

  // -- actions -------------------------------------------------------------
  function paint(brief) {
    current = brief;
    summary(brief);
    buttons(brief);
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

  dom.collect.addEventListener("click", collect);
  dom.analyze.addEventListener("click", analyze);

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
