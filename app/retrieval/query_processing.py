from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.text import extract_keywords, normalize_for_retrieval, normalize_text

INTENT_VALUES = (
    "definition",
    "fact_lookup",
    "attribute_lookup",
    "comparison",
    "composition",
    "component_role",
    "process_explanation",
    "interaction_explanation",
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
    "spring": ["spring", "спринг"],
    "hibernate": ["hibernate", "хибернейт", "хайбернейт"],
    "jvm": ["jvm", "джава виртуальная машина", "джавиэм", "jvm машина"],
    "jdk": ["jdk", "джава девелопмент кит", "джейдикей", "джедикей"],
    "docker": ["docker", "докер"],
    "rest": ["rest", "рест", "rest api"],
    "api": ["api", "апи"],
    "boolean": ["boolean", "логический тип", "bool"],
    "alu": ["alu", "arithmetic logic unit", "арифметико-логическое устройство"],
    "control_unit": ["уу", "устройство управления", "control unit", "cu"],
    "von_neumann": ["фон неймана", "фон неимана", "von neumann", "neumann", "neiman"],
    "processor": ["процессор", "processor", "cpu"],
    "memory": ["память", "memory"],
    "primitive_types": ["primitive types", "примитивные типы", "переменные примитивного типа"],
    "reference_types": ["reference types", "ссылочные типы", "данные ссылочного типа"],
}

RELATION_ALIASES: dict[str, list[str]] = {
    "definition": ["что такое", "означает", "define", "definition", "термин"],
    "fact_lookup": ["назови", "перечисли", "какие есть", "какой", "what are", "list"],
    "storage": ["хранится", "хранение", "хранить", "где находится", "место хранения", "store", "stores", "storage"],
    "compare": ["чем отличается", "разница", "различие", "сравни", "compare", "difference"],
    "composition": ["из чего состоит", "состоит из", "входит", "компонент", "contains", "consists of", "parts"],
    "diagram_elements": ["какие элементы", "какие блоки", "подписи", "labels", "elements", "blocks"],
    "diagram_explanation": [
        "объясни схему",
        "объясни рисунок",
        "что изображено",
        "что показано",
        "как связаны блоки",
        "diagram",
        "figure",
        "layout",
        "architecture",
    ],
    "attribute_lookup": ["содержит", "что хранится", "где хранятся", "contains"],
    "process_explanation": [
        "как работает",
        "как происходит",
        "как устроен процесс",
        "по шагам",
        "механизм",
        "workflow",
        "process",
        "flow",
    ],
    "interaction_explanation": [
        "как взаимодействуют",
        "как связаны",
        "взаимодействие блоков",
        "взаимосвязь",
        "кто с кем взаимодействует",
        "interaction",
        "interact",
    ],
    "component_role": [
        "роль",
        "что делает",
        "за что отвечает",
        "функция блока",
        "какую функцию выполняет",
        "what does",
        "responsible for",
    ],
}

ENTITY_EXPANSIONS: dict[str, list[str]] = {
    "stack": ["стек", "stack"],
    "heap": ["куча", "heap"],
    "ram": ["ram", "random access memory", "оперативная память", "random access machine"],
    "ram_machine": ["random access machine", "машина с произвольным доступом", "ram architecture"],
    "ram_memory": ["random access memory", "оперативная память", "main memory"],
    "spring": ["spring", "спринг", "spring framework"],
    "hibernate": ["hibernate", "хибернейт", "orm"],
    "jvm": ["jvm", "java virtual machine", "джава виртуальная машина"],
    "jdk": ["jdk", "java development kit", "джейдикей"],
    "docker": ["docker", "докер", "контейнеризация"],
    "rest": ["rest", "rest api", "рест"],
    "api": ["api", "апи", "application programming interface"],
    "alu": ["alu", "arithmetic logic unit", "арифметико-логическое устройство"],
    "control_unit": ["control unit", "устройство управления", "уу"],
    "von_neumann": ["фон неймана", "фон неимана", "von neumann"],
    "primitive_types": ["primitive types", "примитивные типы"],
    "reference_types": ["reference types", "ссылочные типы"],
}

RELATION_EXPANSIONS: dict[str, list[str]] = {
    "storage": ["storage", "место хранения", "хранится"],
    "compare": ["difference", "compare", "отличается", "разница"],
    "definition": ["definition", "что такое", "означает"],
    "fact_lookup": ["назови", "перечисли", "какие есть", "список"],
    "composition": ["components", "parts", "входит", "состоит"],
    "diagram_elements": ["diagram elements", "блоки", "labels", "подписи"],
    "diagram_explanation": ["diagram", "схема", "рисунок", "layout", "architecture"],
    "process_explanation": ["как работает", "механизм работы", "последовательность шагов", "workflow"],
    "interaction_explanation": ["взаимодействие блоков", "связи между блоками", "flow between components"],
    "component_role": ["роль компонента", "функция блока", "за что отвечает"],
}

