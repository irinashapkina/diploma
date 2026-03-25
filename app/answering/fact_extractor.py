from __future__ import annotations

import re
from dataclasses import dataclass

from app.retrieval.query_processing import ENTITY_ALIASES, ProcessedQuery, RELATION_ALIASES
from app.schemas.models import RetrievalCandidate
from app.utils.text import normalize_text

_SPLIT_RE = re.compile(r"[;\n\.!?]+")
_LIST_SPLIT_RE = re.compile(r"[,\|/]|->|→|—")
_NOISE_RE = re.compile(r"^[\d\W_]+$")
_PAGE_RE = re.compile(r"^\s*(page|стр|слайд)\s*\d+\s*$", re.IGNORECASE)
_DIAGRAM_LABEL_HINTS = (
    "read-only",
    "write-only",
    "input",
    "output",
    "tape",
    "unit",
    "alu",
    "control",
    "memory",
    "register",
    "аккумулятор",
    "лента",
    "вход",
    "выход",
    "блок",
)
_RAM_MACHINE_MARKERS = (
    "random access machine",
    "машина с произвольным доступом",
    "alu",
    "control unit",
    "read-only",
    "write-only",
    "лента",
)
_RAM_MEMORY_MARKERS = (
    "random access memory",
    "оперативная память",
    "озу",
    "ячейка памяти",
)


@dataclass
class StructuredFact:
    fact_type: str
    entity: str
    attribute: str
    value: str
    source_phrase: str
    source_id: str
    page_number: int
    source_type: str
    score: float


@dataclass
class FactExtractionResult:
    facts: list[StructuredFact]
    rejected_fragments: list[str]
    contributing_sources: list[str]
    likely_multi_source: bool
    multi_source_fulfilled: bool


def extract_structured_facts(
    processed_query: ProcessedQuery,
    candidates: list[RetrievalCandidate],
    selected_sense: dict[str, str] | None = None,
) -> FactExtractionResult:
    selected_sense = selected_sense or {}
    likely_multi_source = processed_query.question_intent in {
        "comparison",
        "composition",
        "diagram_elements",
        "diagram_explanation",
        "process_explanation",
        "interaction_explanation",
        "component_role",
    } or len(processed_query.entities) >= 2
    facts: list[StructuredFact] = []
    rejected: list[str] = []

    for cand in candidates[:8]:
        fragments = _split_fragments(cand.text or "")
        for fragment in fragments:
            if _is_bad_fragment(fragment, processed_query, cand):
                rejected.append(fragment[:120])
                continue
            if _sense_conflict(fragment, processed_query, selected_sense):
                rejected.append(f"[sense_conflict] {fragment[:100]}")
                continue
            if not _fragment_relevant(fragment, processed_query):
                continue
            for prepared in _expand_fragment_for_intent(fragment, processed_query):
                fact = _build_fact(prepared, cand, processed_query, selected_sense)
                if fact:
                    facts.append(fact)

    facts = _deduplicate_facts(facts)
    facts = _shape_facts_by_intent(facts, processed_query)
    contributing_sources = sorted({f.source_id for f in facts})
    multi_source_fulfilled = len(contributing_sources) >= 2 if likely_multi_source else True
    return FactExtractionResult(
        facts=facts[:10],
        rejected_fragments=rejected[:20],
        contributing_sources=contributing_sources,
        likely_multi_source=likely_multi_source,
        multi_source_fulfilled=multi_source_fulfilled,
    )


def _split_fragments(text: str) -> list[str]:
    out: list[str] = []
    for part in _SPLIT_RE.split(text or ""):
        fragment = re.sub(r"\s+", " ", part).strip()
        if fragment:
            out.append(fragment)
    return out


