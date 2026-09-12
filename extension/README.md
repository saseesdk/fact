# Fact Check — browser extension (Phase 5 MVP)

A Manifest V3 Chrome extension over the same local backend (`src/app.py`)
used by the web UI (`src/page/index.html`) — no new logic, just a second
front end over the same `/api/segregate` + `/api/verify` calls.

## Setup

1. Start the backend first (it must be running on `127.0.0.1:5000` before
   the extension can do anything):
   ```
   cd D:\PROGRAMMING\fact
   venv\Scripts\python src\app.py
   ```
2. In Chrome, go to `chrome://extensions`, enable **Developer mode** (top
   right), click **Load unpacked**, and select this `extension/` folder.
   A "How to use" tab (`onboarding.html`) opens automatically the first
   time it's installed — also reachable any time via the "How to use this
   extension" link at the bottom of the popup.

## Usage

- **Select text on any page, right-click, "Verify with Fact Check"** —
  a live progress bar ("Checking claim 3 of 7…") tracks claims as they
  finish, and each verified sentence gets highlighted directly on the page
  as soon as its own verdict is in (not all at once at the end), color-coded
  by verdict (green/red/yellow). Hovering a highlight shows its confidence
  and which source it was compared against. A floating summary panel in the
  top-right also lists every claim. Sentences that were skipped as
  opinion/not checkable are left unhighlighted.
- **Click the toolbar icon** for a popup where you can paste/type text
  directly, for text that isn't already on a page (no inline highlighting
  in this case, since there's no page selection to highlight — the popup
  still shows the same live progress bar).

## How the progress bar works

Claims are verified one at a time — `background.js` calls `POST
/api/segregate` once to split the text into checkable claims, then `POST
/api/verify` once per claim, in sequence (`verifyTextWithProgress`). Each
of those per-claim calls is what lets it report "N of total done" as it
goes, instead of the previous single `/api/verify_text` call that only
resolved once every claim was already checked, with no visibility into
which claim it was on or how many were left.

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
