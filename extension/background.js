// Service worker: owns the context menu and every network call to the
// local backend. All fetches happen here (not in content.js or popup.js)
// because a background/extension-page context is what actually gets the
// host_permissions cross-origin bypass in Manifest V3 — routing every
// request through one place avoids relying on that being true everywhere.

const API_BASE = "http://127.0.0.1:5000";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "verify-selection",
    title: 'Verify with Fact Check: "%s"',
    contexts: ["selection"],
  });
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

async function verifyText(text) {
  const res = await fetch(`${API_BASE}/api/verify_text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Server error (${res.status})`);
  }
  return res.json();
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "verify-selection" || !info.selectionText || !tab?.id) return;

  chrome.tabs.sendMessage(tab.id, { type: "FACTCHECK_LOADING" });
  try {
    const data = await withServiceWorkerKeepAlive(verifyText(info.selectionText));
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
  withServiceWorkerKeepAlive(verifyText(message.text))
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) =>
      sendResponse({
        ok: false,
        error: err.message || "Could not reach the local Fact Check server. Is app.py running?",
      })
    );
  return true; // keep the message channel open for the async response
});