def _is_bad_fragment(fragment: str, pq: ProcessedQuery, cand: RetrievalCandidate) -> bool:
    low = fragment.lower().strip()
    if _PAGE_RE.match(low):
        return True
    if pq.question_intent in {"diagram_elements", "diagram_explanation"}:
        if _is_diagram_label(fragment, cand):
            return False
        if len(low) < 6:
            return True
    elif len(low) < 20:
        return True
    if _NOISE_RE.match(low):
        return True
    digits_ratio = sum(ch.isdigit() for ch in low) / max(1, len(low))
    if digits_ratio > 0.35 and pq.question_intent not in {"diagram_elements", "diagram_explanation"}:
        return True
    letters = sum(ch.isalpha() for ch in low)
    min_letters = 3 if pq.question_intent in {"diagram_elements", "diagram_explanation", "component_role"} else 10
    if letters < min_letters:
        return True
    return False


def _fragment_relevant(fragment: str, pq: ProcessedQuery) -> bool:
    txt = normalize_text(fragment)
    ent_hit = any(any(alias in txt for alias in ENTITY_ALIASES.get(ent, [ent])) for ent in pq.entities)
    rel_hit = any(any(alias in txt for alias in RELATION_ALIASES.get(rel, [rel])) for rel in pq.normalized_relations)
    if pq.question_intent in {"definition", "attribute_lookup"}:
        return ent_hit or rel_hit
    if pq.question_intent == "fact_lookup":
        return ent_hit or rel_hit or len(fragment.split()) >= 4
    if pq.question_intent in {"comparison", "composition"}:
        return ent_hit or rel_hit or ("," in fragment and len(fragment.split()) >= 4)
    if pq.question_intent in {"process_explanation", "interaction_explanation", "component_role"}:
        flow_markers = ("взаимодейств", "связ", "переда", "сначала", "затем", "после", "через", "flow", "interaction")
        role_markers = ("роль", "функц", "отвеча", "делает", "назначени", "управля")
        return ent_hit or rel_hit or any(m in txt for m in flow_markers) or any(m in txt for m in role_markers)
    if pq.question_intent in {"diagram_elements", "diagram_explanation"}:
        return ent_hit or rel_hit or any(k in txt for k in _DIAGRAM_LABEL_HINTS) or _looks_like_label_row(fragment)
    return ent_hit or rel_hit


def _build_fact(
    fragment: str,
    cand: RetrievalCandidate,
    pq: ProcessedQuery,
    selected_sense: dict[str, str],
) -> StructuredFact | None:
    entity = _resolve_entity(fragment, pq, selected_sense)
    if not entity and pq.entities:
        entity = selected_sense.get(pq.entities[0], pq.entities[0])
    if not entity:
        entity = "unknown"
    attribute = _infer_attribute(pq.question_intent, fragment)
    value = fragment.strip()
    return StructuredFact(
        fact_type=pq.question_intent,
        entity=entity,
        attribute=attribute,
        value=value,
        source_phrase=fragment.strip(),
        source_id=f"{cand.document_title}:p{cand.page_number}",
        page_number=cand.page_number,
        source_type=cand.source_type,
        score=float(cand.score),
    )


def _resolve_entity(fragment: str, pq: ProcessedQuery, selected_sense: dict[str, str]) -> str | None:
    txt = normalize_text(fragment)
    for ent in pq.entities:
        aliases = ENTITY_ALIASES.get(ent, [ent])
        if any(alias in txt for alias in aliases):
            return selected_sense.get(ent, ent)
    return None


def _infer_attribute(intent: str, fragment: str) -> str:
    txt = normalize_text(fragment)
    if intent == "attribute_lookup":
        if any(t in txt for t in ["хран", "store", "contains"]):
            return "storage"
        return "attribute"
    if intent == "fact_lookup":
        return "fact"
    if intent == "comparison":
        return "difference"
    if intent == "composition":
        return "components"
    if intent == "diagram_elements":
        return "elements"
    if intent == "diagram_explanation":
        return "roles"
    if intent in {"process_explanation", "interaction_explanation", "component_role"}:
        if any(t in txt for t in ["взаимодейств", "interaction", "связ", "between"]):
            return "interaction"
        if any(t in txt for t in ["сначала", "затем", "после", "этап", "шаг", "then"]):
            return "flow"
        if any(t in txt for t in ["роль", "функц", "отвеча", "делает", "назначени", "управля"]):
            return "role"
        return "mechanism"
    if intent == "definition":
        return "definition"
    return "fact"


