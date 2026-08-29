"""Shared keyword extraction, used by both medical_retrieval.py (query
fallback) and local_classifier.py (distinctive-terms check). Split out once
a second real use case appeared rather than duplicating the stopword list.
"""

import re

STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "not", "no", "cannot", "can", "could", "should",
    "would", "will", "to", "of", "in", "on", "at", "for", "and", "or",
    "but", "with", "like", "than", "that", "this", "these", "those", "it",
    "its", "you", "your", "i", "we", "they", "he", "she", "them", "as",
    "also", "means", "mean", "if", "so", "than", "have", "has", "had",
    "by", "more", "some", "any", "all",
})


def keywords(text):
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS]
