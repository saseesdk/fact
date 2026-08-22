# Factual Verification Extension — Prototype Stage

Full context and roadmap: `Factual_Verification_Extension_Master_Plan.docx` (on Desktop).

This repo currently contains only the **Phase 2 prototype** from that plan:
a standalone script that proves out the core loop — `claim -> evidence retrieval -> verdict`
— before any backend API, database, or Chrome extension gets built.

First domain: **general/trivia facts**, checked against Wikipedia (the plan's
Tier-1 source list). Narrower domains (programming docs, medical/PubMed) can
be added later as separate retrieval modules with the same `retrieve_evidence()`
shape.

Classification is fully local and free: a small open-source NLI model
(`MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`, ~200M params, CPU-only, no
GPU needed) trained on FEVER — the "claim + evidence -> supports/refutes/not
enough info" dataset, which maps directly onto our verdict categories. No API
key, no external LLM, no per-call cost, runs offline after the first model
download.

## Setup

Use the project's own virtualenv (kept separate from any other project's env
on this machine — torch/transformers are heavy and don't belong in unrelated
repos). This is a Windows machine, so the venv uses `Scripts/`, not `bin/`:

```bash
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
```

First run downloads the NLI model (~370MB) from Hugging Face and caches it
under `~/.cache/huggingface`; subsequent runs are offline.

## Usage

Check a single claim:

```bash
cd prototype
../venv/Scripts/python verify.py "The capital of Australia is Sydney"
```

Check a full paragraph — sentences are split, filtered to just the checkable
factual claims (`claim_filter.py`), and only those are verified; everything
else is returned separately as `skipped_non_factual`:

```bash
../venv/Scripts/python verify.py "The capital of Australia is Sydney. This is a beautiful country. The economy is on fire right now."
```

Run the hand-picked verification test set (8 true / 6 false / 4
subjective-or-unverifiable claims) and get a pass rate:

```bash
../venv/Scripts/python test_claims.py
```

Run the fact/opinion filter test set (15 sentences: facts, opinions,
metaphors, predictions) and get a pass rate:

```bash
../venv/Scripts/python test_claim_filter.py
```

## Claim segregation UI

A minimal local web UI for Phase 1 of the roadmap (see `ROADMAP.md`): paste
in any text and see it partitioned into checkable factual claims vs.
everything else, using the same filter as above. This is deliberately
segregation-only for now — no retrieval, no verdicts yet.

```bash
cd prototype
../venv/Scripts/python app.py
```

Then open `http://127.0.0.1:5000` in a browser. Backend is a single Flask
route (`/api/segregate`) over `claim_filter.segregate()`; frontend is a
static page in `prototype/ui/` with no build step.

## Phase 3: fact/opinion filtering — calibration notes

The filter reuses the same NLI model as a zero-shot classifier rather than
adding a second model. Getting it to behave took real calibration, documented
at the top of `claim_filter.py`:

- A 3-way split (fact / opinion / metaphor) could not reliably detect
  metaphor at all (0/4) — general-purpose NLI has no real signal for
  figurative language. Collapsed to a 2-way fact/opinion split instead,
  since the pipeline only needs to *exclude* non-checkable statements, not
  correctly label *why*.
- Confidence margins are often razor-thin even for canonical facts — "The
  capital of France is Paris" scored fact=0.148 vs opinion=0.185, a near
  coin flip that a bare argmax would silently misfile as an opinion and
  drop from verification entirely. Fixed by failing **open**: only exclude a
  sentence when opinion clearly beats fact by a margin (`OPINION_MARGIN`).
  Silently skipping a real claim is worse than spending a verification
  cycle on a borderline one, which just resolves to `insufficient_evidence`.
- Remaining known misses (80% on the test set): future-tense predictions
  read as "opinion," and short idioms ("time is money") read as literal
  fact. Both are open questions the master plan itself calls out, not bugs.

## What this does NOT do yet

- No caching, no API wrapper, no extension, no database.
- No page-text ingestion (HTML stripping, boilerplate removal) — input is
  already plain text.
- Retrieval is naive (raw claim text as the Wikipedia search query), which
  is the other known weak point from Phase 2 validation — see the git
  history / prior conversation for the specific misses (e.g. a claim
  matching a page about someone's discredited belief rather than an
  authoritative source).

## Next steps

1. Wrap `verify()`/`verify_text()` in a FastAPI endpoint (Phase 4).
2. Build the Chrome extension (Manifest V3) that sends page text to the API
   and highlights results (Phase 5).
3. Improve retrieval (prefer exact Wikipedia title match over full-text
   search; pull fuller article text, not just the intro summary).
