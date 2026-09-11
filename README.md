# Factual Verification Extension — Prototype Stage

Full context and roadmap: `Factual_Verification_Extension_Master_Plan.docx` (on Desktop).

This repo currently contains only the **Phase 2 prototype** from that plan:
a standalone script that proves out the core loop — `claim -> evidence retrieval -> verdict`
— before any backend API, database, or Chrome extension gets built.

Current domain: **medical claims only** (see `ROADMAP.md` Phase 1), checked
against MedlinePlus (`medical_retrieval.py`) — a National Library of
Medicine / NIH source, picked over Wikipedia for medical claims specifically
because it's authored and reviewed by health professionals, not open
community editing. Other domains (general trivia via the older
`retrieval.py`, programming docs, PubMed for research-specific claims) can
be wired back in later as separate retrieval modules with the same
`retrieve_evidence()` shape.

Claim segregation (fact vs. opinion) uses a dedicated zero-shot model
(`MoritzLaurer/deberta-v3-base-zeroshot-v2.0`, `claim_filter.py`).
Claim-vs-evidence verdict classification uses a separate NLI model trained
on FEVER (`MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`, `local_classifier.py`)
— the "claim + evidence -> supports/refutes/not enough info" task, which
maps directly onto our verdict categories. Both are CPU-only, ~200M params
or less, no API key, no external LLM, no per-call cost, fully offline after
the first download.

## Development guide
#### Branches
- master — Production-ready code. Permanent branch.
- develop — Testing/integration branch. Permanent branch.
- feature_* — Temporary branches for new features, fixes, or changes.
  
#### Workflow
1. Always create a new feature_* branch from the latest master.
2. Do all development and individual testing on the feature branch.
3. Once testing is complete, create a PR and merge the feature branch into develop.
4. Admin tests the changes on develop.
5. If issues are found, fix them on the feature branch, retest, and merge the changes back into develop.
6. Once both admins agree on the changes, merge develop into master.
7. master is then deployed to production.

#### Rules
- Do not develop directly on master or develop.
- Keep feature branches focused on a single change.
- Use clear commit messages and branch names.
- Resolve all conflicts and ensure tests pass before merging.
- master must always remain production-ready.

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
