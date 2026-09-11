const input = document.getElementById("input");
const runBtn = document.getElementById("run");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

function escapeHtml(text) {
  // Escapes quotes too, since this also ends up inside href="..."
  // attributes below (see renderSourcesHtml) — those come from third-party
  // search results, so an unescaped quote there could break attribute
  // quoting rather than just being displayed as text.
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Clickable source link(s) where a URL is available (issue #18), falling
// back to plain text otherwise. Only http(s) URLs are linked.
function renderSourcesHtml(r) {
  if (r.sources && r.sources.length) {
    return r.sources
      .map((s) =>
        s.url && /^https?:\/\//i.test(s.url)
          ? `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title)}</a>`
          : escapeHtml(s.title)
      )
      .join(", ");
  }
  return r.matched_sources?.length ? escapeHtml(r.matched_sources.join(", ")) : "";
}

function renderResults(data) {
  if (!data.verified || data.verified.length === 0) {
    resultsEl.innerHTML = `<p class="empty">No checkable factual claims found.</p>`;
    return;
  }
  resultsEl.innerHTML = data.verified
    .map((r) => {
      const sourcesHtml = renderSourcesHtml(r);
      const sources = sourcesHtml ? `<span class="sources">Source: ${sourcesHtml}</span>` : "";
      return `
        <div class="claim">
          <div class="claim-text">${escapeHtml(r.claim)}</div>
          <div class="verdict ${r.verdict}">
            <span class="verdict-label">${r.verdict.replace("_", " ")} (${r.confidence})</span>
            <span>${escapeHtml(r.explanation)}</span>
            ${sources}
          </div>
        </div>
      `;
    })
    .join("");
}

async function run() {
  const text = input.value;
  if (!text.trim()) return;
  runBtn.disabled = true;
  statusEl.textContent = "Checking… can take a minute or two (runs fully offline).";
  resultsEl.innerHTML = "";

  chrome.runtime.sendMessage({ type: "FACTCHECK_VERIFY_TEXT", text }, (response) => {
    runBtn.disabled = false;
    if (chrome.runtime.lastError) {
      statusEl.textContent = "";
      resultsEl.innerHTML = `<p class="error-text">Failed: ${escapeHtml(chrome.runtime.lastError.message)}</p>`;
      return;
    }
    if (!response.ok) {
      statusEl.textContent = "";
      resultsEl.innerHTML = `<p class="error-text">Failed: ${escapeHtml(response.error)}</p>`;
      return;
    }
    statusEl.textContent = "";
    renderResults(response.data);
  });
}

runBtn.addEventListener("click", run);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run();
});
