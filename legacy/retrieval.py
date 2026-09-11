"""General-purpose evidence retrieval against Wikipedia — one of two sources
verify.py fans out to (see medical_retrieval.py for the medical-specific
source, kept alongside this one since it's meaningfully higher quality for
medical claims specifically).

This is the "trusted source" layer described in the master plan's Tier-1
source registry (Wikipedia, verified through citations). Swapping in more
general sources later just means adding more functions with the same
{title, extract, url, origin} return shape.
"""

import requests

from query_strategy import query_candidates

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "FactVerificationPrototype/0.1 (research prototype)"
ORIGIN = "Wikipedia"


def _search_titles(term, limit, trace=None):
    """Returns [] on any network failure rather than raising — matches
    medical_retrieval._search()'s degrade-safely behavior."""
    params = {"action": "query", "list": "search", "srsearch": term, "format": "json", "srlimit": limit}
    try:
        resp = requests.get(API_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        titles = [r["title"] for r in resp.json().get("query", {}).get("search", [])]
    except requests.exceptions.RequestException as e:
        print(f"retrieval: search failed for {term!r}: {e}")
        titles = []
    if trace is not None:
        trace.setdefault("queries_tried", []).append({"source": ORIGIN, "query": term, "hits": len(titles)})
    return titles


def _get_extract(title):
    """The REST /page/summary/ endpoint (used previously) only returns the
    first ~500-char paragraph of the lead, which routinely misses facts that
    show up later in the lead section — confirmed directly: the "Australia"
    summary never mentions "Canberra" at all, so "The capital of Australia
    is Sydney" had nothing to compare against and fell back to
    insufficient_evidence instead of a confident contradiction. The
    query-API's prop=extracts&exintro=true returns the FULL lead section
    (all paragraphs before the first heading, ~2700 chars for Australia,
    which does mention Canberra) — same "richer article, truncate before
    tokenizing" approach already used for MedlinePlus."""
    params = {
        "action": "query",
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "titles": title,
        "format": "json",
        "formatversion": "2",
    }
    try:
        resp = requests.get(API_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", [])
    except requests.exceptions.RequestException as e:
        print(f"retrieval: extract fetch failed for {title!r}: {e}")
        return None
    if not pages or not pages[0].get("extract"):
        return None
    page = pages[0]
    return {
        "title": page["title"],
        "extract": page["extract"],
        "url": "https://en.wikipedia.org/wiki/" + requests.utils.quote(page["title"].replace(" ", "_")),
        "origin": ORIGIN,
    }


def retrieve_evidence(claim, max_sources=3, trace=None):
    """Given a claim, return a list of {title, extract, url, origin} evidence
    candidates from Wikipedia. Same query strategy as medical_retrieval.py
    (concept-based search, most salient concept first) rather than the raw
    claim text, for the same reason: a full sentence rarely matches any
    single Wikipedia article title, while an extracted concept usually does."""
    titles = []
    query_used = None
    for query in query_candidates(claim):
        titles = _search_titles(query, max_sources, trace=trace)
        if titles:
            query_used = query
            break

    if trace is not None:
        trace.setdefault("query_used", {})[ORIGIN] = query_used

    evidence = []
    for title in titles:
        extract = _get_extract(title)
        if extract:
            evidence.append(extract)
    return evidence


if __name__ == "__main__":
    import json
    import sys

    claim = " ".join(sys.argv[1:]) or "The capital of Australia is Sydney"
    print(json.dumps(retrieve_evidence(claim), indent=2))
