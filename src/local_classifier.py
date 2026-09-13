"""Local, free, no-API-key claim-vs-evidence classifier.

Uses MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli — an NLI model trained on
MNLI + FEVER-NLI + ANLI (~200M params, CPU-friendly). FEVER is literally the
"claim + evidence -> SUPPORTS/REFUTES/NOT ENOUGH INFO" task, which is exactly
what this project needs, so this maps onto our four user-facing verdicts
(issue #18):

    entailment    -> supported        (a source backs up the claim)
    contradiction -> misrepresented   (a relevant source disagrees with it)
    neutral       -> unsupported      (nothing relevant enough found either way)

There is a 4th user-facing category, "outdated" (the claim was once true but
a source shows it no longer is, with a date), which this module does NOT
produce yet — that needs actual date-aware reasoning (extracting and
comparing dates between claim and evidence), which nothing in this pipeline
does today. Rather than guess at it with no real signal, "outdated" is left
unimplemented until there's a real way to detect it; see docs/PROGRESS.md.

Runs entirely offline after the first download (model is cached under
~/.cache/huggingface). No account, no API key, no per-call cost.
"""

import re

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from concept_extraction import extract_concepts
from keywords import keywords as _keywords

MODEL_NAME = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
ENTAILMENT_THRESHOLD = 0.55
CONTRADICTION_THRESHOLD = 0.55

# LangSearch's "summary" field can be huge (confirmed directly: one real
# result was 50,000+ characters), and every comparison was hitting the old
# 2000-char cap every single time, paying near-maximum compute cost on
# every item regardless of source. Measured directly that compute time
# scales sharply with this cap, not just tokenizer overhead: cutting from
# 2000 to 800 chars took per-item NLI scoring from ~17s to ~6s on this
# machine — the claim-relevant answer is almost always in the lead
# "what is X" section of a summary, not buried thousands of characters in,
# so this trims cost without (measured via the regression suites) losing
# accuracy. Trim before tokenizing instead of after (truncation=True alone
# still pays full tokenizer + attention cost up to the untruncated length).
MAX_PREMISE_CHARS = 800

_tokenizer = None
_model = None


def _load():
    global _tokenizer, _model
    if _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        _model.eval()
    return _tokenizer, _model


def _nli_scores(premise, hypothesis):
    """Return {'entailment': p, 'neutral': p, 'contradiction': p} for one pair."""
    tokenizer, model = _load()
    inputs = tokenizer(premise[:MAX_PREMISE_CHARS], hypothesis, return_tensors="pt", truncation=True)
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)[0]
    return {model.config.id2label[i]: float(p) for i, p in enumerate(probs)}


def _addresses_claim_specifics(claim, evidence_extract, trace=None):
    """The model can score high entailment (or contradiction) purely from
    general topical familiarity, without the evidence actually saying
    anything about the claim's specific assertion — confirmed directly:
    "Type 1 diabetes can be cured by drinking more water" scored entailment
    0.95 against the Diabetes page, which never mentions "water" or "cure"
    anywhere in the compared text.

    First attempt at this check compared claim keywords against the
    *evidence title's* keywords, which was fragile: it depends on the exact
    wording of whichever specific page happened to win, not on the claim
    itself. Confirmed failing directly — when the winning source was the
    generic "Diabetes" page (title = just that one word), "type" and "1"
    from the claim weren't excluded as topic words, and both trivially
    matched the evidence (which obviously discusses "Type 1"/"Type 2" as
    categories), letting the check pass even though the actually distinctive
    words ("cured", "drinking", "water") were still absent.

    Anchoring on the claim's own primary extracted concept instead (Phase
    1.1, concept_extraction.py) fixes the title-dependence, but a second
    problem showed up right behind it: the anchor concept isn't reliably
    "the general topic" — for "Take 500mg of ibuprofen every 4 hours for
    chronic pain", concept extraction ranked "500mg" as the top concept
    (highest content-token score), so THAT got excluded as if it were the
    topic, leaving only generic words ("take", "pain", "chronic", "every")
    as "distinctive" — all of which trivially appear on any Chronic Pain
    page, letting a fabricated dosage regimen through. Same failure for "A
    newly discovered gene variant found in 2025 causes gestational
    diabetes": "diabetes"/"gestational" trivially matched a real Diabetes
    and Pregnancy page, even though "2025"/"causes"/"found" — the actual
    fabricated-study assertion — did not.

    Numbers (dosages, years, statistics) turn out to be a much more
    reliable signal than word-overlap for this specific problem: a general
    topic page essentially never happens to independently restate an
    arbitrary specific number unless it's actually confirming that fact, so
    treat "does the evidence contain the claim's numbers" as a hard
    requirement, before the softer word-based check.

    That word-based check also had to change shape: comparing the claim's
    full keyword bag against just the anchor concept's keywords let a lone
    leftover word decide the outcome even when it wasn't a real concept at
    all — confirmed failing on "The flu vaccine cannot give you the flu"
    (a legitimate, correctly-matched "Flu Shot" page): concepts were
    ['The flu vaccine', 'the flu'], so after removing the anchor's words
    ("flu", "vaccine") the only leftover was "give" — a generic verb that
    was never actually part of any extracted concept, just incidental
    sentence filler, and it happened not to appear in the evidence text,
    wrongly rejecting a correct match. Scoping the check to words that
    belong to an actual *other extracted concept* (not just any leftover
    word from the raw sentence) fixes this: "the flu" contributes nothing
    new beyond the anchor, so there's nothing left to require — while
    "more water" (for the diabetes claim) still contributes a genuine new
    concept ("water") that has to be addressed."""
    haystack = evidence_extract[:MAX_PREMISE_CHARS].lower()

    claim_numbers = set(re.findall(r"\b\d+\b", claim))
    if claim_numbers and not claim_numbers.issubset(set(re.findall(r"\b\d+\b", haystack))):
        if trace is not None:
            trace["distinctive_check"] = {
                "reason": "claim number(s) missing from evidence",
                "claim_numbers": sorted(claim_numbers),
                "passed": False,
            }
        return False

    concepts = extract_concepts(claim)
    if len(concepts) < 2:
        if trace is not None:
            trace["distinctive_check"] = {"reason": "fewer than 2 concepts, nothing to check", "passed": True}
        return True
    anchor_keywords = set(_keywords(concepts[0]))
    other_keywords = set()
    for concept in concepts[1:]:
        other_keywords |= set(_keywords(concept)) - anchor_keywords
    if not other_keywords:
        if trace is not None:
            trace["distinctive_check"] = {"reason": "no distinctive terms beyond anchor concept", "passed": True}
        return True
    passed = any(term in haystack for term in other_keywords)
    if trace is not None:
        trace["distinctive_check"] = {
            "anchor_concept": concepts[0],
            "other_concepts": concepts[1:],
            "distinctive_terms": sorted(other_keywords),
            "passed": passed,
        }
    return passed


