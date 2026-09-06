// Injected on every page. Listens for messages from background.js
// (triggered by the right-click "Verify with Fact Check" context menu) and
// renders a floating results panel directly on the page — no full-page
// inline highlighting yet (see extension/README.md), just a clear summary
// panel, matching Phase 5's "popup with a page-level accuracy score" goal
// from ROADMAP.md as a first cut.

let panel = null;

function ensurePanel() {
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "factcheck-panel";
  panel.innerHTML = `
    <div class="factcheck-header">
      <span>Fact Check</span>
      <button class="factcheck-close" aria-label="Close">&times;</button>
    </div>
    <div class="factcheck-body"></div>
  `;
  document.documentElement.appendChild(panel);
  panel.querySelector(".factcheck-close").addEventListener("click", () => {
    panel.remove();
    panel = null;
  });
  return panel;
}

function setBody(html) {
  ensurePanel().querySelector(".factcheck-body").innerHTML = html;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderResult(data) {
  if (!data.verified || data.verified.length === 0) {
    setBody(
      `<p class="factcheck-empty">No checkable factual claims found in the selected text.</p>`
    );
    return;
  }

  const claims = data.verified
    .map((r) => {
      const sources = r.matched_sources?.length
        ? `<div class="factcheck-sources">Source: ${escapeHtml(r.matched_sources.join(", "))}</div>`
        : "";
      return `
        <div class="factcheck-claim">
          <div class="factcheck-claim-text">${escapeHtml(r.claim)}</div>
          <div class="factcheck-verdict factcheck-${r.verdict}">
            <span class="factcheck-verdict-label">${r.verdict.replace("_", " ")} (${r.confidence})</span>
            <span>${escapeHtml(r.explanation)}</span>
            ${sources}
          </div>
        </div>
      `;
    })
    .join("");

  const skippedNote = data.skipped_non_factual?.length
    ? `<p class="factcheck-skipped">${data.skipped_non_factual.length} sentence(s) skipped as opinion/not checkable.</p>`
    : "";

  setBody(claims + skippedNote);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "FACTCHECK_LOADING") {
    setBody(`<p class="factcheck-status">Checking claims against local sources…</p>`);
  } else if (message.type === "FACTCHECK_RESULT") {
    renderResult(message.data);
  } else if (message.type === "FACTCHECK_ERROR") {
    setBody(`<p class="factcheck-status factcheck-error-text">Failed: ${escapeHtml(message.error)}</p>`);
  }
});
