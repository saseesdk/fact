"""General-purpose evidence retrieval via LangSearch (https://langsearch.com),
replacing the direct Wikipedia search (retrieval.py, kept but no longer wired
into verify.py) as the general/non-medical source. Chosen over raw Wikipedia
search because it's a real web search engine — not limited to one site, and
handles natural-language queries without needing an exact article-title
match.

Requires a free-tier API key from the LangSearch dashboard, set as
LANGSEARCH_API_KEY in a local .env file (gitignored, never committed).
"""

import os

import requests
from dotenv import load_dotenv
from langdetect import LangDetectException, detect

from query_strategy import query_candidates

load_dotenv()

API_URL = "https://api.langsearch.com/v1/web-search"
API_KEY = os.environ.get("LANGSEARCH_API_KEY")
ORIGIN = "LangSearch"


def _search(term, max_sources, trace=None):
    """Returns [] on any network/parsing/auth failure rather than raising —
    matches the degrade-safely behavior of the other retrieval modules."""
    if not API_KEY:
        print("websearch_retrieval: LANGSEARCH_API_KEY not set, skipping")
        return []
    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"query": term, "summary": True, "count": max_sources},
            timeout=15,
        )
        resp.raise_for_status()
        pages = resp.json().get("data", {}).get("webPages", {}).get("value", []) or []
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"websearch_retrieval: search failed for {term!r}: {e}")
        pages = []
    if trace is not None:
        trace.setdefault("queries_tried", []).append({"source": ORIGIN, "query": term, "hits": len(pages)})
    return pages


def retrieve_evidence(claim, max_sources=5, trace=None):
    """Given a claim, return a list of {title, extract, url, origin} evidence
    candidates from general web search. Same concept-based query strategy as
    the other sources (see query_strategy.py) for consistency, even though
    LangSearch — unlike MedlinePlus/Wikipedia's exact-term search — can
    handle a full natural-language query fine on its own; keeping one
    strategy across all sources keeps behavior easier to reason about and
    reuses the already-validated proper-noun-first concept ranking.

    max_sources bumped from 3 to 5: with LangSearch as the only source
    (dev-langsearch-only), the English-only filter below can otherwise
    leave too little evidence to work with — confirmed directly, "Napoleon
    Bonaparte" returned 3 hits at count=3 but 2 were non-English (Chinese,
    French), leaving 0 usable evidence after filtering. Requesting more
    up front gives the filter more to work with.

    Prefers each result's "summary" (a fuller extract) over "snippet" (a
    short, "..."-truncated excerpt) for the text handed to the NLI
    classifier — same "richer text, truncate before tokenizing" pattern used
    for MedlinePlus and Wikipedia."""
    pages = []
    query_used = None
    for query in query_candidates(claim):
        pages = _search(query, max_sources, trace=trace)
        if pages:
            query_used = query
            break

    if trace is not None:
        trace.setdefault("query_used", {})[ORIGIN] = query_used

    evidence = []
    for page in pages:
        text = page.get("summary") or page.get("snippet")
        if not text or not _looks_english(text):
            continue
        evidence.append(
            {
                "title": page.get("name") or page.get("url"),
                "extract": text,
                "url": page.get("url"),
                "origin": ORIGIN,
            }
        )
    return evidence


def _looks_english(text):
    """LangSearch has no language parameter and mixes in non-English pages
    by default — confirmed directly: a plain "Australia" query returned
    Chinese (baike.com), Spanish, and Portuguese Wikipedia mirrors alongside
    English government pages, with no field in the response to distinguish
    them. The NLI classifier is English-only, so a non-English match would
    get scored anyway, producing an unreliable entailment/contradiction
    score rather than a clean skip — confirmed this already happened once:
    a Spanish "Australia" Wikipedia mirror scored 0.79 "contradiction"
    against an English claim. Fails open (keeps the text) on a detection
    error rather than losing evidence over a harmless short-text edge case."""
    try:
        return detect(text) == "en"
    except LangDetectException:
        return True


if __name__ == "__main__":
    import json
    import sys

    claim = " ".join(sys.argv[1:]) or "The capital of Australia is Sydney"
    print(json.dumps(retrieve_evidence(claim), indent=2))
