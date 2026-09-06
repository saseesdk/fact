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
    const data = await verifyText(info.selectionText);
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
  verifyText(message.text)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) =>
      sendResponse({
        ok: false,
        error: err.message || "Could not reach the local Fact Check server. Is app.py running?",
      })
    );
  return true; // keep the message channel open for the async response
});
