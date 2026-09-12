// Service worker: owns the context menu and every network call to the
// local backend. All fetches happen here (not in content.js or popup.js)
// because a background/extension-page context is what actually gets the
// host_permissions cross-origin bypass in Manifest V3 — routing every
// request through one place avoids relying on that being true everywhere.

const API_BASE = "http://127.0.0.1:5000";

chrome.runtime.onInstalled.addListener((details) => {
  chrome.contextMenus.create({
    id: "verify-selection",
    title: 'Verify with Fact Check: "%s"',
    contexts: ["selection"],
  });
  // Only on a fresh install, not every update/reload while developing —
  // nobody wants a tab popping open every time the extension reloads.
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("onboarding.html") });
  }
});

// MV3 service workers get torn down by Chrome after ~30s of being
// considered "idle" — a pending fetch() alone doesn't reliably count as
// activity that resets that timer. Our backend is CPU-only local model
// inference and routinely takes well over 30s per request (confirmed
// directly: the panel got stuck on "Checking…" forever even though the
// server logged a clean 200 — the worker had already been killed by the
// time the response came back, so it never delivered the result message).
// Fix: keep issuing a harmless extension API call every few seconds while
// a request is in flight, which does reset Chrome's idle timer.
function withServiceWorkerKeepAlive(promise) {
  const heartbeat = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 15000);
  return promise.finally(() => clearInterval(heartbeat));
}

async function fetchJSON(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.error || `Server error (${res.status})`);
  }
  return res.json();
}

// Verifies claim-by-claim (same two endpoints the web UI already uses:
// /api/segregate then /api/verify per claim) instead of one opaque
// /api/verify_text call, specifically so progress can be reported as each
// claim finishes — a single one-shot call has no way to say "3 of 7 done"
// partway through. onProgress is called once up front with the total (as
// soon as segregation finishes) and once per claim after it resolves.
async function verifyTextWithProgress(text, onProgress) {
  const seg = await fetchJSON("/api/segregate", { text });
  const claims = seg.claims.map((c) => c.sentence);
  const skipped = seg.non_claims.map((c) => c.sentence);
  const total = claims.length;
  const verified = [];
  onProgress({ done: 0, total, latest: null });
  for (const claim of claims) {
    const result = await fetchJSON("/api/verify", { claim });
    verified.push(result);
    onProgress({ done: verified.length, total, latest: result });
  }
  return { verified, skipped_non_factual: skipped };
}

// content.js is NOT declared in manifest.json's content_scripts anymore —
// a static declaration only auto-runs on new page loads, so a tab that was
// already open before the extension was loaded/reloaded would never get
// it, and sendMessage to that tab would fail with "Could not establish
// connection. Receiving end does not exist." (confirmed directly).
// Injecting it here, right before use, means it's always there regardless
// of when the page was opened. content.js itself guards against being
// initialized twice if this runs again on the same tab.
async function ensureContentScriptInjected(tabId) {
  try {
    await chrome.scripting.insertCSS({ target: { tabId }, files: ["content.css"] });
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  } catch (e) {
    // Fails on pages content scripts can never run on (chrome://, the Web
    // Store, etc.) — the context menu item still shouldn't have been
    // reachable there, but degrade quietly rather than throw.
  }
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "verify-selection" || !info.selectionText || !tab?.id) return;

  await ensureContentScriptInjected(tab.id);
  chrome.tabs.sendMessage(tab.id, { type: "FACTCHECK_LOADING" });
  try {
    const data = await withServiceWorkerKeepAlive(
      verifyTextWithProgress(info.selectionText, (progress) =>
        chrome.tabs.sendMessage(tab.id, { type: "FACTCHECK_PROGRESS", ...progress })
      )
    );
    chrome.tabs.sendMessage(tab.id, { type: "FACTCHECK_RESULT", data });
  } catch (err) {
    chrome.tabs.sendMessage(tab.id, {
      type: "FACTCHECK_ERROR",
      error: err.message || "Could not reach the local Fact Check server. Is app.py running?",
    });
  }
});

// The popup can't reach 127.0.0.1 without going through this same
// privileged fetch path, so it asks the background worker to do it too.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "FACTCHECK_VERIFY_TEXT") return false;
  withServiceWorkerKeepAlive(
    verifyTextWithProgress(message.text, (progress) =>
      // Fire-and-forget broadcast to whichever popup is currently open. No
      // listener (popup closed) just means this promise rejects; swallow
      // it — the popup only cares about progress while it's visible.
      chrome.runtime.sendMessage({ type: "FACTCHECK_PROGRESS", ...progress }).catch(() => {})
    )
  )
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) =>
      sendResponse({
        ok: false,
        error: err.message || "Could not reach the local Fact Check server. Is app.py running?",
      })
    );
  return true; // keep the message channel open for the async response
});
