// Injected on demand by background.js (chrome.scripting.executeScript),
// right when "Verify with Fact Check" is clicked — not declared statically
// in manifest.json, since a static content_scripts entry only auto-runs on
// NEW page loads. A page already open before the extension was
// loaded/reloaded would never get it, and background.js's sendMessage to
// that tab would fail with "Could not establish connection. Receiving end
// does not exist." — confirmed directly. Injecting on demand means it
// always works regardless of when the page was opened.
//
// Guarded against re-injection: clicking "Verify" again on the same page
// re-runs this whole file (executeScript doesn't know it's "already
// there"). Without this guard, a second run would redeclare everything and
// add a second message listener, double-handling every future message.
if (!window.__factcheckContentScriptLoaded) {
  window.__factcheckContentScriptLoaded = true;
  initFactCheckContentScript();
}

function initFactCheckContentScript() {

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
    setBody(
      `<p class="factcheck-status">Checking claims against local sources… this runs fully offline on your own machine and can take a minute or two per claim.</p>`
    );
  } else if (message.type === "FACTCHECK_RESULT") {
    renderResult(message.data);
  } else if (message.type === "FACTCHECK_ERROR") {
    setBody(`<p class="factcheck-status factcheck-error-text">Failed: ${escapeHtml(message.error)}</p>`);
  }
});

}