def classify(claim, evidence, trace=None):
    """Same input/output shape as the LLM-based classifier it replaces.

    verdict is one of the four user-facing categories from issue #18:
    supported / misrepresented / unsupported / outdated — "outdated" is not
    produced by this function yet (see module docstring). matched_sources
    stays a flat list of "title (origin)" strings for existing callers;
    sources is the richer {title, url} form so a UI can render an actual
    clickable link instead of just a label.

    issue #21 ("insufficient evidence when evidence exists"): this used to
    only ever look at the single highest-scoring entailment/contradiction
    candidate — if THAT one happened to fail the specifics gate below, the
    whole claim fell back to unsupported even when a different,
    slightly-lower-scoring item in the same evidence list would have passed
    outright. Now walks each ranked list (entailment candidates, separately
    contradiction candidates) and picks the first one that also passes the
    specifics gate, so a pool of several evidence items actually gets used
    as a pool, not just probed at its single top entry — capped to the top
    MAX_CANDIDATES_PER_SIDE of each list, since unbounded depth measurably
    backfired on claims with no real evidence either way (opinions/
    predictions that slip past claim_filter.py): deep enough search
    eventually turns up something that coincidentally passes the gate,
    producing a confident wrong verdict where "unsupported" was correct."""
    if not evidence:
        return {
            "verdict": "unsupported",
            "confidence": 1.0,
            "explanation": "No evidence was retrieved for this claim.",
            "matched_sources": [],
            "sources": [],
        }

    scored = []
    if trace is not None:
        trace["sources_checked"] = []

    for e in evidence:
        scores = _nli_scores(premise=e["extract"], hypothesis=claim)
        origin = e.get("origin")
        label = f"{e['title']} ({origin})" if origin else e["title"]
        if trace is not None:
            trace["sources_checked"].append({
                "title": e["title"],
                "origin": origin,
                "url": e.get("url"),
                "entailment": round(scores["entailment"], 4),
                "contradiction": round(scores["contradiction"], 4),
                "neutral": round(scores["neutral"], 4),
            })
        scored.append({
            "key": (e["title"], origin),
            "source": label,
            "title": e["title"],
            "url": e.get("url"),
            "extract": e["extract"],
            "entailment": scores["entailment"],
            "contradiction": scores["contradiction"],
            "neutral": scores["neutral"],
        })

    entailment_candidates = sorted(
        (e for e in scored if e["entailment"] >= ENTAILMENT_THRESHOLD),
        key=lambda e: e["entailment"],
        reverse=True,
    )
    contradiction_candidates = sorted(
        (e for e in scored if e["contradiction"] >= CONTRADICTION_THRESHOLD),
        key=lambda e: e["contradiction"],
        reverse=True,
    )

    # Only the top MAX_CANDIDATES_PER_SIDE of each ranked list get a chance
    # at the specifics gate, not the whole pool (see docstring above for why).
    MAX_CANDIDATES_PER_SIDE = 3
    entailment_winner = next(
        (
            e for e in entailment_candidates[:MAX_CANDIDATES_PER_SIDE]
            if _addresses_claim_specifics(claim, e["extract"])
        ),
        None,
    )
    contradiction_winner = next(
        (
            e for e in contradiction_candidates[:MAX_CANDIDATES_PER_SIDE]
            if _addresses_claim_specifics(claim, e["extract"])
        ),
        None,
    )

    if entailment_winner and contradiction_winner and entailment_winner["key"] != contradiction_winner["key"]:
        # Two different sources each strongly assert the opposite of the
        # other, AND each one actually addresses the claim's specifics (not
        # just raw score) — a real disagreement, not one side being topical
        # noise. Picking whichever score is a fraction higher and silently
        # discarding the other would hide that disagreement behind a
        # confident-looking verdict. Surface it instead of guessing. Neither
        # source unambiguously "supports" the claim, so this falls under
        # "unsupported" rather than "misrepresented" (which implies one
        # clear relevant source, not two disagreeing ones).
        _addresses_claim_specifics(claim, entailment_winner["extract"], trace=trace)
        return {
            "verdict": "unsupported",
            "confidence": round(min(entailment_winner["entailment"], contradiction_winner["contradiction"]), 4),
            "explanation": (
                f"Conflicting evidence: '{entailment_winner['source']}' entails the claim "
                f"(entailment={entailment_winner['entailment']:.2f}) while "
                f"'{contradiction_winner['source']}' contradicts it "
                f"(contradiction={contradiction_winner['contradiction']:.2f})."
            ),
            "matched_sources": [entailment_winner["source"], contradiction_winner["source"]],
            "sources": [
                {"title": entailment_winner["title"], "url": entailment_winner["url"]},
                {"title": contradiction_winner["title"], "url": contradiction_winner["url"]},
            ],
        }

    if entailment_winner:
        _addresses_claim_specifics(claim, entailment_winner["extract"], trace=trace)
        return {
            "verdict": "supported",
            "confidence": round(entailment_winner["entailment"], 4),
            "explanation": (
                f"Evidence from '{entailment_winner['source']}' entails the claim "
                f"(entailment={entailment_winner['entailment']:.2f})."
            ),
            "matched_sources": [entailment_winner["source"]],
            "sources": [{"title": entailment_winner["title"], "url": entailment_winner["url"]}],
        }

    if contradiction_winner:
        _addresses_claim_specifics(claim, contradiction_winner["extract"], trace=trace)
        return {
            "verdict": "misrepresented",
            "confidence": round(contradiction_winner["contradiction"], 4),
            "explanation": (
                f"Evidence from '{contradiction_winner['source']}' contradicts the claim "
                f"(contradiction={contradiction_winner['contradiction']:.2f})."
            ),
            "matched_sources": [contradiction_winner["source"]],
            "sources": [{"title": contradiction_winner["title"], "url": contradiction_winner["url"]}],
        }

    # Nothing in either ranked list passed the specifics gate. Still surface
    # the most informative near-miss (whichever side's raw top score was
    # higher) instead of silently falling through to the generic neutral
    # message, so the explanation stays as useful as before this change.
    top_entailment = entailment_candidates[0] if entailment_candidates else None
    top_contradiction = contradiction_candidates[0] if contradiction_candidates else None

    if top_entailment and (
        not top_contradiction or top_entailment["entailment"] >= top_contradiction["contradiction"]
    ):
        _addresses_claim_specifics(claim, top_entailment["extract"], trace=trace)
        return {
            "verdict": "unsupported",
            "confidence": round(1 - top_entailment["entailment"], 4),
            "explanation": (
                f"'{top_entailment['source']}' scored high entailment "
                f"(entailment={top_entailment['entailment']:.2f}) but never actually "
                f"addresses what the claim specifically asserts beyond its general "
                f"topic — likely a topical-familiarity false positive, not real support."
            ),
            "matched_sources": [],
            "sources": [],
        }

    if top_contradiction:
        _addresses_claim_specifics(claim, top_contradiction["extract"], trace=trace)
        return {
            "verdict": "unsupported",
            "confidence": round(1 - top_contradiction["contradiction"], 4),
            "explanation": (
                f"'{top_contradiction['source']}' scored high contradiction "
                f"(contradiction={top_contradiction['contradiction']:.2f}) but never actually "
                f"addresses what the claim specifically asserts beyond its general "
                f"topic — likely a topical-familiarity false positive, not a real refutation."
            ),
            "matched_sources": [],
            "sources": [],
        }

    best_neutral = max(scored, key=lambda e: e["neutral"])
    best_entailment_score = max(e["entailment"] for e in scored)
    best_contradiction_score = max(e["contradiction"] for e in scored)
    return {
        "verdict": "unsupported",
        # Confidence in THIS verdict is how confident the model is that the
        # relationship is genuinely neutral — not `1 - <whatever score
        # happened to be highest>`, which was backwards: a high neutral
        # score (real signal that no evidence source relates to the claim
        # either way) previously produced a LOW displayed confidence.
        "confidence": round(best_neutral["neutral"], 4),
        "explanation": (
            f"No evidence source was confident enough either way "
            f"(best entailment={best_entailment_score:.2f}, "
            f"best contradiction={best_contradiction_score:.2f})."
        ),
        "matched_sources": [],
        "sources": [],
    }
