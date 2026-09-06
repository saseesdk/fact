# Fact Check — browser extension (Phase 5 MVP)

A Manifest V3 Chrome extension over the same local backend (`src/app.py`)
used by the web UI (`src/page/index.html`) — no new logic, just a second
front end for the same `verify_text()` pipeline.

## Setup

1. Start the backend first (it must be running on `127.0.0.1:5000` before
   the extension can do anything):
   ```
   cd D:\PROGRAMMING\fact
   venv\Scripts\python src\app.py
   ```
2. In Chrome, go to `chrome://extensions`, enable **Developer mode** (top
   right), click **Load unpacked**, and select this `extension/` folder.

## Usage

- **Select text on any page, right-click, "Verify with Fact Check"** — a
  floating panel appears in the top-right corner with the verdict for each
  checkable claim in the selection.
- **Click the toolbar icon** for a popup where you can paste/type text
  directly, for text that isn't already on a page.

## What this does NOT do yet

- No inline highlighting of individual sentences on the page itself (the
  original ideation deck's vision) — results show in a summary panel
  instead. Real inline highlighting needs matching each verified sentence
  back to its exact location in the page DOM (handling text split across
  multiple elements, hidden text, etc.) — a real chunk of work, deliberately
  deferred rather than half-built.
- No page-level overall accuracy score (deck's "verdict for the whole
  paragraph") — each claim shows its own verdict only.
- Backend must be running locally (`127.0.0.1:5000`) — this does not call
  any hosted/deployed version, since none exists yet (see `docs/ROADMAP.md`
  Phase 4).
