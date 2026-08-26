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

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

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


def classify(claim, evidence):
    """Same input/output shape as the LLM-based classifier it replaces."""
    if not evidence:
        return {
            "verdict": "insufficient_evidence",
            "confidence": 1.0,
            "explanation": "No evidence was retrieved for this claim.",
            "matched_sources": [],
        }

    best_entailment = {"score": -1.0, "source": None}
    best_contradiction = {"score": -1.0, "source": None}
    best_neutral = {"score": -1.0, "source": None}

    for e in evidence:
        scores = _nli_scores(premise=e["extract"], hypothesis=claim)
        if scores["entailment"] > best_entailment["score"]:
            best_entailment = {"score": scores["entailment"], "source": e["title"]}
        if scores["contradiction"] > best_contradiction["score"]:
            best_contradiction = {"score": scores["contradiction"], "source": e["title"]}
        if scores["neutral"] > best_neutral["score"]:
            best_neutral = {"score": scores["neutral"], "source": e["title"]}

    if (
        best_entailment["score"] >= ENTAILMENT_THRESHOLD
        and best_entailment["score"] >= best_contradiction["score"]
    ):
        return {
            "verdict": "supported",
            "confidence": round(best_entailment["score"], 4),
            "explanation": (
                f"Evidence from '{best_entailment['source']}' entails the claim "
                f"(entailment={best_entailment['score']:.2f})."
            ),
            "matched_sources": [best_entailment["source"]],
        }

    if (
        best_contradiction["score"] >= CONTRADICTION_THRESHOLD
        and best_contradiction["score"] > best_entailment["score"]
    ):
        return {
            "verdict": "contradicted",
            "confidence": round(best_contradiction["score"], 4),
            "explanation": (
                f"Evidence from '{best_contradiction['source']}' contradicts the claim "
                f"(contradiction={best_contradiction['score']:.2f})."
            ),
            "matched_sources": [best_contradiction["source"]],
        }

    winner = max(best_entailment["score"], best_contradiction["score"], best_neutral["score"])
    return {
        "verdict": "insufficient_evidence",
        "confidence": round(1 - winner, 4) if winner < 1 else 0.0,
        "explanation": (
            f"No evidence source was confident enough either way "
            f"(best entailment={best_entailment['score']:.2f}, "
            f"best contradiction={best_contradiction['score']:.2f})."
        ),
        "matched_sources": [],
    }
