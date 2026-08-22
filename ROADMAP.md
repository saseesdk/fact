# Roadmap — Factual Verification Extension

Source of truth for direction: `IDEATION.pptx` (Desktop) +
`Factual_Verification_Extension_Master_Plan.docx` (Desktop). This file tracks
the phase-by-phase plan from the current local prototype to the full product
pitched in the deck.

## Phase 0 — Foundation (shipped)

Prove the core loop works before building anything around it.

- Claim -> Wikipedia evidence -> NLI verdict (supported / contradicted /
  insufficient_evidence), fully local and free.
- Fact/opinion pre-filter so the pipeline doesn't waste cycles verifying
  subjective sentences.
- Hand-built test sets proving the loop generalizes past demo claims.

## Phase 1 — Trustworthy retrieval

The deck's own Tier 2/3 slides were left blank. This is where the product's
credibility actually gets decided.

- **Tier 1** — arXiv, PubMed, Semantic Scholar, government open-data portals,
  official org sites, Wikipedia (accepted only once its citation is checked,
  not the prose itself).
- **Tier 2** — wire services and structured fact-check organizations:
  Reuters, AP, AFP, PolitiFact, Snopes, FactCheck.org.
- **Tier 3** — general reputable web, used only to corroborate, never alone.
- A domain router that reads the claim (medical / scientific / news /
  general / computational) and picks which tiers to query, instead of one
  hardcoded Wikipedia call.

Aim for the sky: a source registry with a live-scored reliability weight per
domain, learned from historical accuracy — not a static hardcoded list.

## Phase 2 — Verdict intelligence

The deck promises six outcomes, not three. Close that gap.

- Expand the verdict set to match the deck: supported / contradicted /
  outdated / misrepresented (evidence exists but the claim distorts it) /
  logical error / insufficient evidence.
- Add an embedding-similarity layer for ranking evidence candidates, separate
  from the NLI entailment step used for the final verdict.
- Per-verdict confidence calibration instead of one global threshold.

Aim for the sky: every verdict ships with a quoted sentence of evidence and a
one-line reason, so the user can audit the audit instead of trusting a label.

## Phase 3 — Beyond prose claims

The deck's own "Challenge" slide names this directly: a math answer with
working shown can't be fact-checked by retrieval.

- Route numeric/computational claims to a symbolic checker (e.g. sympy)
  instead of NLI — recompute rather than retrieve.
- Temporal reasoning: does the claim's implied date line up with the
  evidence's actual publish/revision date (catches "outdated" mechanically).

Open risk (from the deck): ambiguous and subjective text has no ground truth
to retrieve against — the honest answer for a lot of input will stay
"insufficient evidence," and that has to be an acceptable output, not a
failure.

## Phase 4 — Service backbone

Turn a script into something an extension, or anyone else, can call.

- FastAPI wrapper around `verify()` / `verify_text()`.
- Claim-hash cache with a TTL tuned to source volatility (news claims expire
  fast, reference facts barely at all).
- Git history, CI, structured logging — the project has none of this today.

Aim for the sky: sub-second p95 latency via caching and async multi-source
fan-out, so the extension never feels like it's "thinking."

## Phase 5 — The extension

The actual product from the deck's first slide.

- Manifest V3 Chrome extension: content script extracts visible page text,
  chunks it, sends it to the API.
- Inline highlighting color-coded by verdict, plus a popup with a page-level
  accuracy score.

Aim for the sky: hover any highlight to see the exact evidence snippet and
its source tier inline — the receipts, not just the verdict.

## Phase 6 — Scale & robustness

Real pages are messier than the plain-text test fixtures this was validated
on.

- HTML ingestion: strip boilerplate, ads, navigation before claims ever reach
  the filter.
- Long-document chunking that preserves cross-sentence context.
- Batch inference and an optional GPU path for throughput.

Aim for the sky: verification runs live as the page loads and as a user
scrolls, and extends past articles to chatbot output and social feeds — the
two other sources the deck calls out by name.

## Phase 7 — Source trust maturity

Tier 1 is well defined; Tier 2 and 3 need to graduate from "reputable web"
into something rigorous.

- Citation verification: confirm a Wikipedia citation actually supports the
  sentence it's attached to, not just that the citation exists.
- A transparency panel listing every source checked and why each was trusted
  or rejected.

Aim for the sky: a feedback loop — expert or crowd review of disputed
verdicts — that continuously improves the trust-tier weights instead of
leaving them fixed at launch.

## Phase 8 — Monetization

Straight from the deck's own answer to "how will I make money."

- Free tier gated by check volume or text length.
- Paid subscription for unlimited/priority checks.
- Public API with keys, usage dashboard, and billing.

Aim for the sky: an enterprise tier for newsrooms and CMS platforms to check
drafts pre-publish, plus an embeddable "accuracy score" badge publishers can
put on their own articles.

## Phase 9 — Distribution & moat

Where "aim for the sky" actually points: not a niche tool, an expected layer
of the browser.

- Ports to Firefox, Edge, Safari; a mobile/bookmarklet path for platforms
  without extensions.
- Data partnerships with existing fact-checking organizations to feed Tier 2
  directly.

Aim for the sky: the extension becomes assumed infrastructure the way
ad-blockers and password managers did — the default answer to "is this
AI-generated content actually true," which is the exact problem the deck
opens with.

## Why this, in one line

AI-generated and AI-retrieved content is never guaranteed accurate, and it
now sits underneath social feeds, chatbots, and articles alike — so the
trust layer has to live where people actually read, not in a separate tab
they have to remember to open.

**Monetization arc:** Free (capped by volume/length) -> Subscription
(unlimited, priority) -> API (usage-billed access for other products).
