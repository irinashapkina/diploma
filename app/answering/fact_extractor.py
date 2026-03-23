from __future__ import annotations

import re
from dataclasses import dataclass

from app.retrieval.query_processing import ENTITY_ALIASES, ProcessedQuery, RELATION_ALIASES
from app.schemas.models import RetrievalCandidate
from app.utils.text import normalize_text

_SPLIT_RE = re.compile(r"[;\n\.!?]+")
_NOISE_RE = re.compile(r"^[\d\W_]+$")
_PAGE_RE = re.compile(r"^\s*(page|стр|слайд)\s*\d+\s*$", re.IGNORECASE)


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
    } or len(processed_query.entities) >= 2
    facts: list[StructuredFact] = []
    rejected: list[str] = []

    for cand in candidates[:8]:
        fragments = _split_fragments(cand.text or "")
        for fragment in fragments:
            if _is_bad_fragment(fragment):
                rejected.append(fragment[:120])
                continue
            if not _fragment_relevant(fragment, processed_query):
                continue
            fact = _build_fact(fragment, cand, processed_query, selected_sense)
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


def _is_bad_fragment(fragment: str) -> bool:
    low = fragment.lower().strip()
    if len(low) < 20:
        return True
    if _NOISE_RE.match(low):
        return True
    if _PAGE_RE.match(low):
        return True
    digits_ratio = sum(ch.isdigit() for ch in low) / max(1, len(low))
    if digits_ratio > 0.35:
        return True
    letters = sum(ch.isalpha() for ch in low)
    if letters < 10:
        return True
    return False


def _fragment_relevant(fragment: str, pq: ProcessedQuery) -> bool:
    txt = normalize_text(fragment)
    ent_hit = any(any(alias in txt for alias in ENTITY_ALIASES.get(ent, [ent])) for ent in pq.entities)
    rel_hit = any(any(alias in txt for alias in RELATION_ALIASES.get(rel, [rel])) for rel in pq.normalized_relations)
    if pq.question_intent in {"definition", "attribute_lookup"}:
        return ent_hit or rel_hit
    if pq.question_intent in {"comparison", "composition"}:
        return ent_hit or rel_hit or ("," in fragment and len(fragment.split()) >= 4)
    if pq.question_intent in {"diagram_elements", "diagram_explanation"}:
        return ent_hit or rel_hit or any(k in txt for k in ["блок", "архитектур", "unit", "memory", "control"])
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
    if intent == "comparison":
        return "difference"
    if intent == "composition":
        return "components"
    if intent == "diagram_elements":
        return "elements"
    if intent == "diagram_explanation":
        return "roles"
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
        return facts
    by_entity: dict[str, StructuredFact] = {}
    for fact in facts:
        if fact.entity not in by_entity:
            by_entity[fact.entity] = fact
    selected = list(by_entity.values())
    if len(selected) >= 2:
        return selected[:4]
    return facts
