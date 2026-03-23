from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.text import extract_keywords, normalize_for_retrieval, normalize_text

INTENT_VALUES = (
    "definition",
    "attribute_lookup",
    "comparison",
    "composition",
    "diagram_elements",
    "diagram_explanation",
    "general",
)

ENTITY_ALIASES: dict[str, list[str]] = {
    "stack": ["stack", "стек"],
    "heap": ["heap", "куча"],
    "ram": ["ram"],
    "ram_machine": ["random access machine", "random-access machine", "машина с произвольным доступом"],
    "ram_memory": ["random access memory", "оперативная память", "озу"],
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
    "composition": ["из чего состоит", "состоит из", "входит", "компонент", "contains", "consists of", "parts"],
    "diagram_elements": ["какие элементы", "какие блоки", "подписи", "labels", "elements", "blocks"],
    "diagram_explanation": [
        "объясни схему",
        "объясни рисунок",
        "что изображено",
        "что показано",
        "как работает",
        "как устроен",
        "как связаны блоки",
        "diagram",
        "figure",
        "layout",
        "architecture",
    ],
    "attribute_lookup": ["содержит", "что хранится", "где хранятся", "contains"],
}

ENTITY_EXPANSIONS: dict[str, list[str]] = {
    "stack": ["стек", "stack"],
    "heap": ["куча", "heap"],
    "ram": ["ram", "random access memory", "оперативная память", "random access machine"],
    "ram_machine": ["random access machine", "машина с произвольным доступом", "ram architecture"],
    "ram_memory": ["random access memory", "оперативная память", "main memory"],
    "alu": ["alu", "arithmetic logic unit", "арифметико-логическое устройство"],
    "von_neumann": ["фон неймана", "фон неимана", "von neumann"],
    "primitive_types": ["primitive types", "примитивные типы"],
    "reference_types": ["reference types", "ссылочные типы"],
}

RELATION_EXPANSIONS: dict[str, list[str]] = {
    "storage": ["storage", "место хранения", "хранится"],
    "compare": ["difference", "compare", "отличается", "разница"],
    "definition": ["definition", "что такое", "означает"],
    "composition": ["components", "parts", "входит", "состоит"],
    "diagram_elements": ["diagram elements", "блоки", "labels", "подписи"],
    "diagram_explanation": ["diagram", "схема", "рисунок", "layout", "architecture"],
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
    expected_answer_shape: str


def normalize_and_expand_query(query: str) -> ProcessedQuery:
    normalized = normalize_text(query)
    normalized_retrieval = normalize_for_retrieval(query)
    keywords = extract_keywords(query, max_terms=10)
    entities = extract_entities(normalized)
    relations = extract_relations(normalized)
    structure = detect_question_structure(normalized, entities)
    question_intent = infer_question_intent(normalized, entities, relations, structure)
    expected_answer_shape = infer_expected_answer_shape(question_intent)

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
        expected_answer_shape=expected_answer_shape,
    )


def extract_entities(normalized_query: str) -> list[str]:
    normalized_query_retrieval = normalize_for_retrieval(normalized_query)
    found: list[str] = []
    for entity, aliases in ENTITY_ALIASES.items():
        if any(_phrase_match(normalized_query, normalized_query_retrieval, alias) for alias in aliases):
            found.append(entity)
    return found


def extract_relations(normalized_query: str) -> list[str]:
    normalized_query_retrieval = normalize_for_retrieval(normalized_query)
    found: list[str] = []
    for relation, aliases in RELATION_ALIASES.items():
        if any(_phrase_match(normalized_query, normalized_query_retrieval, alias) for alias in aliases):
            found.append(relation)
    return found


def detect_question_structure(normalized_query: str, entities: list[str]) -> str:
    if ("чем" in normalized_query and "отлич" in normalized_query) or "разница" in normalized_query:
        return "x_vs_y"
    if len(entities) >= 2 and any(tok in normalized_query for tok in ["vs", "versus", "между", "и"]):
        return "x_vs_y"
    if any(tok in normalized_query for tok in ["что хранится в", "где хранятся", "где хранится"]):
        return "attribute_in_entity"
    if any(tok in normalized_query for tok in ["что входит", "из чего состоит", "состоит из"]):
        return "composition_of_entity"
    if any(tok in normalized_query for tok in ["какие элементы", "какие блоки", "элементы на схеме", "блоки на схеме"]):
        return "diagram_elements"
    if any(
        tok in normalized_query
        for tok in ["что изображено", "что показано", "на схеме", "на рисунке", "объясни схему", "как работает", "как устроен"]
    ):
        return "diagram_explanation"
    return "generic"


def infer_question_intent(
    normalized_query: str,
    entities: list[str],
    relations: list[str],
    structure: str,
) -> str:
    if structure == "x_vs_y" or "compare" in relations:
        return "comparison"
    if structure == "composition_of_entity" or "composition" in relations:
        return "composition"
    if structure == "diagram_elements" or "diagram_elements" in relations:
        return "diagram_elements"
    if structure == "diagram_explanation" or "diagram_explanation" in relations:
        return "diagram_explanation"
    if "definition" in relations or normalized_query.startswith("что такое"):
        return "definition"
    if "attribute_lookup" in relations or "storage" in relations or structure == "attribute_in_entity":
        return "attribute_lookup"
    return "general"


def infer_expected_answer_shape(question_intent: str) -> str:
    shape_by_intent = {
        "definition": "X — это ...",
        "attribute_lookup": "По материалам, X хранит/содержит ...",
        "comparison": "X — ..., а Y — ...",
        "composition": "В X входят A, B, C...",
        "diagram_elements": "На схеме показаны: A, B, C...",
        "diagram_explanation": "На схеме изображены ... ; их роль: ...",
        "general": "Краткий ответ по подтвержденным фактам.",
    }
    return shape_by_intent.get(question_intent, shape_by_intent["general"])


def _phrase_match(normalized_query: str, normalized_query_retrieval: str, phrase: str) -> bool:
    p_norm = normalize_text(phrase)
    if p_norm and p_norm in normalized_query:
        return True
    p_retrieval = normalize_for_retrieval(phrase)
    if p_retrieval and p_retrieval in normalized_query_retrieval:
        return True
    p_tokens = [t for t in p_retrieval.split() if t]
    q_tokens = set(normalized_query_retrieval.split())
    return bool(p_tokens) and all(t in q_tokens for t in p_tokens)
