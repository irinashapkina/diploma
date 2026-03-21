from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.text import extract_keywords, normalize_for_retrieval, normalize_text

INTENT_VALUES = (
    "definition",
    "explanation",
    "attribute_lookup",
    "comparison",
    "relation",
    "mechanism",
    "diagram_layout",
    "yes_no",
    "general",
)

ENTITY_ALIASES: dict[str, list[str]] = {
    "stack": ["stack", "стек"],
    "heap": ["heap", "куча"],
    "ram": ["ram", "random access memory", "оперативная память", "random access machine"],
    "java": ["java", "jav", "gava"],
    "boolean": ["boolean", "логический тип", "bool"],
    "alu": ["alu", "arithmetic logic unit", "арифметико-логическое устройство"],
    "von_neumann": ["фон неймана", "фон неимана", "von neumann", "neumann", "neiman"],
    "processor": ["процессор", "processor", "cpu"],
    "memory": ["память", "memory"],
    "primitive_types": ["primitive types", "примитивные типы", "переменные примитивного типа"],
    "reference_types": ["reference types", "ссылочные типы", "данные ссылочного типа"],
}

RELATION_ALIASES: dict[str, list[str]] = {
    "definition": ["что такое", "означает", "define", "definition", "термин"],
    "storage": ["хранится", "хранение", "хранить", "где находится", "место хранения", "store", "stores", "storage"],
    "compare": ["чем отличается", "разница", "различие", "сравни", "compare", "difference"],
    "mechanism": ["как работает", "как устроен", "принцип работы", "механизм", "how works", "mechanism"],
    "relation": ["как связан", "связаны", "related", "relation", "зависит"],
    "diagram_description": [
        "что показано",
        "что изображено",
        "объясни схему",
        "объясни рисунок",
        "блок",
        "стрелк",
        "diagram",
        "figure",
        "layout",
    ],
    "purpose": ["для чего", "зачем", "why used", "purpose", "используется для"],
    "attribute_lookup": ["из чего состоит", "содержит", "что хранится", "где хранятся", "contains", "consists of"],
    "yes_no": ["есть ли", "говорится ли", "упоминается ли", "is there", "does it mention"],
}

ENTITY_EXPANSIONS: dict[str, list[str]] = {
    "stack": ["стек", "stack"],
    "heap": ["куча", "heap"],
    "ram": ["ram", "random access memory", "оперативная память", "random access machine"],
    "alu": ["alu", "arithmetic logic unit", "арифметико-логическое устройство"],
    "von_neumann": ["фон неймана", "фон неимана", "von neumann"],
    "primitive_types": ["primitive types", "примитивные типы"],
    "reference_types": ["reference types", "ссылочные типы"],
}

RELATION_EXPANSIONS: dict[str, list[str]] = {
    "storage": ["storage", "место хранения", "хранится"],
    "compare": ["difference", "compare", "отличается", "разница"],
    "definition": ["definition", "что такое", "означает"],
    "mechanism": ["mechanism", "принцип работы", "как устроен"],
    "diagram_description": ["diagram", "схема", "рисунок", "layout"],
}


@dataclass
class ProcessedQuery:
    original: str
    normalized: str
    retrieval_forms: list[str]
    keywords: list[str]
    question_intent: str
    entities: list[str]
    normalized_relations: list[str]
    structure: str


def normalize_and_expand_query(query: str) -> ProcessedQuery:
    normalized = normalize_text(query)
    normalized_retrieval = normalize_for_retrieval(query)
    keywords = extract_keywords(query, max_terms=10)
    entities = extract_entities(normalized)
    relations = extract_relations(normalized)
    structure = detect_question_structure(normalized, entities)
    question_intent = infer_question_intent(normalized, entities, relations, structure)

    forms = [query.strip(), normalized, normalized_retrieval]
    for ent in entities:
        forms.extend(ENTITY_EXPANSIONS.get(ent, []))
    for rel in relations:
        forms.extend(RELATION_EXPANSIONS.get(rel, []))
    forms.extend(keywords[:5])

    dedup: list[str] = []
    seen: set[str] = set()
    for f in forms:
        f = re.sub(r"\s+", " ", f.strip())
        if not f or f in seen:
            continue
        seen.add(f)
        dedup.append(f)
    return ProcessedQuery(
        original=query,
        normalized=normalized,
        retrieval_forms=dedup,
        keywords=keywords,
        question_intent=question_intent,
        entities=entities,
        normalized_relations=relations,
        structure=structure,
    )


def extract_entities(normalized_query: str) -> list[str]:
    found: list[str] = []
    for entity, aliases in ENTITY_ALIASES.items():
        if any(alias in normalized_query for alias in aliases):
            found.append(entity)
    return found


def extract_relations(normalized_query: str) -> list[str]:
    found: list[str] = []
    for relation, aliases in RELATION_ALIASES.items():
        if any(alias in normalized_query for alias in aliases):
            found.append(relation)
    return found


def detect_question_structure(normalized_query: str, entities: list[str]) -> str:
    if ("чем" in normalized_query and "отлич" in normalized_query) or "разница" in normalized_query:
        return "x_vs_y"
    if len(entities) >= 2 and any(tok in normalized_query for tok in ["vs", "versus", "между", "и"]):
        return "x_vs_y"
    if any(tok in normalized_query for tok in ["что хранится в", "где хранятся", "где хранится"]):
        return "attribute_in_entity"
    if any(tok in normalized_query for tok in ["как устроен", "как работает"]):
        return "mechanism_of_entity"
    if any(tok in normalized_query for tok in ["что изображено", "что показано", "на схеме", "на рисунке"]):
        return "diagram_description"
    return "generic"


def infer_question_intent(
    normalized_query: str,
    entities: list[str],
    relations: list[str],
    structure: str,
) -> str:
    if "yes_no" in relations:
        return "yes_no"
    if structure == "x_vs_y" or "compare" in relations:
        return "comparison"
    if structure == "diagram_description" or "diagram_description" in relations:
        return "diagram_layout"
    if structure == "mechanism_of_entity" or "mechanism" in relations:
        return "mechanism"
    if "definition" in relations or normalized_query.startswith("что такое"):
        return "definition"
    if "attribute_lookup" in relations or "storage" in relations or structure == "attribute_in_entity":
        return "attribute_lookup"
    if "purpose" in relations:
        return "explanation"
    if "relation" in relations:
        return "relation"
    if any(tok in normalized_query for tok in ["объясни", "explain"]) and entities:
        return "explanation"
    return "general"
