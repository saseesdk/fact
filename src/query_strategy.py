"""Shared query-building strategy for any evidence source (MedlinePlus,
Wikipedia, ...). Split out once a second retrieval module needed the exact
same approach that was validated on MedlinePlus, to avoid the two drifting
apart.

Yields queries in priority order: extracted concepts first (Phase 1.1,
concept_extraction.py), each tried individually and most-salient-first, then
the raw claim / stopword-stripped claim as a last resort.

Concepts are tried one at a time rather than joined together, since these
sources' search appears to require most/all terms in a query to co-occur in
a document — confirmed directly on MedlinePlus: 'diabetes cured water' (3
words) gets 0 results even though 'diabetes water' and 'diabetes cure' each
get 30+ results individually. A single extracted concept is usually specific
enough to be safe on its own (e.g. "Sinusitis" finds the exact right page
directly) — this is different from a single *generic keyword* fallback
(e.g. bare "diabetes"), which surfaces a broad, only tangentially-related
page and can make an NLI model mistake lexical overlap for entailment. A
concept like "Type 1 diabetes" or "the common cold" is meaningfully narrower
than the bare category name that caused those false positives.
"""

import re

from concept_extraction import extract_concepts
from keywords import keywords as _keywords


def strip_leading_quantity(concept):
    """Drop a leading bare number/dose token ("10", "500mg") from a search
    term. Confirmed directly on MedlinePlus: "10 paracetamol" searched
    verbatim returned two unrelated pages (Chickenpox, Fifth Disease, which
    only coincidentally mention giving a child acetaminophen for fever),
    while bare "paracetamol" correctly finds "Pain Relievers" — the search
    engine has no concept of "10" as a dosage, it's just another term to
    match. The concept itself (with its number) is untouched elsewhere, so
    local_classifier's numeric distinctive-terms check still has the number
    to require in the evidence."""
    words = concept.split()
    while words and re.match(r"^\d", words[0]):
        words.pop(0)
    return " ".join(words) if words else concept


def query_candidates(claim):
    for concept in extract_concepts(claim):
        yield strip_leading_quantity(concept)
    yield claim
    kws = _keywords(claim)
    if kws:
        yield " ".join(kws)
