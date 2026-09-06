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
from medical_retrieval import retrieve_evidence as retrieve_medical
from retrieval import retrieve_evidence as retrieve_wikipedia
from websearch_retrieval import retrieve_evidence as retrieve_websearch

# Fan out to every source rather than picking one domain up front — no
# domain routing yet (see ROADMAP.md), so a general claim and a medical
# claim both get compared against whichever sources actually have relevant
# evidence, and the classifier picks the best match regardless of origin.
# MedlinePlus stays a dedicated source even for general claims since it's
# meaningfully higher-quality than general web search specifically for
# medical facts; it simply returns [] for non-medical claims, which costs
# one cheap wasted request, not a wrong answer.
#
# LangSearch was tried as a straight replacement for Wikipedia and measured
# worse on both regression suites (general 9/16->8/16, medical 10/14->9/14,
# see docs/PROGRESS.md) — its snippets/summaries are shorter than Wikipedia's
# full lead section and missed facts Wikipedia had (e.g. "capital of
# Australia" lost the "Canberra" mention entirely). Kept as a third
# supplementary source instead of a replacement, for its broader web
# coverage beyond one single site, without giving up Wikipedia's more
# complete text for well-known facts.
SOURCES = [retrieve_medical, retrieve_wikipedia, retrieve_websearch]


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
