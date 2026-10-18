"""BM25 keyword ranking and reciprocal rank fusion; no model downloads."""

import math
import re
from collections import Counter

ALIASES = {
    "delivery": "deliver",
    "delivered": "deliver",
    "shipping": "ship",
    "shipped": "ship",
    "refunds": "refund",
    "cancellation": "cancel",
    "cancellations": "cancel",
    "days": "day",
    "seven": "7",
    "hours": "hour",
}
STOPWORDS = set(
    "a an the is are was were to of for and or in on my me i it how what when can do does please policy".split()
)


def tokenize(text):
    return [
        ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in STOPWORDS
    ]


def keyword_rank(query, chunks, limit=10):
    terms = set(tokenize(query))
    if not terms or not chunks:
        return []
    documents = [Counter(tokenize(chunk.source + " " + chunk.text)) for chunk in chunks]
    lengths = [sum(document.values()) for document in documents]
    average = sum(lengths) / len(lengths) or 1
    frequencies = {term: sum(term in document for document in documents) for term in terms}
    scores = []
    for chunk, document, length in zip(chunks, documents, lengths):
        score = 0
        for term in terms:
            count = document[term]
            if count:
                idf = math.log(
                    1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
                )
                score += idf * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * length / average))
        if score > 0:
            scores.append((chunk.id, score))
    return sorted(scores, key=lambda item: (-item[1], item[0]))[:limit]


def fuse_ranks(keyword_ids, vector_ids, limit=3):
    scores = {}
    methods = {}
    for method, identifiers in [("keyword", keyword_ids), ("vector", vector_ids)]:
        for rank, identifier in enumerate(dict.fromkeys(identifiers), start=1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank)
            methods.setdefault(identifier, []).append(method)
    return [
        (identifier, scores[identifier], methods[identifier])
        for identifier in sorted(scores, key=lambda value: (-scores[value], value))[:limit]
    ]