_STUDENT_NOISE_TOKENS = {
    "я",
    "мы",
    "мне",
    "нам",
    "не",
    "понимаю",
    "понимаем",
    "объясни",
    "поясни",
    "подробно",
    "попроще",
    "пожалуйста",
    "там",
    "тут",
    "как",
    "короче",
    "типа",
    "почему",
    "просто",
    "вообще",
    "это",
    "этот",
    "эта",
    "эти",
    "как-то",
    "можешь",
    "можно",
    "ли",
}

_ENTITY_CANONICAL_QUERY_TERM: dict[str, str] = {
    "stack": "stack",
    "heap": "heap",
    "ram": "ram",
    "ram_machine": "машина с произвольным доступом",
    "ram_memory": "оперативная память",
    "java": "java",
    "spring": "spring",
    "hibernate": "hibernate",
    "jvm": "jvm",
    "jdk": "jdk",
    "docker": "docker",
    "rest": "rest",
    "api": "api",
    "boolean": "boolean",
    "alu": "алу",
    "control_unit": "устройство управления",
    "von_neumann": "архитектура фон неймана",
    "processor": "процессор",
    "memory": "память",
    "primitive_types": "примитивные типы",
    "reference_types": "ссылочные типы",
}

_ENTITY_COMPONENT_HINTS: dict[str, list[str]] = {
    "von_neumann": ["память", "уу", "алу", "ввод", "вывод", "блоки"],
    "control_unit": ["управление", "команды", "память", "алу"],
    "ram_machine": ["alu", "control unit", "memory", "input", "output"],
    "ram_memory": ["ячейки", "данные", "адрес", "оперативная"],
}

_STUDENT_EXPLANATORY_MARKERS = (
    "я не понимаю",
    "не понимаю",
    "объясни",
    "поясни",
    "подробно объясни",
    "как это связано",
    "что происходит",
    "пошагово",
)


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
    visual_query: str
    retrieval_queries_academic: list[str]
    component_labels: list[str]


def normalize_and_expand_query(query: str) -> ProcessedQuery:
    normalized = normalize_text(query)
    normalized_retrieval = normalize_for_retrieval(query)
    keywords = extract_keywords(query, max_terms=10)
    entities = extract_entities(normalized)
    component_labels = extract_component_labels(query)
    relations = extract_relations(normalized)
    structure = detect_question_structure(normalized, entities)
    question_intent = infer_question_intent(normalized, entities, relations, structure)
    expected_answer_shape = infer_expected_answer_shape(question_intent)

    academic_forms = rewrite_student_query_for_retrieval(
        normalized_query=normalized,
        entities=entities,
        relations=relations,
        question_intent=question_intent,
        keywords=keywords,
        component_labels=component_labels,
    )
    forms = [query.strip(), normalized, normalized_retrieval] + academic_forms
    for ent in entities:
        forms.extend(ENTITY_EXPANSIONS.get(ent, []))
    for rel in relations:
        forms.extend(RELATION_EXPANSIONS.get(rel, []))
    forms.extend(keywords[:5])
    forms.extend(component_labels[:4])

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
        visual_query=build_visual_query(
            entities=entities,
            relations=relations,
            keywords=keywords,
            component_labels=component_labels,
            question_intent=question_intent,
            normalized_query=normalized,
        ),
        retrieval_queries_academic=academic_forms,
        component_labels=component_labels,
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
    if len(entities) >= 2 and any(tok in normalized_query for tok in ["vs", "versus", "между"]):
        return "x_vs_y"
    if any(tok in normalized_query for tok in ["что хранится в", "где хранятся", "где хранится"]):
        return "attribute_in_entity"
    if any(tok in normalized_query for tok in ["что входит", "из чего состоит", "состоит из"]):
        return "composition_of_entity"
    if any(tok in normalized_query for tok in ["роль", "что делает", "за что отвечает", "функция блока", "какую функцию"]):
        return "component_role"
    if any(tok in normalized_query for tok in ["какие элементы", "какие блоки", "элементы на схеме", "блоки на схеме"]):
        return "diagram_elements"
    if any(tok in normalized_query for tok in ["по схеме", "по рисунку"]):
        return "diagram_explanation"
    if any(
        tok in normalized_query
        for tok in ["что изображено", "что показано", "на схеме", "на рисунке", "объясни схему", "объясни рисунок"]
    ):
        return "diagram_explanation"
    if any(tok in normalized_query for tok in ["как взаимодейств", "взаимодействие", "как связаны блоки", "как связаны"]):
        return "interaction_explanation"
    if any(tok in normalized_query for tok in ["как работает", "по шагам", "как происходит", "механизм работы"]):
        return "process_explanation"
    if _looks_like_student_explanatory_question(normalized_query):
        if any(tok in normalized_query for tok in ["схема", "рисунок", "диаграм"]):
            return "diagram_explanation"
        if any(tok in normalized_query for tok in ["взаимодейств", "связ", "между блок"]):
            return "interaction_explanation"
        return "process_explanation"
    return "generic"


