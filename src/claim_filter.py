"""Phase 3: separate checkable factual claims from opinions/metaphors/other
non-checkable statements, before spending any retrieval or verification
effort on them.

Reuses the same local NLI model as local_classifier.py — an NLI model doubles
as a zero-shot classifier (score each candidate label via entailment against
the sentence, using the "This example is {label}." hypothesis template). No
new model, no new dependency, no API key.

Calibration notes (see claim_filter_test.json / test_claim_filter.py):
- A 3-way split (fact / opinion / metaphor) with short single-word labels
  handled fact-vs-opinion well but could not reliably detect metaphor at all
  (0/4 on the test set) — general-purpose NLI has no real signal for
  figurative language.
- Collapsing to a 2-way split (fact / opinion), with metaphors bucketed under
  "opinion" (i.e. "not a checkable claim"), scored 11/13 (85%) — this works
  because the pipeline only needs to correctly EXCLUDE non-checkable
  statements, not correctly *label* why a statement was excluded.
- Long, grammatically-precise hypothesis phrases (e.g. "an opinion or
  subjective statement") scored WORSE than short single-word labels ("fact",
  "opinion") — this model's zero-shot behavior was benchmarked on short
  topic-style labels, not descriptive phrases.
- Remaining known failure modes: future-tense predictions ("the stock market
  will crash in 2027") read as "opinion" even though they're structurally
  checkable claims; short idioms ("time is money") can read as literal fact.
  Both are open questions in the master plan (ambiguous/hard-to-classify
  statements), not bugs in this implementation.
"""

import re

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# Separate model from local_classifier.py on purpose: that module does
# claim-vs-evidence entailment (FEVER-trained is the right tool there), this
# module does zero-shot fact/opinion topic classification (a model trained
# for zero-shot, not just FEVER, is the better tool here) — no reason the
# two tasks should be pinned to the same checkpoint.
MODEL_NAME = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"

_tokenizer = None
_model = None


def _load():
    global _tokenizer, _model
    if _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        _model.eval()
    return _tokenizer, _model


CANDIDATE_LABELS = ["fact", "opinion"]
FACTUAL_LABEL = "fact"

# Confidence margins on this model are often razor-thin even for canonical
# facts (e.g. "The capital of France is Paris" scores fact=0.148 vs
# opinion=0.185 — a near coin flip). A bare argmax would silently drop real
# claims from verification entirely, which is worse than spending a wasted
# verification cycle on a borderline statement (which just resolves to
# insufficient_evidence downstream — a safe outcome, not a wrong one). So we
# fail OPEN: only exclude a sentence when opinion clearly beats fact.
OPINION_MARGIN = 0.05


_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?])(?:\[\d+\])*\s+"          # normal case: punctuation (+ optional
                                            # citations, e.g. Wikipedia's "life.[4][5]")
                                            # followed by whitespace
    r"|(?<=[.!?])(?:\[\d+\])*(?=[A-Z])"    # punctuation directly followed by a
                                            # capital letter, no space at all —
                                            # copy-pasted web text routinely loses
                                            # the space/newline between a sentence
                                            # and the next heading ("provider.Common
                                            # Causes")
    r"|(?<=[a-z]{2})(?=[A-Z][a-z])"        # two headings glued directly together
                                            # with no punctuation whatsoever
                                            # ("CausesViral infections") — requires
                                            # 2+ lowercase letters before the
                                            # boundary and a capital+lowercase
                                            # after, so short acronym prefixes like
                                            # "mRNA" or "pH" aren't split apart
)


def split_sentences(text):
    """Naive sentence splitter — good enough for the MVP prototype stage.

    Beyond the textbook "punctuation + space" case, this also recovers
    sentence/heading boundaries from text pasted out of a rendered web page,
    where block-level elements (paragraphs, headings) routinely lose their
    separating whitespace entirely once flattened to plain text — confirmed
    directly: a real pasted health article collapsed into a single ~700-word
    "sentence" and broke retrieval entirely, because every boundary in it was
    either "punctuation.NextWord" or "HeadingWordNextHeading" with zero space.
    """
    text = text.strip()
    if not text:
        return []
    sentences = _SENTENCE_BOUNDARY.split(text)
    return [s.strip() for s in sentences if s.strip()]


def classify_statement(sentence):
    """Return {'fact': entailment_score, 'opinion': entailment_score}."""
    tokenizer, model = _load()
    scores = {}
    for label in CANDIDATE_LABELS:
        hypothesis = f"This example is {label}."
        inputs = tokenizer(sentence, hypothesis, return_tensors="pt", truncation=True)
        with torch.no_grad():
            logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        entailment_idx = [i for i, l in model.config.id2label.items() if l == "entailment"][0]
        scores[label] = round(float(probs[entailment_idx]), 4)
    return scores


def is_checkable_claim(scores):
    return (scores["opinion"] - scores["fact"]) <= OPINION_MARGIN


def extract_factual_claims(text):
    """Given raw page text, return only the sentences worth fact-checking."""
    claims = []
    for sentence in split_sentences(text):
        scores = classify_statement(sentence)
        if is_checkable_claim(scores):
            claims.append({"sentence": sentence, "scores": scores})
    return claims


def segregate(text):
    """Partition every sentence into factual claims vs. everything else.

    Same classification as extract_factual_claims(), but keeps both sides of
    the split so a UI can show the full partition rather than just the
    surviving claims.
    """
    claims = []
    non_claims = []
    for sentence in split_sentences(text):
        scores = classify_statement(sentence)
        entry = {"sentence": sentence, "scores": scores}
        if is_checkable_claim(scores):
            claims.append(entry)
        else:
            non_claims.append(entry)
    return {"claims": claims, "non_claims": non_claims}


if __name__ == "__main__":
    import json
    import sys

    text = " ".join(sys.argv[1:]) or (
        "The Eiffel Tower is located in Paris. This is the greatest city in the world. "
        "The stock market is on fire today."
    )
    print(json.dumps(extract_factual_claims(text), indent=2))
