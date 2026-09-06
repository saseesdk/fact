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
from concept_extraction import extract_concepts
from local_classifier import classify
from websearch_retrieval import retrieve_evidence as retrieve_websearch

# extension MVP branch only: LangSearch alone, not the full
# MedlinePlus + Wikipedia + LangSearch fan-out used on dev. Two reasons:
# fewer sources means less evidence to score per claim, which matters a lot
# here since each comparison is CPU-bound local inference (10-20s each) and
# the extension's popup/panel is a live UI a person is staring at, unlike
# the batch test scripts. Traded off knowingly: regression testing on dev
# (see docs/PROGRESS.md) measured LangSearch-only as less accurate than the
# 3-source fan-out (general 8/16 vs 8/16 - same; medical 9/14 vs 9/14 - same,
# both below the original Wikipedia+MedlinePlus-only 9/16/10/14) - this is a
# deliberate speed-over-accuracy tradeoff for this branch specifically, not
# a claim that LangSearch-only is the better setup overall.
SOURCES = [retrieve_websearch]


def verify(claim):
    trace = {"concepts": extract_concepts(claim)}
    evidence = []
    for retrieve in SOURCES:
        evidence += retrieve(claim, trace=trace)
    result = classify(claim, evidence, trace=trace)
    result["claim"] = claim
    result["evidence_count"] = len(evidence)
    result["debug"] = trace
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
