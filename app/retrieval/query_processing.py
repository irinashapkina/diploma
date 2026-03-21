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
        "ram": [
            "random access machine",
            "random access memory",
            "оперативная память",
            "память с произвольным доступом",
        ],
        "random access machine": ["ram", "random access memory"],
        "random access memory": ["ram", "оперативная память"],
        "оперативная память": ["ram", "random access memory"],
        "java": ["jav", "gava"],
        "фон неймана": ["фон неимана", "von neumann", "neumann", "neiman"],
        "фон неимана": ["фон неймана", "von neumann"],
        "von neumann": ["фон неймана", "фон неимана", "neiman"],
        "alu": ["arithmetic logic unit", "арифметико-логическое устройство"],
        "stack": ["стек"],
        "heap": ["куча"],
        "схема": ["diagram", "architecture", "scheme", "layout"],
        "архитектура": ["architecture", "diagram", "устройство"],
        "принцип работы": ["how it works", "workflow", "mechanism"],
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
