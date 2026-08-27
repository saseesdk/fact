"""Evidence retrieval for the medical domain — the only domain this
prototype targets for now (see ROADMAP.md Phase 1).

Source of truth: MedlinePlus (National Library of Medicine / NIH) — a
government-run, editorially curated consumer-health encyclopedia. It's the
Tier-1 "government portal" source from the ideation deck, picked over
Wikipedia specifically for medical claims because it's authored and reviewed
by NLM health professionals rather than open editing.

Free, no API key, no registration: https://medlineplus.gov/webservices.html
Rate limit: 85 requests/minute/IP (not a concern at prototype scale).

PubMed (via NCBI E-utilities) is the natural next source to add for claims
about specific research findings rather than general medical facts — not
added yet, tracked as the next step in ROADMAP.md, to keep this module doing
one thing before layering a second source on top.
"""

import html
import re
import xml.etree.ElementTree as ET

import requests

SEARCH_URL = "https://wsearch.nlm.nih.gov/ws/query"

# MedlinePlus search returns zero results for long natural-language claims
# even when a clearly relevant page exists — confirmed directly: "Antibiotics
# do not work against viral infections like the common cold" (13 words) gets
# 0 results, but "antibiotics common cold" (3 keywords) gets 13. Stripping
# stopwords/negation as a fallback query recovers exactly this failure mode.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "not", "no", "cannot", "can", "could", "should",
    "would", "will", "to", "of", "in", "on", "at", "for", "and", "or",
    "but", "with", "like", "than", "that", "this", "these", "those", "it",
    "its", "you", "your", "i", "we", "they", "he", "she", "them", "as",
    "also", "means", "mean", "if", "so", "than", "have", "has", "had",
    "by", "more", "some", "any", "all",
}


def _keywords(claim):
    words = re.findall(r"[A-Za-z0-9]+", claim.lower())
    return [w for w in words if w not in _STOPWORDS]


def _query_candidates(claim):
    """Yield progressively narrower queries. MedlinePlus search appears to
    require most/all terms to co-occur in a document — confirmed directly:
    'diabetes cured water' (3 words) gets 0 results even though 'diabetes
    water' and 'diabetes cure' each get 30+ results individually.

    Deliberately stops at the stopword-stripped query and does NOT fall back
    further to a single bare keyword. That was tried and measured worse:
    a single generic term (e.g. just "diabetes") surfaces a broad, only
    tangentially-related page, and the NLI model reliably mistakes lexical
    overlap for entailment — e.g. "Type 1 diabetes can be cured by drinking
    water" scored 0.95 "supported" against the general Diabetes page, and
    "Antibiotics are an effective treatment for the common cold" scored 0.88
    "supported" despite the actual antibiotics evidence explicitly saying
    the opposite. For a medical fact-checker, a confident wrong verdict is
    worse than insufficient_evidence — only widen the query while there's
    still a reasonable chance the result is specific to the claim."""
    yield claim
    keywords = _keywords(claim)
    if keywords:
        yield " ".join(keywords)


def _clean_html(raw):
    """MedlinePlus wraps matched terms in <span> and formats prose with
    <p>/<ul>/<li> — strip markup and unescape entities for plain-text NLI
    input."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _search(term, max_sources):
    """Returns [] on any network/parsing failure rather than raising —
    a MedlinePlus outage should degrade to insufficient_evidence (safe,
    matches the existing "no evidence found" path) rather than crashing
    verify() and surfacing a raw 500 to the UI."""
    params = {"db": "healthTopics", "term": term, "retmax": max_sources}
    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        return ET.fromstring(resp.content).findall(".//document")
    except (requests.exceptions.RequestException, ET.ParseError) as e:
        print(f"medical_retrieval: search failed for {term!r}: {e}")
        return []


def retrieve_evidence(claim, max_sources=3):
    """Given a claim, return a list of {title, extract, url} evidence
    candidates from MedlinePlus health topics. Same shape as
    retrieval.retrieve_evidence() so local_classifier.classify() works
    unchanged regardless of which source module verify.py wires up.

    Known limitation, deliberately NOT patched with a keyword filter: search
    results occasionally include a genuinely unrelated page (e.g. "The flu
    vaccine cannot give you the flu" matched a "Gastroenteritis" page; a
    diabetes claim matched "Steatotic Liver Disease" and "Uterine Cancer").
    A substantive-keyword-overlap filter was tried against both cases and
    failed both: generic words ("give", "form") pass through too easily, and
    a real topic word (e.g. "diabetes") can legitimately appear in an
    unrelated page discussing it as a comorbidity, so simple keyword
    presence can't distinguish "this page is about the claim" from "this
    page mentions a word from the claim in passing." The actual mitigation
    in place is local_classifier.classify()'s conflict-detection branch,
    which catches the resulting bad signal downstream when it produces a
    contradiction alongside a real source's entailment (or vice versa) —
    fixing this at the retrieval layer would need real semantic relevance
    scoring (e.g. embeddings), not string matching."""
    docs = []
    for query in _query_candidates(claim):
        docs = _search(query, max_sources)
        if docs:
            break

    evidence = []
    for doc in docs:
        title = doc.find("./content[@name='title']")
        summary = doc.find("./content[@name='FullSummary']")
        if summary is None or not summary.text:
            continue
        evidence.append(
            {
                "title": _clean_html(title.text) if title is not None else doc.get("url"),
                "extract": _clean_html(summary.text),
                "url": doc.get("url"),
            }
        )
    return evidence


if __name__ == "__main__":
    import json
    import sys

    claim = " ".join(sys.argv[1:]) or "Type 2 diabetes means the body makes no insulin at all"
    print(json.dumps(retrieve_evidence(claim), indent=2))