def infer_question_intent(
    normalized_query: str,
    entities: list[str],
    relations: list[str],
    structure: str,
) -> str:
    if structure == "x_vs_y":
        return "comparison"
    if structure == "composition_of_entity":
        return "composition"
    if structure == "component_role":
        return "component_role"
    if structure == "interaction_explanation":
        return "interaction_explanation"
    if structure == "process_explanation":
        return "process_explanation"
    if structure == "diagram_elements":
        return "diagram_elements"
    if structure == "diagram_explanation":
        return "diagram_explanation"
    if "compare" in relations:
        return "comparison"
    if "composition" in relations:
        return "composition"
    if "component_role" in relations:
        return "component_role"
    if "interaction_explanation" in relations:
        return "interaction_explanation"
    if "process_explanation" in relations:
        return "process_explanation"
    if "diagram_explanation" in relations:
        return "diagram_explanation"
    if "diagram_elements" in relations:
        return "diagram_elements"
    if _looks_like_student_explanatory_question(normalized_query):
        if any(tok in normalized_query for tok in ["схема", "рисунок", "диаграм", "по схеме", "по рисунку"]):
            return "diagram_explanation"
        if any(tok in normalized_query for tok in ["взаимодейств", "связ", "между блок"]):
            return "interaction_explanation"
        return "process_explanation"
    if "definition" in relations or normalized_query.startswith("что такое"):
        return "definition"
    if "fact_lookup" in relations:
        return "fact_lookup"
    if "attribute_lookup" in relations or "storage" in relations or structure == "attribute_in_entity":
        return "attribute_lookup"
    return "general"


