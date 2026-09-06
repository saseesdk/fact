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
let tooltipEl = null;

// The page's Selection is gone by the time verify() resolves (can take
// 1-3 minutes — the user isn't holding the selection that whole time, and
// clicking a context menu item doesn't require keeping it anyway). It has
// to be captured as a live Range the moment "Verify" is clicked, not read
// again later. Re-captured on every FACTCHECK_LOADING message (not just
// once at injection) so a second "Verify" click on the same already-open
// page picks up the NEW selection, not the first one.
let capturedRange = null;

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

// ---- Inline highlighting -------------------------------------------------
//
// Walks the captured Range's text nodes into one flat string ("fullText")
// with a map back to (node, offsetWithinNode) for every character, so each
// verified sentence — which we only have as a plain string — can be
// located and converted back into a real DOM Range, then wrapped in a
// colored element. Sentences that were skipped (opinions/not checkable)
// are simply never looked up, so they're left as plain, unhighlighted text
// — only what was actually verified gets a color, so the signal stays
// meaningful.

function buildTextMap(range) {
  const root = range.commonAncestorContainer;
  const walkRoot = root.nodeType === Node.TEXT_NODE ? root.parentNode : root;
  const walker = document.createTreeWalker(walkRoot, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (range.intersectsNode(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });

  let fullText = "";
  const segments = []; // { node, nodeStart, fullStart, fullEnd }
  let node;
  while ((node = walker.nextNode())) {
    const text = node.textContent;
    let nodeStart = 0;
    let nodeEnd = text.length;
    if (node === range.startContainer) nodeStart = range.startOffset;
    if (node === range.endContainer) nodeEnd = range.endOffset;
    if (nodeStart >= nodeEnd) continue;
    const slice = text.slice(nodeStart, nodeEnd);
    segments.push({ node, nodeStart, fullStart: fullText.length, fullEnd: fullText.length + slice.length });
    fullText += slice;
  }
  return { fullText, segments };
}

function offsetToPoint(segments, charOffset) {
  for (const seg of segments) {
    if (charOffset >= seg.fullStart && charOffset <= seg.fullEnd) {
      return { node: seg.node, offset: seg.nodeStart + (charOffset - seg.fullStart) };
    }
  }
  return null;
}

function makeSubRange(segments, start, end) {
  const startPoint = offsetToPoint(segments, start);
  const endPoint = offsetToPoint(segments, end);
  if (!startPoint || !endPoint) return null;
  const r = document.createRange();
  r.setStart(startPoint.node, startPoint.offset);
  r.setEnd(endPoint.node, endPoint.offset);
  return r;
}

function wrapRange(range, item) {
  // A custom (unknown) element name, not <span>/<mark>, so the host page's
  // own CSS (which might target span/mark broadly) can't accidentally
  // restyle or break these — browsers render unknown elements as plain
  // inline boxes by default, and our CSS only ever targets this exact tag.
  const el = document.createElement("factcheck-mark");
  el.className = "factcheck-highlight factcheck-highlight-" + item.verdict;
  const frag = range.extractContents();
  el.appendChild(frag);
  range.insertNode(el);
  el.addEventListener("mouseenter", () => showTooltip(el, item));
  el.addEventListener("mouseleave", hideTooltip);
  return el;
}

function highlightVerifiedSentences(range, verified) {
  if (!range) return; // nothing was selected (e.g. triggered from the popup, not a page selection)
  const { fullText, segments } = buildTextMap(range);

  const matches = [];
  let cursor = 0;
  for (const item of verified) {
    const sentence = (item.claim || "").trim();
    if (!sentence) continue;
    const idx = fullText.indexOf(sentence, cursor);
    if (idx === -1) continue; // couldn't find this exact text in the page (whitespace/formatting mismatch) - skip, panel still has it
    matches.push({ start: idx, end: idx + sentence.length, item });
    cursor = idx + sentence.length;
  }

  // Reverse order: each wrap mutates the DOM at its own position via
  // extractContents(), which only touches nodes at or after its own start.
  // Processing latest-in-document-order first means earlier matches' still
  // haven't been touched yet when their turn comes, so their (node,offset)
  // references — computed once up front from the untouched DOM — stay valid.
  matches
    .slice()
    .reverse()
    .forEach(({ start, end, item }) => {
      const subRange = makeSubRange(segments, start, end);
      if (!subRange) return;
      try {
        wrapRange(subRange, item);
      } catch (e) {
        // DOM shape didn't allow wrapping here (e.g. a sentence spanning
        // into a <table>/<select> boundary) - skip silently, the panel is
        // still the source of truth regardless.
      }
    });
}

function ensureTooltip() {
  if (tooltipEl) return tooltipEl;
  tooltipEl = document.createElement("div");
  tooltipEl.id = "factcheck-tooltip";
  document.documentElement.appendChild(tooltipEl);
  return tooltipEl;
}

function showTooltip(target, item) {
  const el = ensureTooltip();
  const source = item.matched_sources?.length ? item.matched_sources.join(", ") : "no single matching source";
  el.innerHTML = `
    <div class="factcheck-tooltip-verdict factcheck-${item.verdict}">${item.verdict.replace("_", " ")} (${item.confidence})</div>
    <div class="factcheck-tooltip-explanation">${escapeHtml(item.explanation)}</div>
    <div class="factcheck-tooltip-source">Compared against: ${escapeHtml(source)}</div>
  `;
  const rect = target.getBoundingClientRect();
  el.style.left = `${Math.max(8, rect.left)}px`;
  el.style.top = `${rect.bottom + 6}px`;
  el.style.display = "block";
}

function hideTooltip() {
  if (tooltipEl) tooltipEl.style.display = "none";
}

// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "FACTCHECK_LOADING") {
    const sel = window.getSelection();
    capturedRange = sel && sel.rangeCount > 0 && !sel.isCollapsed ? sel.getRangeAt(0).cloneRange() : null;
    setBody(
      `<p class="factcheck-status">Checking claims against local sources… this runs fully offline on your own machine and can take a minute or two per claim.</p>`
    );
  } else if (message.type === "FACTCHECK_RESULT") {
    renderResult(message.data);
    if (message.data.verified?.length) {
      highlightVerifiedSentences(capturedRange, message.data.verified);
    }
  } else if (message.type === "FACTCHECK_ERROR") {
    setBody(`<p class="factcheck-status factcheck-error-text">Failed: ${escapeHtml(message.error)}</p>`);
  }
});

}
