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

- **Select text on any page, right-click, "Verify with Fact Check"** —
  each verified sentence gets highlighted directly on the page, color-coded
  by verdict (green/red/yellow), and hovering one shows its confidence and
  which source it was compared against. A floating summary panel in the
  top-right also lists every claim. Sentences that were skipped as
  opinion/not checkable are left unhighlighted.
- **Click the toolbar icon** for a popup where you can paste/type text
  directly, for text that isn't already on a page (no inline highlighting
  in this case, since there's no page selection to highlight).

## How inline highlighting works

The page's text selection is gone by the time a result comes back (can
take 1-3 minutes) — it has to be captured as a live DOM `Range` the moment
"Verify" is clicked, then matched back to each verified sentence's exact
position once results arrive, then wrapped in a colored element
(`extension/content.js`, `highlightVerifiedSentences`). Handles a sentence
spanning multiple HTML elements (e.g. `<b>`/`<a>` mid-sentence) — verified
with a synthetic DOM test before shipping, not just assumed to work.
Sentences that can't be located in the page text exactly (rare whitespace/
formatting mismatches) are simply left unhighlighted rather than guessed
at; the summary panel still has them either way.

## What this does NOT do yet

- No page-level overall accuracy score (deck's "verdict for the whole
  paragraph") — each claim shows its own verdict only.
- Backend must be running locally (`127.0.0.1:5000`) — this does not call
  any hosted/deployed version, since none exists yet (see `docs/ROADMAP.md`
  Phase 4).
- Highlights aren't source-verified — a "Wikipedia"-named source could be
  a lookalike domain, not necessarily the real site (see `docs/PROGRESS.md`).
