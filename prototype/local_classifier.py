"""Local, free, no-API-key claim-vs-evidence classifier.

Uses MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli — an NLI model trained on
MNLI + FEVER-NLI + ANLI (~200M params, CPU-friendly). FEVER is literally the
"claim + evidence -> SUPPORTS/REFUTES/NOT ENOUGH INFO" task, which is exactly
what this project needs, so this maps directly onto our verdict categories:

    entailment    -> supported
    contradiction -> contradicted
    neutral       -> insufficient_evidence

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

# Wikipedia evidence (this project's original source) is a short lead
# paragraph, a few hundred characters. MedlinePlus evidence is a full
# article (often 2000-5000+ chars) — feeding that whole thing to the
# tokenizer every time, and relying on truncation=True to cut it down at
# encode time, made each comparison dramatically slower (DeBERTa-v3's
# tokenizer is not fast on long raw text) without adding useful signal: the
# claim-relevant answer is almost always in the lead "What is X?" section,
# not buried in prevention/treatment sections further down. Trim before
# tokenizing instead of after.
MAX_PREMISE_CHARS = 2000

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


def _addresses_claim_specifics(claim, evidence_extract):
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
        return False

    concepts = extract_concepts(claim)
    if len(concepts) < 2:
        return True
    anchor_keywords = set(_keywords(concepts[0]))
    other_keywords = set()
    for concept in concepts[1:]:
        other_keywords |= set(_keywords(concept)) - anchor_keywords
    if not other_keywords:
        return True
    return any(term in haystack for term in other_keywords)


def classify(claim, evidence):
    """Same input/output shape as the LLM-based classifier it replaces."""
    if not evidence:
        return {
            "verdict": "insufficient_evidence",
            "confidence": 1.0,
            "explanation": "No evidence was retrieved for this claim.",
            "matched_sources": [],
        }

    best_entailment = {"score": -1.0, "source": None, "extract": None}
    best_contradiction = {"score": -1.0, "source": None, "extract": None}
    best_neutral = {"score": -1.0, "source": None, "extract": None}

    for e in evidence:
        scores = _nli_scores(premise=e["extract"], hypothesis=claim)
        if scores["entailment"] > best_entailment["score"]:
            best_entailment = {"score": scores["entailment"], "source": e["title"], "extract": e["extract"]}
        if scores["contradiction"] > best_contradiction["score"]:
            best_contradiction = {"score": scores["contradiction"], "source": e["title"], "extract": e["extract"]}
        if scores["neutral"] > best_neutral["score"]:
            best_neutral = {"score": scores["neutral"], "source": e["title"], "extract": e["extract"]}

    if (
        best_entailment["score"] >= ENTAILMENT_THRESHOLD
        and best_contradiction["score"] >= CONTRADICTION_THRESHOLD
        and best_entailment["source"] != best_contradiction["source"]
    ):
        # Two different sources each strongly assert the opposite of the
        # other. Picking whichever raw score happens to be a fraction
        # higher and silently discarding the other would hide a genuine
        # disagreement between sources behind a confident-looking verdict —
        # exactly the kind of overconfidence this pipeline already got
        # burned by once (see the reverted single-keyword retrieval fallback
        # in medical_retrieval.py). Surface the conflict instead of guessing.
        return {
            "verdict": "insufficient_evidence",
            "confidence": round(min(best_entailment["score"], best_contradiction["score"]), 4),
            "explanation": (
                f"Conflicting evidence: '{best_entailment['source']}' entails the claim "
                f"(entailment={best_entailment['score']:.2f}) while "
                f"'{best_contradiction['source']}' contradicts it "
                f"(contradiction={best_contradiction['score']:.2f})."
            ),
            "matched_sources": [best_entailment["source"], best_contradiction["source"]],
        }

    if (
        best_entailment["score"] >= ENTAILMENT_THRESHOLD
        and best_entailment["score"] >= best_contradiction["score"]
    ):
        if _addresses_claim_specifics(claim, best_entailment["extract"]):
            return {
                "verdict": "supported",
                "confidence": round(best_entailment["score"], 4),
                "explanation": (
                    f"Evidence from '{best_entailment['source']}' entails the claim "
                    f"(entailment={best_entailment['score']:.2f})."
                ),
                "matched_sources": [best_entailment["source"]],
            }
        return {
            "verdict": "insufficient_evidence",
            "confidence": round(1 - best_entailment["score"], 4),
            "explanation": (
                f"'{best_entailment['source']}' scored high entailment "
                f"(entailment={best_entailment['score']:.2f}) but never actually "
                f"addresses what the claim specifically asserts beyond its general "
                f"topic — likely a topical-familiarity false positive, not real support."
            ),
            "matched_sources": [],
        }

    if (
        best_contradiction["score"] >= CONTRADICTION_THRESHOLD
        and best_contradiction["score"] > best_entailment["score"]
    ):
        if _addresses_claim_specifics(claim, best_contradiction["extract"]):
            return {
                "verdict": "contradicted",
                "confidence": round(best_contradiction["score"], 4),
                "explanation": (
                    f"Evidence from '{best_contradiction['source']}' contradicts the claim "
                    f"(contradiction={best_contradiction['score']:.2f})."
                ),
                "matched_sources": [best_contradiction["source"]],
            }
        return {
            "verdict": "insufficient_evidence",
            "confidence": round(1 - best_contradiction["score"], 4),
            "explanation": (
                f"'{best_contradiction['source']}' scored high contradiction "
                f"(contradiction={best_contradiction['score']:.2f}) but never actually "
                f"addresses what the claim specifically asserts beyond its general "
                f"topic — likely a topical-familiarity false positive, not a real refutation."
            ),
            "matched_sources": [],
        }

    return {
        "verdict": "insufficient_evidence",
        # Confidence in THIS verdict is how confident the model is that the
        # relationship is genuinely neutral — not `1 - <whatever score
        # happened to be highest>`, which was backwards: a high neutral
        # score (real signal that no evidence source relates to the claim
        # either way) previously produced a LOW displayed confidence.
        "confidence": round(best_neutral["score"], 4),
        "explanation": (
            f"No evidence source was confident enough either way "
            f"(best entailment={best_entailment['score']:.2f}, "
            f"best contradiction={best_contradiction['score']:.2f})."
        ),
        "matched_sources": [],
    }
