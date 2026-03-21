from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.text import extract_keywords, normalize_for_retrieval, normalize_text


@dataclass
class ProcessedQuery:
    original: str
    normalized: str
    retrieval_forms: list[str]
    keywords: list[str]


def normalize_and_expand_query(query: str) -> ProcessedQuery:
    normalized = normalize_text(query)
    normalized_retrieval = normalize_for_retrieval(query)
    keywords = extract_keywords(query, max_terms=10)

    forms = [query.strip(), normalized, normalized_retrieval]

    aliases = {
        "ram": ["random access machine", "random access memory", "оперативная память"],
        "оперативная память": ["ram", "random access memory"],
        "схема": ["diagram", "architecture", "scheme"],
        "принцип работы": ["how it works", "workflow", "mechanism"],
        "grammar": ["грамматика"],
        "context-free": ["cf", "контекстно-свободная"],
    }
    q_low = normalized
    for key, vals in aliases.items():
        if key in q_low:
            forms.extend(vals)
    forms.extend(keywords[:5])

    dedup: list[str] = []
    seen: set[str] = set()
    for f in forms:
        f = re.sub(r"\s+", " ", f.strip())
        if not f or f in seen:
            continue
        seen.add(f)
        dedup.append(f)
    return ProcessedQuery(original=query, normalized=normalized, retrieval_forms=dedup, keywords=keywords)
