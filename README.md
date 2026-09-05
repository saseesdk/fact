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

## Setup

Use the project's own virtualenv (kept separate from any other project's env
on this machine — torch/transformers are heavy and don't belong in unrelated
repos). This is a Windows machine, so the venv uses `Scripts/`, not `bin/`:

```bash
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
./venv/Scripts/python -m spacy download en_core_web_sm
```

First run downloads the NLI model (~370MB) from Hugging Face and caches it
under `~/.cache/huggingface`; subsequent runs are offline. The spaCy model
(~13MB, used for concept extraction — `concept_extraction.py`) is a
separate one-time download via the command above, not covered by
`pip install -r requirements.txt`.

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

## Web UI

A minimal local web UI (see `ROADMAP.md` Phase 1/2): paste in any text, see
it partitioned into checkable factual claims vs. everything else
(`claim_filter.segregate()`), then click "Verify" on any claim to run full
retrieval + verdict (`verify()`). Each verdict has a "Show what happened
behind the scenes" toggle exposing the actual trace: concepts extracted from
the claim, which MedlinePlus searches were tried and which one hit, every
source's entailment/contradiction/neutral scores, and whether the
distinctive-terms check (see below) passed — the goal is that no verdict is
a black box.

```bash
cd prototype
../venv/Scripts/python app.py
```

Then open `http://127.0.0.1:5000` in a browser. Backend is two Flask routes
(`/api/segregate`, `/api/verify`) over `claim_filter.segregate()` and
`verify.verify()`; frontend is a static page in `prototype/ui/` with no
build step.

## How a verdict is actually reached (concept extraction + the trust gate)

Naively comparing a claim against whatever MedlinePlus page happens to match
its raw text is dangerous: an NLI model can score high entailment or
contradiction purely from general topical familiarity with a page, without
that page ever addressing what the claim specifically asserts — confirmed
directly, e.g. "Type 1 diabetes can be cured by drinking more water" scored
0.95 entailment against the Diabetes page, which never mentions "water" or
"cure" anywhere.

The pipeline now works in two stages instead of one direct compare:

1. **Concept extraction** (`concept_extraction.py`, spaCy noun chunks) pulls
   the claim's actual topical concepts, most content-rich first, and each is
   tried as its own MedlinePlus search term (`medical_retrieval.py`) — a
   single concept like "Type 1 diabetes" or "Sinusitis" finds the right page
   far more reliably than the raw sentence or a single bare keyword did.
   A leading bare quantity ("10 paracetamol") is stripped before searching,
   since MedlinePlus's keyword search has no concept of "10" as a dosage —
   it just treats it as a term to match, which surfaced unrelated pages.
2. **The distinctive-terms gate** (`local_classifier._addresses_claim_specifics`)
   is checked before accepting any "supported"/"contradicted" verdict: any
   number in the claim (dosage, year, statistic) must literally appear in the
   evidence, and any concept beyond the claim's primary one must contribute
   at least one term the evidence actually contains. Failing either downgrades
   the verdict to `insufficient_evidence` with an explanation, rather than
   reporting a confident verdict that's actually just lexical-overlap noise.

**Known remaining limitation:** this catches invented statistics/dates and
generic topical false positives, but MedlinePlus's consumer-health prose
usually doesn't state precise numeric thresholds (e.g. "how many tablets is
an overdose") even on the exact right page — that requires a structured
drug-label source (NIH DailyMed has one, confirmed reachable, not yet wired
in) rather than an encyclopedia article. Until then, dosage-specific safety
claims correctly resolve to `insufficient_evidence` rather than a guess.

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
- No PubMed integration yet for claims about a specific research finding
  (MedlinePlus only covers general consumer-health facts).
- No structured drug-dosage source (DailyMed) — see the limitation noted
  above; precise numeric dosage-safety claims stay `insufficient_evidence`.
- Retrieval can still occasionally surface a topically-adjacent-but-wrong
  page even after concept extraction — mitigated by the distinctive-terms
  gate and the conflict-detection branch in `local_classifier.py`, not
  eliminated. A real fix needs embedding-based relevance scoring, not string
  matching.

## Next steps

1. Wrap `verify()`/`verify_text()` in a FastAPI endpoint (Phase 4).
2. Build the Chrome extension (Manifest V3) that sends page text to the API
   and highlights results (Phase 5).
3. Wire in NIH DailyMed as a second medical source for dosage-specific
   claims, or PubMed for research-finding claims.
