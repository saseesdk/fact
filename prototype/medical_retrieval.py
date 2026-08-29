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

from concept_extraction import extract_concepts
from keywords import keywords as _keywords

SEARCH_URL = "https://wsearch.nlm.nih.gov/ws/query"


def _query_candidates(claim):
    """Yield queries in priority order: extracted concepts first (Phase 1.1,
    concept_extraction.py), each tried individually and most-salient-first,
    then the old raw-claim / stopword-stripped queries as a last resort.

    Concepts are tried one at a time rather than joined together, since
    MedlinePlus search appears to require most/all terms in a query to
    co-occur in a document — confirmed directly: 'diabetes cured water' (3
    words) gets 0 results even though 'diabetes water' and 'diabetes cure'
    each get 30+ results individually. A single extracted concept is
    usually specific enough to be safe on its own (e.g. "Sinusitis" finds
    the exact right page directly) — this is different from the single
    *generic keyword* fallback that was tried and reverted earlier (e.g.
    bare "diabetes"), which surfaced a broad, only tangentially-related page
    and caused the NLI model to mistake lexical overlap for entailment.
    A concept like "Type 1 diabetes" or "the common cold" is meaningfully
    narrower than the bare category name that caused those false positives.

    A leading bare quantity is stripped before searching (e.g. "10
    paracetamol" -> "paracetamol") — confirmed directly that MedlinePlus's
    keyword search treats "10" as just another search term to match, not a
    dosage filter, so "10 paracetamol" surfaced two completely unrelated
    pages (Chickenpox, Fifth Disease — both mention giving a child
    acetaminophen for fever) while bare "paracetamol" correctly finds "Pain
    Relievers", the actually relevant page. The number itself isn't lost:
    local_classifier._addresses_claim_specifics() separately requires the
    claim's numbers to literally appear in the winning evidence text before
    accepting a verdict, so this only changes what's searched for, not what's
    later required to match."""
    for concept in extract_concepts(claim):
        yield _strip_leading_quantity(concept)
    yield claim
    keywords = _keywords(claim)
    if keywords:
        yield " ".join(keywords)


def _strip_leading_quantity(concept):
    """Drop a leading bare number/dose token ("10", "500mg") from a search
    term — see _query_candidates for why."""
    words = concept.split()
    while words and re.match(r"^\d", words[0]):
        words.pop(0)
    return " ".join(words) if words else concept


def _clean_html(raw):
    """MedlinePlus wraps matched terms in <span> and formats prose with
    <p>/<ul>/<li> — strip markup and unescape entities for plain-text NLI
    input."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _search(term, max_sources, trace=None):
    """Returns [] on any network/parsing failure rather than raising —
    a MedlinePlus outage should degrade to insufficient_evidence (safe,
    matches the existing "no evidence found" path) rather than crashing
    verify() and surfacing a raw 500 to the UI."""
    params = {"db": "healthTopics", "term": term, "retmax": max_sources}
    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        docs = ET.fromstring(resp.content).findall(".//document")
    except (requests.exceptions.RequestException, ET.ParseError) as e:
        print(f"medical_retrieval: search failed for {term!r}: {e}")
        docs = []
    if trace is not None:
        trace.setdefault("queries_tried", []).append({"query": term, "hits": len(docs)})
    return docs


def retrieve_evidence(claim, max_sources=3, trace=None):
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
    if trace is not None:
        trace["concepts"] = extract_concepts(claim)

    docs = []
    query_used = None
    for query in _query_candidates(claim):
        docs = _search(query, max_sources, trace=trace)
        if docs:
            query_used = query
            break

    if trace is not None:
        trace["query_used"] = query_used

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
