"""Evidence retrieval against Wikipedia for the general-trivia MVP domain.

This is the "trusted source" layer described in the master plan's Tier-1
source registry (Wikipedia, verified through citations). Swapping in more
sources later just means adding more functions with the same return shape.
"""

import requests

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
USER_AGENT = "FactVerificationPrototype/0.1 (research prototype)"


def search_titles(query, limit=3):
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": limit,
    }
    resp = requests.get(SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
    resp.raise_for_status()
    return [r["title"] for r in resp.json().get("query", {}).get("search", [])]


def get_summary(title):
    url = SUMMARY_URL.format(title=requests.utils.quote(title))
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {
        "title": data.get("title"),
        "extract": data.get("extract"),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
    }


def retrieve_evidence(claim, max_sources=3):
    """Given a claim, return a list of {title, extract, url} evidence candidates."""
    titles = search_titles(claim, limit=max_sources)
    evidence = []
    for title in titles:
        summary = get_summary(title)
        if summary and summary.get("extract"):
            evidence.append(summary)
    return evidence


if __name__ == "__main__":
    import sys
    import json

    claim = " ".join(sys.argv[1:]) or "The capital of Australia is Sydney"
    print(json.dumps(retrieve_evidence(claim), indent=2))