def infer_expected_answer_shape(question_intent: str) -> str:
    shape_by_intent = {
        "definition": "X — это ...",
        "fact_lookup": "По материалам перечислены: A, B, C...",
        "attribute_lookup": "По материалам, X хранит/содержит ...",
        "comparison": "X — ..., а Y — ...",
        "composition": "В X входят A, B, C...",
        "component_role": "Роль компонента X: ... ; связь с другими блоками: ...",
        "process_explanation": "Сначала ..., затем ..., после этого ...",
        "interaction_explanation": "Элементы X,Y,Z взаимодействуют так: ...",
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


def rewrite_student_query_for_retrieval(
    *,
    normalized_query: str,
    entities: list[str],
    relations: list[str],
    question_intent: str,
    keywords: list[str],
    component_labels: list[str],
) -> list[str]:
    cleaned_tokens = [
        tok
        for tok in normalize_text(normalized_query).split()
        if len(tok) >= 2 and tok not in _STUDENT_NOISE_TOKENS
    ]
    entity_terms = [_ENTITY_CANONICAL_QUERY_TERM.get(ent, ent.replace("_", " ")) for ent in entities]
    key_terms = [t for t in cleaned_tokens if t not in _STUDENT_NOISE_TOKENS][:10]
    if not entity_terms and keywords:
        entity_terms = [normalize_text(keywords[0])]

    templates: list[str] = []
    if question_intent in {"process_explanation", "diagram_explanation"}:
        templates = [
            "{entity} как работает",
            "{entity} механизм работы по шагам",
            "{entity} схема работы",
            "{entity} взаимодействие блоков",
        ]
    elif question_intent == "interaction_explanation":
        templates = [
            "{entity} взаимодействие блоков",
            "{entity} связи между компонентами",
            "как работает {entity}",
            "{entity} схема взаимодействия",
        ]
    elif question_intent == "composition":
        templates = ["{entity} состав блоков", "{entity} основные компоненты", "из чего состоит {entity}"]
    elif question_intent == "component_role":
        templates = [
            "{entity} роль компонента",
            "{entity} функция блока",
            "{entity} за что отвечает",
            "{entity} связь компонента с другими блоками",
        ]
    elif question_intent == "fact_lookup":
        templates = ["{entity} ключевые факты", "{entity} основные элементы", "перечень по теме {entity}"]
    elif question_intent == "definition":
        templates = ["{entity} определение", "что такое {entity}"]

    out: list[str] = []
    if entity_terms:
        for term in entity_terms[:2]:
            for template in templates[:4]:
                out.append(template.format(entity=term))
            for ent, hints in _ENTITY_COMPONENT_HINTS.items():
                if _ENTITY_CANONICAL_QUERY_TERM.get(ent, ent.replace("_", " ")) == term:
                    out.append(f"{term} {' '.join(hints[:5])}")
            if key_terms:
                out.append(f"{term} {' '.join(key_terms[:4])}")
    for label in component_labels[:3]:
        out.append(f"{label} роль компонента")
        out.append(f"{label} функция блока")
        for ent, aliases in ENTITY_ALIASES.items():
            if any(normalize_text(alias) == label for alias in aliases):
                canonical = _ENTITY_CANONICAL_QUERY_TERM.get(ent, ent.replace("_", " "))
                out.append(f"{canonical} {label}")
    if question_intent in {"process_explanation", "interaction_explanation", "diagram_explanation", "component_role"} and entity_terms:
        primary = entity_terms[0]
        out.extend(
            [
                f"{primary} взаимодействие памяти устройства управления и алу",
                f"{primary} схема блоков и поток данных",
            ]
        )
    if not out:
        out.append(" ".join(key_terms[:6]))
    if relations:
        for rel in relations[:2]:
            for rel_exp in RELATION_EXPANSIONS.get(rel, [])[:2]:
                base = entity_terms[0] if entity_terms else " ".join(key_terms[:3])
                out.append(f"{base} {normalize_text(rel_exp)}")

    dedup: list[str] = []
    seen: set[str] = set()
    for form in out:
        cleaned = re.sub(r"\s+", " ", normalize_text(form)).strip()
        if not cleaned or len(cleaned) < 4 or cleaned in seen:
            continue
        seen.add(cleaned)
        dedup.append(cleaned)
        if len(dedup) >= 5:
            break
    return dedup


def build_visual_query(
    *,
    entities: list[str],
    relations: list[str],
    keywords: list[str],
    component_labels: list[str],
    question_intent: str,
    normalized_query: str,
    max_terms: int = 14,
) -> str:
    terms: list[str] = []
    for ent in entities:
        terms.append(_ENTITY_CANONICAL_QUERY_TERM.get(ent, ent.replace("_", " ")))
        terms.extend(_ENTITY_COMPONENT_HINTS.get(ent, [])[:4])
    for rel in relations:
        rel_terms = RELATION_EXPANSIONS.get(rel, [rel])
        terms.extend(normalize_text(t) for t in rel_terms[:1])
    terms.extend(normalize_text(k) for k in keywords[:5])
    terms.extend(normalize_text(lbl) for lbl in component_labels[:4])
    if question_intent in {"diagram_elements", "diagram_explanation"} or any(
        t in normalized_query for t in ("схема", "рисунок", "диаграм", "блок")
    ):
        terms.extend(["схема", "блоки"])
    elif question_intent in {"process_explanation", "interaction_explanation", "component_role"}:
        terms.extend(["взаимодействие", "блоки"])

    compact = _compact_tokens(" ".join(terms), max_terms=max_terms)
    return " ".join(compact).strip() or "diagram architecture blocks"


def _looks_like_student_explanatory_question(normalized_query: str) -> bool:
    return any(marker in normalized_query for marker in _STUDENT_EXPLANATORY_MARKERS)


def _compact_tokens(text: str, *, max_terms: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in text.split():
        tok = normalize_text(token)
        if len(tok) < 2 or tok in _STUDENT_NOISE_TOKENS or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= max_terms:
            break
    return out


def extract_component_labels(query: str) -> list[str]:
    text = query or ""
    labels: list[str] = []
    # Short uppercase-ish block labels (e.g., УУ, АЛУ, CPU, RAM)
    for match in re.findall(r"\b[А-ЯA-Z]{2,6}\b", text):
        labels.append(normalize_text(match))
    norm = normalize_text(text)
    for marker in ("уу", "алу", "cpu", "ram", "rom", "io", "i/o"):
        if marker in norm:
            labels.append(normalize_text(marker))
    seen: set[str] = set()
    dedup: list[str] = []
    for label in labels:
        if not label or label in seen:
            continue
        seen.add(label)
        dedup.append(label)
    return dedup[:6]
