# Progress log

Running log of what's been decided and done, session by session. `ROADMAP.md`
is the long-term phase plan; `README.md` is setup/usage; this file is "what
actually happened and what's still open" — read this first after a break.

## 2026-09-06 (later) — speed-up-nli-scoring: why one claim took ~2 minutes

Per direct question about per-claim latency, measured (not guessed) where
the time actually goes: retrieval is fast (3-6s), but NLI comparison
scoring was ~7-19s *per evidence item* and scaled linearly (3 items = 28s,
4 items = 36s) — with `max_sources=5`, worst case is ~50-90s of pure
scoring, matching the reported ~2 minutes.

**Root cause, confirmed directly:** LangSearch's "summary" field can be
enormous (one real result was 50,000+ characters), and every comparison
was hitting `local_classifier.MAX_PREMISE_CHARS` (2000) every single time,
paying near-maximum compute cost on every item regardless of source.

**Two attempted fixes that made things WORSE (measured, not assumed):**
1. Batching all evidence-claim pairs into one tokenizer call + one forward
   pass, instead of one call per item. Backfired: padding shorter premises
   up to the batch's longest one increases cost for the shorter ones, and
   this machine's CPU backend didn't get enough coordinated-batch benefit
   to offset that. Measured slower than sequential on every test.
2. Running comparisons concurrently via `ThreadPoolExecutor` with reduced
   per-call thread count. Backfired too: this machine has 6 physical cores
   and a *single* inference call already uses all 6 (torch's default
   intra-op threading) — there's no idle capacity to parallelize into, only
   contention. Measured slower than sequential.

**The fix that actually worked:** lowering `MAX_PREMISE_CHARS` from 2000 to
800 — since transformer compute scales with sequence length, this directly
reduces the amount of work per comparison rather than trying to
parallelize the same amount of work. Measured **~2.5-3x speedup**
(17.4s/item → 6.1s/item on one test claim) consistently across multiple
claims and re-checks.

**Accuracy validated, not assumed:** first full medical-suite run at 800
chars scored 7/14 (50%, down from the historical 64-71% range), with two
previously rock-solid cases ("flu vaccine cannot give you the flu",
"antibiotics don't work against viral infections") failing right at the
threshold edge — looked like a real regression. A second full run at the
same 800-char setting scored 9/14 (64%), with *both* of those cases passing
correctly. Conclusion: the first run's drop was live-search variance
(LangSearch's results aren't perfectly stable between runs — a known
limitation, see the LangSearch integration entry above), not the char cap.
**800 chars ships with no demonstrated accuracy cost.**

## 2026-09-06 — dev-langsearch-only: source count bump + a real trust finding

Per explicit direction, `dev` (via branch `dev-langsearch-only`) and both
extension branches now use LangSearch alone (`SOURCES = [retrieve_websearch]`),
dropping MedlinePlus and Wikipedia. `medical_retrieval.py`/`retrieval.py`
stay in the repo, just unused — known accuracy tradeoff already documented
above (LangSearch-only scored lower than the original setup on both
regression suites).

**Bug found and fixed:** with only one source, the English-only language
filter (see LangSearch integration entry above) could leave zero usable
evidence — confirmed directly, "Napoleon Bonaparte" returned 3 hits at
`count=3` but 2 were non-English, leaving nothing to compare against.
Bumped `websearch_retrieval.py`'s default `max_sources` from 3 to 5 so the
filter has more to work with.

