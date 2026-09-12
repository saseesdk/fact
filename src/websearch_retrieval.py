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

from concept_extraction import extract_concepts
from keywords import keywords as _keywords
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


# issue #20: a single query's hits were the whole evidence pool — if that
# one query happened to be off-target (or LangSearch just didn't have much
# for it), the classifier had little or nothing to work with, and there was
# no way for one bad query result to be outweighed by a better one from a
# different angle on the same claim. Merging results from *multiple* query
# candidates instead of stopping at the first one that returns anything
# fixes both complaints in the issue at once: more evidence overall (closer
# to the "at least 5" target), and less chance that the *only* evidence is
# an irrelevant one-off hit, since a genuinely on-topic page tends to show
# up for more than one phrasing of the same claim.
TARGET_EVIDENCE = 8
MAX_QUERIES_TRIED = 4


def _anchor_terms(claim):
    """The claim's primary-concept keywords, computed once per retrieve_evidence
    call (not per candidate page — extract_concepts() runs a spaCy parse, no
    reason to repeat it for every one of a dozen search results)."""
    concepts = extract_concepts(claim)
    return _keywords(concepts[0]) if concepts else _keywords(claim)


def _looks_relevant(anchor_terms, title, text):
    """Cheap, deterministic relevance gate before evidence ever reaches the
    (much more expensive) NLI classifier: does this result even mention the
    claim's main topic anywhere in its title or extract? This is not the
    same check as local_classifier._addresses_claim_specifics (which checks
    the claim's *secondary* concepts and numbers against the single winning
    source, after scoring) — this one runs on every candidate, before
    scoring, purely to keep obviously off-topic search noise (confirmed
    directly: a "APPLE Definition & Meaning | Dictionary.com" hit for
    "Eating an apple a day guarantees you will never get sick") from ever
    reaching the model, or from crowding out a genuinely relevant result
    when only a handful of evidence slots are kept.

    Anchored on the claim's *primary* extracted concept only (not every
    concept) — requiring all concepts would reject legitimate results that
    just don't happen to restate every noun phrase from the claim, which is
    normal, not a sign of irrelevance."""
    if not anchor_terms:
        return True
    haystack = f"{title} {text}".lower()
    return any(term in haystack for term in anchor_terms)


def retrieve_evidence(claim, max_sources=5, trace=None):
    """Given a claim, return a list of {title, extract, url, origin} evidence
    candidates from general web search. Same concept-based query strategy as
    the other sources (see query_strategy.py) for consistency, even though
    LangSearch — unlike MedlinePlus/Wikipedia's exact-term search — can
    handle a full natural-language query fine on its own; keeping one
    strategy across all sources keeps behavior easier to reason about and
    reuses the already-validated proper-noun-first concept ranking.

    Tries query candidates in priority order, merging (and de-duplicating by
    URL) results across all of them — not just the first that returns
    anything — until TARGET_EVIDENCE post-filter results are collected or
    MAX_QUERIES_TRIED candidates have been tried, whichever comes first. The
    query-candidate cap bounds network calls (each is a real LangSearch
    round trip); the evidence-count cap bounds how much gets fed to the
    (slow, CPU-only) NLI classifier downstream — more evidence per claim
    means more comparisons, so this is a deliberate recall/speed tradeoff,
    not free.

    Prefers each result's "summary" (a fuller extract) over "snippet" (a
    short, "..."-truncated excerpt) for the text handed to the NLI
    classifier — same "richer text, truncate before tokenizing" pattern used
    for MedlinePlus and Wikipedia."""
    anchor_terms = _anchor_terms(claim)
    evidence = []
    seen_urls = set()
    queries_tried = 0
    contributing_queries = []

    for query in query_candidates(claim):
        if len(evidence) >= TARGET_EVIDENCE or queries_tried >= MAX_QUERIES_TRIED:
            break
        pages = _search(query, max_sources, trace=trace)
        queries_tried += 1
        added_this_query = 0

        for page in pages:
            if len(evidence) >= TARGET_EVIDENCE:
                break
            url = page.get("url")
            if not url or url in seen_urls:
                continue
            text = page.get("summary") or page.get("snippet")
            if not text or not _looks_english(text):
                continue
            title = page.get("name") or url
            if not _looks_relevant(anchor_terms, title, text):
                continue
            seen_urls.add(url)
            evidence.append({"title": title, "extract": text, "url": url, "origin": ORIGIN})
            added_this_query += 1

        if added_this_query:
            contributing_queries.append(query)

    if trace is not None:
        trace.setdefault("query_used", {})[ORIGIN] = contributing_queries

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
