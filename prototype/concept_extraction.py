"""Phase 1.1: reduce a claim to its core medical concepts before searching
for evidence, instead of using the raw sentence (or a crude stopword-strip
of it) as the search query.

Confirmed directly this session that searching on a full sentence — even a
stopword-stripped one — routinely fails against MedlinePlus (0 results) or
succeeds but on an unrelated page (e.g. "The flu vaccine cannot give you
the flu" matched a "Gastroenteritis" page). This is a lightweight, local,
free noun-phrase extractor (spaCy's small English model, ~15MB, no GPU) —
not a medical-specific NER model, which would be a heavier, riskier
download on this machine's RAM budget. Good enough to identify "the actual
topic of this sentence" without needing to understand medicine.
"""

import re

import spacy

_nlp = None

# "Sinusitis: Severe sinus congestion..." / "Conjunctivitis (Pink Eye): ..."
# — a disease-name heading followed by a colon is extremely common in real
# pasted health articles (confirmed directly this session: two separate
# headings in one test paragraph followed exactly this shape). spaCy's
# parser doesn't reliably form a noun chunk out of a bare heading fragment
# like this, and even when it does ("Conjunctivitis" on its own), a single
# token loses to longer, less useful generic phrases under content-token
# scoring. The disease name is usually the single best search anchor
# (it's often the literal MedlinePlus page title), so pull it out directly
# rather than relying on the general noun-chunk parse for this shape.
_HEADING_RE = re.compile(r"^([A-Z][A-Za-z][A-Za-z\s]{1,30}?)(?:\s*\(([^)]+)\))?\s*:")


def _load():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm", disable=["lemmatizer", "ner"])
    return _nlp


def extract_concepts(claim, max_concepts=3):
    """Return the claim's most salient noun phrases, most content-rich
    first — e.g. "Antibiotics do not work against viral infections like the
    common cold" -> ["viral infections", "the common cold", "Antibiotics"].

    A leading "Heading (Alt name): ..." pattern is extracted first and
    always ranked highest, since it's usually the exact disease/condition
    name. Remaining slots are filled by noun chunks, scored by count of
    non-stopword tokens (a longer, more specific phrase like "severe sinus
    congestion" is a better search anchor than a short generic one like
    "pressure") — except the scoring only applies among chunks; the heading
    match always wins regardless of its own (often short) length.
    """
    concepts = []
    seen = set()

    heading = _HEADING_RE.match(claim)
    if heading:
        for group in (heading.group(1), heading.group(2)):
            if group:
                text = group.strip()
                key = text.lower()
                if key not in seen:
                    seen.add(key)
                    concepts.append(text)

    nlp = _load()
    doc = nlp(claim)

    scored = []
    for chunk in doc.noun_chunks:
        content_tokens = [t for t in chunk if not t.is_stop and not t.is_punct]
        if not content_tokens:
            continue
        text = chunk.text.strip(" ()[]{}:;,.\"'")
        if len(text) < 3:
            continue
        scored.append((len(content_tokens), chunk.start, text))

    scored.sort(key=lambda x: (-x[0], x[1]))

    for _, _, text in scored:
        if len(concepts) >= max_concepts:
            break
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        concepts.append(text)

    return concepts[:max_concepts]


if __name__ == "__main__":
    import sys

    claim = " ".join(sys.argv[1:]) or "Antibiotics do not work against viral infections like the common cold"
    print(extract_concepts(claim))
