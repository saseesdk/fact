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


def _clean_html(raw):
    """MedlinePlus wraps matched terms in <span> and formats prose with
    <p>/<ul>/<li> — strip markup and unescape entities for plain-text NLI
    input."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def retrieve_evidence(claim, max_sources=3):
    """Given a claim, return a list of {title, extract, url} evidence
    candidates from MedlinePlus health topics. Same shape as
    retrieval.retrieve_evidence() so local_classifier.classify() works
    unchanged regardless of which source module verify.py wires up."""
    params = {"db": "healthTopics", "term": claim, "retmax": max_sources}
    resp = requests.get(SEARCH_URL, params=params, timeout=10)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    evidence = []
    for doc in root.findall(".//document"):
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
