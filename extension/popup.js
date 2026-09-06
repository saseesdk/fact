const input = document.getElementById("input");
const runBtn = document.getElementById("run");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderResults(data) {
  if (!data.verified || data.verified.length === 0) {
    resultsEl.innerHTML = `<p class="empty">No checkable factual claims found.</p>`;
    return;
  }
  resultsEl.innerHTML = data.verified
    .map((r) => {
      const sources = r.matched_sources?.length
        ? `<span class="sources">Source: ${escapeHtml(r.matched_sources.join(", "))}</span>`
        : "";
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
  statusEl.textContent = "Checking…";
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
