const input = document.getElementById("input");
const runBtn = document.getElementById("run");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const progressEl = document.getElementById("progress");
const progressLabel = document.getElementById("progressLabel");
const progressFill = document.getElementById("progressFill");

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

function setProgress(done, total) {
  progressEl.hidden = false;
  const pct = total ? Math.round((done / total) * 100) : 0;
  progressFill.style.width = `${pct}%`;
  progressLabel.textContent =
    total === 0
      ? "No checkable claims found yet…"
      : done >= total
      ? `Finished checking ${total} claim(s).`
      : `Checking claim ${done + 1} of ${total}… (${pct}%)`;
}

// Broadcast from background.js as each claim's verdict comes back (see
// verifyTextWithProgress in background.js) — only reaches this listener
// while the popup is open, which is fine: the popup has nothing to update
// while it's closed anyway.
chrome.runtime.onMessage.addListener((message) => {
  if (message.type !== "FACTCHECK_PROGRESS") return;
  setProgress(message.done, message.total);
});

async function run() {
  const text = input.value;
  if (!text.trim()) return;
  runBtn.disabled = true;
  statusEl.textContent = "";
  resultsEl.innerHTML = "";
  progressEl.hidden = false;
  progressFill.style.width = "0%";
  progressLabel.textContent = "Finding checkable claims…";

  chrome.runtime.sendMessage({ type: "FACTCHECK_VERIFY_TEXT", text }, (response) => {
    runBtn.disabled = false;
    progressEl.hidden = true;
    if (chrome.runtime.lastError) {
      resultsEl.innerHTML = `<p class="error-text">Failed: ${escapeHtml(chrome.runtime.lastError.message)}</p>`;
      return;
    }
    if (!response.ok) {
      resultsEl.innerHTML = `<p class="error-text">Failed: ${escapeHtml(response.error)}</p>`;
      return;
    }
    renderResults(response.data);
  });
}

runBtn.addEventListener("click", run);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run();
});