def _deduplicate_facts(facts: list[StructuredFact]) -> list[StructuredFact]:
    dedup: list[StructuredFact] = []
    seen: set[str] = set()
    for fact in sorted(facts, key=lambda f: f.score, reverse=True):
        key = normalize_text(f"{fact.entity}|{fact.attribute}|{fact.source_phrase}")
        if key in seen:
            continue
        seen.add(key)
        dedup.append(fact)
    return dedup


def _shape_facts_by_intent(facts: list[StructuredFact], pq: ProcessedQuery) -> list[StructuredFact]:
    if pq.question_intent != "comparison":
        if pq.question_intent in {"diagram_elements", "diagram_explanation"}:
            return _prioritize_diagram_facts(facts)
        if pq.question_intent in {"process_explanation", "interaction_explanation", "component_role"}:
            return sorted(
                facts,
                key=lambda f: (
                    1 if f.attribute in {"interaction", "flow", "mechanism", "role"} else 0,
                    1 if any(tok in normalize_text(f.source_phrase) for tok in ["взаимодейств", "связ", "затем", "flow", "роль", "функц"]) else 0,
                    f.score,
                ),
                reverse=True,
            )
        return facts
    by_entity: dict[str, StructuredFact] = {}
    for fact in facts:
        if fact.entity not in by_entity:
            by_entity[fact.entity] = fact
    selected = list(by_entity.values())
    if len(selected) >= 2:
        return selected[:4]
    return facts


def _expand_fragment_for_intent(fragment: str, pq: ProcessedQuery) -> list[str]:
    if pq.question_intent not in {"diagram_elements", "diagram_explanation"}:
        return [fragment]
    if not _looks_like_label_row(fragment):
        return [fragment]
    parts = [re.sub(r"\s+", " ", p).strip(" -:\t") for p in _LIST_SPLIT_RE.split(fragment)]
    prepared = [p for p in parts if p and len(p) >= 3 and not _NOISE_RE.match(p)]
    if not prepared:
        return [fragment]
    return prepared


def _looks_like_label_row(fragment: str) -> bool:
    txt = normalize_text(fragment)
    return (
        any(sep in fragment for sep in [",", "|", "->", "→", "/"])
        or any(h in txt for h in _DIAGRAM_LABEL_HINTS)
        or len(fragment.split()) <= 6
    )


def _is_diagram_label(fragment: str, cand: RetrievalCandidate) -> bool:
    txt = normalize_text(fragment)
    if cand.source_type == "visual" and len(txt) >= 5 and any(ch.isalpha() for ch in txt):
        if any(h in txt for h in _DIAGRAM_LABEL_HINTS):
            return True
        if _looks_like_label_row(fragment):
            return True
    return False


def _sense_conflict(fragment: str, pq: ProcessedQuery, selected_sense: dict[str, str]) -> bool:
    txt = normalize_text(fragment)
    if "ram_machine" in pq.entities and any(marker in txt for marker in _RAM_MEMORY_MARKERS):
        return True
    if "ram_memory" in pq.entities and any(marker in txt for marker in _RAM_MACHINE_MARKERS):
        return True
    for ent, sense in selected_sense.items():
        if ent != "ram":
            continue
        if sense == "ram_machine":
            if any(marker in txt for marker in _RAM_MEMORY_MARKERS) and not any(marker in txt for marker in _RAM_MACHINE_MARKERS):
                return True
        if sense == "ram_memory":
            if any(marker in txt for marker in _RAM_MACHINE_MARKERS) and not any(marker in txt for marker in _RAM_MEMORY_MARKERS):
                return True
    return False


def _prioritize_diagram_facts(facts: list[StructuredFact]) -> list[StructuredFact]:
    scored = sorted(
        facts,
        key=lambda f: (
            1 if any(h in normalize_text(f.source_phrase) for h in _DIAGRAM_LABEL_HINTS) else 0,
            1 if len(f.source_phrase.split()) <= 6 else 0,
            f.score,
        ),
        reverse=True,
    )
    return scored