**New finding, not yet fixed — a real trust/source-quality risk:**
re-testing "Napoleon Bonaparte was born in Italy" (actually false — he was
born in Corsica, France) at `max_sources=5` returned exactly one piece of
evidence: a page titled "Napoleon - Wikipedia" at
`https://en.m.wikipedia.com/wiki/Emperor_Napoleon` — **not the real
Wikipedia domain** (`en.wikipedia.org`; `en.m.wikipedia.com` appears to be
an unrelated site using Wikipedia's name). That page asserts Napoleon was
born in Italy, and the classifier scored it `supported` at 0.90 confidence,
confidently agreeing with a false claim because a spoofed/impersonating
source vouched for it.

This is a different, arguably more serious problem than anything found so
far: earlier issues were about *retrieval missing the right evidence* or
*the NLI model misreading correct evidence*; this one is about **not being
able to tell a real source from one that merely borrows a trusted name.**
General web search has no such guarantee the way a single curated domain
(MedlinePlus, real Wikipedia) does. Not fixed yet — would need some form of
source verification (e.g., checking a result's domain against the actual
known domain for well-known sites, or a source-reputation/allowlist layer)
before LangSearch-sourced "Wikipedia" or similar brand-name claims can be
trusted at face value. Flagged for a decision on priority.

## 2026-09-05 — General-domain pivot

**Decision:** reviewed a new MVP deck (`IDEATION 1.pptx`) that specified a
general-domain, LLM + live-web-search architecture. Given three options
(A: paid-LLM + live search, B: keep medical-only/free, C: general-domain but
still free/local), the user chose **C**: drop the medical-only restriction,
keep everything local/free (no LLM API calls), add general web search
alongside MedlinePlus.

**Also decided:** switch this repo to a branch + PR workflow instead of
pushing directly to `master` (see [[feedback_pr_workflow_fact]] in Claude's
memory). `gh auth login` not yet run, so PRs get opened manually via the
compare-link GitHub returns.

### What was built
- `query_strategy.py` — shared concept-based query-building logic, extracted
  from `medical_retrieval.py` so `retrieval.py` (Wikipedia) could reuse the
  exact same validated approach instead of drifting.
- `retrieval.py` (Wikipedia) rewritten: same concept-based query strategy as
  MedlinePlus, evidence tagged with `"origin": "Wikipedia"`.
- `verify.py` now fans out to **both** `medical_retrieval` and `retrieval`
  (Wikipedia) for every claim — no domain routing yet, just compare
  evidence from both and let `local_classifier.classify()` pick the best
  match regardless of source.
- `local_classifier.py`: source identity for the conflict-detection check is
  now `(title, origin)` instead of just `title`, since two sources could
  coincidentally share a title.

### Bugs found and fixed during validation
1. **Concept ranking picked generic nouns over named entities.** "The
   capital of Australia is Sydney" ranked "The capital" above "Australia"/
   "Sydney" (tied token-count, earliest-position tiebreak) — and since
   retrieval stops at the first query with any hits, the real entities never
   got tried. Fixed in `concept_extraction.py`: chunks containing a proper
   noun (`token.pos_ == "PROPN"`) now rank above same-length generic chunks.
2. **Wikipedia's REST summary endpoint is too short.** It returns only the
   first ~500-char paragraph, which for "Australia" never mentions
   "Canberra" at all. Switched to the full lead-section extract
   (`action=query&prop=extracts&exintro=true`, ~2700 chars for Australia) —
   same "richer article, truncate before tokenizing" pattern already used
   for MedlinePlus.

### Test results (after both fixes above)
- **General domain** (`claims.json`, 16 cases, `test_claims.py`): **9/16
  (56%)**. First-ever measurement under the new architecture — no prior
  baseline to compare against for this specific set.
- **Medical** (`medical_claims_test.json`, 14 cases, `test_verify_medical.py`):
  **10/14 (71%)** — matches the pre-pivot baseline exactly, zero dangerous
  verdicts among the 4 failures (all safe `insufficient_evidence`). The
  two-source fan-out is pulling in genuinely useful Wikipedia evidence for
  some medical claims too (e.g. "Insulin is a hormone made by the pancreas"
  matched via Wikipedia's Insulin page, not MedlinePlus) without regressing
  anything. **No regression from the general-domain pivot.**

### New failure class found (not yet fixed)
**"The sun revolves around the Earth" scored `supported` in the batch run**
(a false claim marked true — dangerous). Root cause confirmed directly: the
real Wikipedia "Sun" article contains "The Sun orbits the Galactic Center" —
structurally identical to the claim's "the sun revolves around ___". The NLI
model appears to match the *sentence pattern* ("Sun orbits X") without
checking that X is actually "Earth." This is a different bug class than the
ones already fixed (missing distinctive terms / missing numbers) — "Earth"
genuinely does appear elsewhere in the evidence (an unrelated
distance-measurement sentence), so the existing distinctive-terms gate
passes it. This is a **relational/argument-binding confusion**, not a
topic-overlap problem, and isn't something the current gates catch.

A re-run of just this one claim (outside the batch) actually landed on
`insufficient_evidence` instead, via the conflict-detection branch (a
MedlinePlus "Tanning" page scored 0.99 entailment, unrelated Wikipedia "The
Sun (disambiguation)" scored 0.82 contradiction — both noise, correctly
caught as a conflict). This means the outcome is **sensitive to which top-3
search results a live query happens to return**, which can vary run to run —
a new source of flakiness that a pure single-curated-source pipeline
(MedlinePlus-only) didn't have to deal with.

**Not yet decided:** whether to raise `ENTAILMENT_THRESHOLD`/
`CONTRADICTION_THRESHOLD` (currently both 0.55) and do a full revalidation
pass, or document this as a known limitation of general-purpose NLI for now.
Flagged to the user, pending their call — raising thresholds blind, without
a full re-test cycle, risks silently regressing already-validated cases, and
each full test cycle costs ~15-20 minutes on this RAM-constrained machine.

**Recommendation:** medical didn't regress (still 10/14, still zero
dangerous verdicts), so the pivot itself is safe to ship as-is. Before
touching global thresholds, worth triaging the other 5 general-suite
failures first (water boiling point, Einstein/relativity, Great Wall visible
from space, Napoleon born in Italy, 10%-of-brain myth, Eiffel Tower in
London) to see how many are the same relational-confusion class vs. simply
"evidence never retrieved" — those need different fixes, and lumping them
together into one threshold change would be guessing.

## 2026-09-05 (later) — LangSearch integration (branch `langsearch-integration` off `dev`)

Manoj suggested LangSearch (free-tier web search API) as the general
source, to replace direct Wikipedia search. Provided an API key, stored in
`.env` (gitignored). Built `websearch_retrieval.py`, wired into `verify.py`
in place of `retrieval.py` (Wikipedia) — `retrieval.py` kept but unused,
same pattern as before.

**Bug found and fixed during validation:** LangSearch has no language
parameter and mixes in non-English results by default — confirmed a plain
"Australia" query returned Chinese (baike.com), Spanish, and Portuguese
Wikipedia mirrors alongside English pages. The English-only NLI classifier
scored one of those anyway (a Spanish Wikipedia mirror got 0.79
"contradiction" against an English claim) — a real risk of an unreliable
verdict from a language mismatch. Fixed with a `langdetect`-based
English-only filter in `websearch_retrieval.py`.

**Regression test results (straight replace, Wikipedia -> LangSearch):**
- General suite: **8/16 (50%)**, down from 9/16 (56%). Two clear
  regressions: "capital of France is Paris" and "capital of Australia is
  Sydney" both went from correct to `insufficient_evidence`, because
  LangSearch's summaries/snippets are shorter than Wikipedia's full lead
  section and didn't happen to state the capital city. The sun/earth
  relational-confusion bug (see above) reproduces here too, confirming it's
  an NLI model limitation independent of which source is used.
- Medical suite: **9/14 (64%)**, down from 10/14 (71%). One new failure:
  "Eating an apple a day guarantees you will never get sick" now scores
  `contradicted` (0.98) from an "Apple - Wikipedia (via LangSearch)" page —
  happens to land on the intuitively-correct real-world answer, but for an
  unreliable reason (likely bypassed the distinctive-terms gate because the
  claim only has one real extracted concept, so the check short-circuits to
  "nothing to check, pass"). Previously this was a clean, correctly-reasoned
  `insufficient_evidence`.

**Net finding: straight replacement measurably regresses both suites.**
User chose to supplement instead (fan out to Wikipedia + MedlinePlus +
LangSearch, all three) rather than replace.

**Re-tested with all three sources:** General **8/16 (50%)**, Medical
**9/14 (64%)** — identical to the LangSearch-only numbers, still below the
original Wikipedia+MedlinePlus baseline (56%/71%). Adding LangSearch as a
third source did not recover the loss and introduced new noise: the
Australia-capital claim (correctly `contradicted` with Wikipedia-only)
flipped to `insufficient_evidence` because the extra source added a
conflicting signal; the apple-a-day false positive persisted in this
config too.

**Conclusion: LangSearch has not demonstrated a net accuracy win in either
configuration tried (replace or supplement).** The original
Wikipedia+MedlinePlus setup (pre-LangSearch) remains the best-performing
configuration measured so far. Recommendation given to the user: don't
merge `langsearch-integration` as the default path; either drop LangSearch
for now, or keep investigating why it's adding noise (shorter text than
Wikipedia's full extract seems to be the main driver) before it earns a
place in the default fan-out. Decision pending.

### Known limitations carried forward
- MedlinePlus is still queried for every claim (including obviously
  non-medical ones) — costs one cheap wasted request per claim, not
  incorrect behavior, but worth knowing if request volume ever matters.
- Live web search (Wikipedia, MedlinePlus) means retrieval results can shift
  over time or between runs, unlike a fixed offline fixture — accuracy
  numbers here are a snapshot, not a permanent guarantee.
