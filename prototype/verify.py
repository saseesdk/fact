"""Core verification loop: claim -> evidence -> verdict.

This is the Phase 2 prototype from the master plan: no extension, no backend
API, no database. Just prove out whether retrieval + NLI comparison can
reliably classify a claim as supported / contradicted / insufficient_evidence.

Fully local and free: classification runs on a small open-source NLI model
(local_classifier.py) — no API key, no external LLM dependency, no per-call
cost.
"""

import json
import sys

from claim_filter import extract_factual_claims, split_sentences
from local_classifier import classify
from retrieval import retrieve_evidence


def verify(claim):
    evidence = retrieve_evidence(claim)
    result = classify(claim, evidence)
    result["claim"] = claim
    result["evidence_count"] = len(evidence)
    return result


def verify_text(text):
    """End-to-end: raw paragraph -> filter to checkable claims -> verify each.

    Returns both the verified claims and the sentences that were filtered out
    (opinions/metaphors/other non-checkable statements), so it's clear what
    was skipped and why — never silently drop input without accounting for it.
    """
    total_sentences = split_sentences(text)
    checkable = extract_factual_claims(text)
    checkable_sentences = {c["sentence"] for c in checkable}

    results = [verify(c["sentence"]) for c in checkable]
    skipped = [s for s in total_sentences if s not in checkable_sentences]

    return {"verified": results, "skipped_non_factual": skipped}


if __name__ == "__main__":
    text = " ".join(sys.argv[1:])
    if not text:
        print('Usage: python verify.py "<claim or paragraph to check>"')
        sys.exit(1)

    if len(split_sentences(text)) > 1:
        print(json.dumps(verify_text(text), indent=2))
    else:
        print(json.dumps(verify(text), indent=2))
