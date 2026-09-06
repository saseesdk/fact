# Architecture — what each file does, and how a claim flows through them

Read this first if you're new to the repo. `README.md` has setup/run
commands; `ROADMAP.md` is the long-term phase plan; `PROGRESS.md` is a
running log of what's been tried and found. This file explains **what the
code actually does today** — one section per file, then the end-to-end
flow tying them together.

## The pipeline, in order

```
raw text
   │
   ▼
split into sentences ─────────────────────────── claim_filter.py
   │
   ▼
keep only checkable factual sentences ────────── claim_filter.py (model #1)
   │                                              (drops opinions/subjective lines)
   ▼
for each factual sentence:
   │
   ├─ pull out the actual topic ─────────────────  concept_extraction.py
   │   e.g. "The capital of Australia is Sydney"
   │        -> ["Australia", "Sydney", "The capital"]
   │
   ├─ search the web with that topic ─────────────  websearch_retrieval.py
   │   (tries each concept as a query, most useful first, via LangSearch)
   │        │
   │        └─ query building shared with other sources ── query_strategy.py
   │        └─ word-list helper used by two files ───────── keywords.py
   │
   ├─ drop non-English results ────────────────────  websearch_retrieval.py
   │
   ├─ compare claim against each result ───────────  local_classifier.py (model #2)
   │   scores: entailment / contradiction / neutral
   │
   ├─ sanity-check the winner ─────────────────────  local_classifier.py
   │   (do the claim's own numbers/extra topics actually
   │    appear in the evidence, or is this just topical noise?)
   │
   ▼
final verdict: supported / contradicted / insufficient_evidence
   │
   ▼
verify.py ties all of the above into one call: verify(claim)
   │
   ▼
app.py exposes it over HTTP for the web UI (src/page/index.html)
```

## File-by-file

### Entry points

- **`src/verify.py`** — the actual pipeline, start to finish. `verify(claim)`
  runs one sentence through every step above and returns a verdict dict.
  `verify_text(text)` runs a whole paragraph: splits it, filters to
  checkable claims, calls `verify()` on each. Also runnable directly:
  `python src/verify.py "some claim"`.
- **`src/app.py`** — Flask backend exposing `verify.py` over HTTP for the
  web UI: `POST /api/segregate` (fact/opinion split only, fast),
  `POST /api/verify` (one claim, full pipeline), `POST /api/verify_text`
  (whole paragraph, used by the browser extension on other branches).
  `GET /` serves the web UI page itself.

### Step 1 — sentence splitting + fact/opinion filter

- **`src/claim_filter.py`** — `split_sentences()` breaks raw text into
  sentences (plain regex, handles real-world pasted-web-content quirks like
  missing whitespace at heading boundaries). `segregate()`/
  `extract_factual_claims()` then run **model #1**
  (`deberta-v3-base-zeroshot-v2.0`, zero-shot classifier) to keep only
  sentences that are checkable facts, dropping opinions/subjective
  statements. Fails "open" — a borderline sentence is kept rather than
  dropped, since a wasted verification cycle is cheaper than silently
  losing a real claim.

### Step 2 — find the actual topic (not the raw sentence)

- **`src/concept_extraction.py`** — `extract_concepts(claim)` uses spaCy
  (`en_core_web_sm`) to pull out the claim's real noun phrases, ranked
  proper-nouns-first then by specificity, e.g. "Antibiotics do not work
  against viral infections like the common cold" ->
  `['viral infections', 'the common cold', 'Antibiotics']`. Exists because
  searching with the full raw sentence routinely fails or matches the wrong
  page — a search engine needs a topic, not a sentence.
- **`src/keywords.py`** — a shared stopword list + `keywords()` helper, used
  by both `concept_extraction.py`-adjacent code and the trust-gate check in
  `local_classifier.py`.
- **`src/query_strategy.py`** — turns a claim into a prioritized list of
  search queries (each concept tried individually, most useful first, with
  a leading bare number like "10" stripped since search engines treat it as
  just another word, not a dosage). Shared by every retrieval module so
  they all search the same way.

### Step 3 — find evidence

- **`src/websearch_retrieval.py`** — the active evidence source. Calls
  LangSearch (a web search API, needs `LANGSEARCH_API_KEY` in a local
  `.env`, gitignored) using the query strategy above, then drops any
  non-English result before it can reach the classifier (LangSearch has no
  language filter of its own and returns pages in any language).
- **`legacy/medical_retrieval.py`** (MedlinePlus) and **`legacy/retrieval.py`**
  (direct Wikipedia) — earlier evidence sources, **not currently used** by
  `verify.py` (see `PROGRESS.md` for why: LangSearch-only was chosen over
  the multi-source setup these belong to). Kept because they're real,
  tested code that might get re-activated later, not because they're
  needed right now.

### Step 4 — compare claim vs. evidence, decide the verdict

- **`src/local_classifier.py`** — **model #2**
  (`DeBERTa-v3-base-mnli-fever-anli`, an NLI model). For each piece of
  evidence, scores how much it entails / contradicts / says-nothing-about
  the claim. Before trusting a high entailment/contradiction score, checks
  the evidence actually addresses the claim's *specific* details (its
  numbers, its secondary concepts) — this is what stops a page that's
  merely *about the same topic* from being mistaken for real support or
  refutation. If two sources disagree, that conflict is surfaced as
  `insufficient_evidence` rather than picked between.

### Tests and fixtures

- **`src/test_claims.py`** + **`src/json/claims.json`** — 16 general-domain
  claims, hand-labeled, run through the whole pipeline for a pass rate.
- **`src/test_verify_medical.py`** + **`src/json/medical_claims_test.json`**
  — 14 medical claims, same idea.
- **`src/test_claim_filter.py`** / **`src/test_claim_filter_medical.py`** +
  their `src/json/*.json` fixtures — test the fact/opinion filter alone
  (model #1), not the full pipeline.
- **`src/test_local_classifier.py`** — deterministic unit tests for the
  comparison step (model #2) using synthetic evidence, no network calls.

### Frontend

- **`src/page/index.html`** — the web UI: paste text, see it split into
  claims vs. non-claims, click "Verify" per claim, see the verdict plus a
  "show what happened behind the scenes" trace (which queries were tried,
  every source's raw scores).

## Why LangSearch alone, right now

Earlier versions fanned out to MedlinePlus + Wikipedia + LangSearch
together and scored higher on both test sets. The switch to LangSearch-only
was a deliberate simplicity/speed tradeoff, not an accuracy upgrade — full
comparison numbers and the reasoning are in `PROGRESS.md`, along with a
real trust problem found during this: LangSearch can return a page that
merely uses a trusted name (e.g. a site titled "... - Wikipedia" on a
domain that isn't actually `wikipedia.org`) without any way for us to tell
the difference yet.
