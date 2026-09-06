# Fact Check — prototype

Verifies factual claims in text against real evidence, fully local and
free (no paid API, no external LLM call — the only outside dependency is a
free-tier search API key). See **`docs/ARCHITECTURE.md`** for a full
file-by-file explanation of how this works and what each file does — read
that first if you're new here. `docs/ROADMAP.md` is the long-term plan;
`docs/PROGRESS.md` is a running log of what's been tried, found, and
decided session by session.

Current setup: general-domain claims (not restricted to any one topic),
searched via **LangSearch** (a web search API), compared using a local NLI
model. See `docs/PROGRESS.md` for why LangSearch alone right now, and a
real limitation found with it (it can return a page merely *using* a
trusted name like "Wikipedia" without actually being that site).

## Setup

Use the project's own virtualenv (kept separate from any other project's
env on this machine — torch/transformers are heavy). This is a Windows
machine, so the venv uses `Scripts/`, not `bin/`:

```bash
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
./venv/Scripts/python -m spacy download en_core_web_sm
```

First run downloads two NLI models (~370MB each) from Hugging Face and
caches them under `~/.cache/huggingface`; subsequent runs are offline. The
spaCy model (~13MB, used for concept extraction) is a separate one-time
download via the command above, not covered by `pip install`.

**LangSearch API key required**: sign up for a free-tier key at
[langsearch.com](https://langsearch.com), then create a `.env` file in the
repo root (gitignored, never committed) containing:

```
LANGSEARCH_API_KEY=your-key-here
```

Without this, retrieval returns no evidence and every claim resolves to
`insufficient_evidence`.

## Usage

Check a single claim:

```bash
venv/Scripts/python src/verify.py "The capital of Australia is Sydney"
```

Check a full paragraph — sentences are split, filtered to just the
checkable factual claims, and only those are verified; everything else is
returned separately as `skipped_non_factual`:

```bash
venv/Scripts/python src/verify.py "The capital of Australia is Sydney. This is a beautiful country. The economy is on fire right now."
```

Run the test suites (each prints a pass rate):

```bash
venv/Scripts/python src/test_claims.py          # 16 general-domain claims
venv/Scripts/python src/test_verify_medical.py  # 14 medical claims
venv/Scripts/python src/test_claim_filter.py           # fact/opinion filter only
venv/Scripts/python src/test_claim_filter_medical.py   # fact/opinion filter, medical style
venv/Scripts/python src/test_local_classifier.py       # comparison step, no network
```

## Web UI

```bash
venv/Scripts/python src/app.py
```

Then open `http://127.0.0.1:5000`. Paste text, see it split into checkable
claims vs. everything else, click "Verify" on any claim to run the full
pipeline. Each verdict has a "Show what happened behind the scenes" toggle
— the actual trace: concepts extracted, which searches were tried and
which hit, every source's raw scores, whether the trust-gate check passed.
No verdict is a black box.

## Repo layout

```
src/            active source code + test scripts + fixtures + web UI
  json/         test fixtures (claims + expected verdicts)
  page/         web UI (single static HTML page, no build step)
legacy/         retrieval modules not currently wired in (see docs/PROGRESS.md)
docs/
  ARCHITECTURE.md   file-by-file explanation + pipeline flow (read this first)
  ROADMAP.md        long-term phase plan
  PROGRESS.md       running log of what's been tried/found/decided
```

## What this does NOT do yet

- No caching, no database, no auth.
- No page-text ingestion (HTML stripping, boilerplate removal) — input is
  already plain text.
- No source-trust verification — a search result can use a well-known
  site's name without actually being that site, and nothing currently
  catches this (see `docs/PROGRESS.md`).
- No structured drug-dosage source — precise numeric dosage-safety claims
  correctly resolve to `insufficient_evidence` rather than a guess, since
  general web prose rarely states exact thresholds.
