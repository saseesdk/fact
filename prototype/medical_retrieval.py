"""Medical-specific evidence retrieval, one of two sources verify.py fans
out to (see retrieval.py for the general-purpose Wikipedia source).

Source of truth: MedlinePlus (National Library of Medicine / NIH) — a
government-run, editorially curated consumer-health encyclopedia. It's the
Tier-1 "government portal" source from the ideation deck, picked over
Wikipedia specifically for medical claims because it's authored and reviewed
by NLM health professionals rather than open editing. Kept as a dedicated
source even after generalizing past medical-only, since it's meaningfully
higher quality than Wikipedia for medical claims specifically.

Free, no API key, no registration: https://medlineplus.gov/webservices.html
Rate limit: 85 requests/minute/IP (not a concern at prototype scale).

PubMed (via NCBI E-utilities) is the natural next source to add for claims
about specific research findings rather than general medical facts — not
added yet, tracked as the next step in ROADMAP.md.
"""

import html
import re
import xml.etree.ElementTree as ET

import requests

from query_strategy import query_candidates

SEARCH_URL = "https://wsearch.nlm.nih.gov/ws/query"
ORIGIN = "MedlinePlus"


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
        trace.setdefault("queries_tried", []).append({"source": ORIGIN, "query": term, "hits": len(docs)})
    return docs


def retrieve_evidence(claim, max_sources=3, trace=None):
    """Given a claim, return a list of {title, extract, url, origin} evidence
    candidates from MedlinePlus health topics. Same shape as
    retrieval.retrieve_evidence() (plus "origin") so local_classifier.classify()
    can compare evidence from multiple sources without caring which one a
    given item came from.

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
    query_used = None
    for query in query_candidates(claim):
        docs = _search(query, max_sources, trace=trace)
        if docs:
            query_used = query
            break

    if trace is not None:
        trace.setdefault("query_used", {})[ORIGIN] = query_used

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
                "origin": ORIGIN,
            }
        )
    return evidence


if __name__ == "__main__":
    import json
    import sys

    claim = " ".join(sys.argv[1:]) or "Type 2 diabetes means the body makes no insulin at all"
    print(json.dumps(retrieve_evidence(claim), indent=2))
