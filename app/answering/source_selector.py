from __future__ import annotations

from dataclasses import dataclass

from app.answering.fact_extractor import FactExtractionResult, StructuredFact
from app.retrieval.query_processing import ENTITY_ALIASES, ProcessedQuery, RELATION_ALIASES
from app.schemas.models import RetrievalCandidate, SourceItem
from app.utils.text import normalize_text
from app.validation.grounding import SupportAssessment


@dataclass
class SourceSelectionResult:
    sources: list[SourceItem]
    selected_source_ids: list[str]
    selected_facts: list[dict]
    reason: str


def select_final_sources(
    *,
    processed_query: ProcessedQuery,
    answer: str,
    candidates: list[RetrievalCandidate],
    facts_result: FactExtractionResult,
    support: SupportAssessment,
    max_sources: int = 4,
) -> SourceSelectionResult:
    if not candidates:
        return SourceSelectionResult(sources=[], selected_source_ids=[], selected_facts=[], reason="no_candidates")
    answer_text = (answer or "").strip()
    if not answer_text:
        return SourceSelectionResult(sources=[], selected_source_ids=[], selected_facts=[], reason="empty_answer")
    if _looks_like_refusal(answer_text):
        return SourceSelectionResult(sources=[], selected_source_ids=[], selected_facts=[], reason="refusal_answer")
    if not support.answer_allowed and not facts_result.facts:
        return SourceSelectionResult(sources=[], selected_source_ids=[], selected_facts=[], reason="insufficient_support")

    evidence_facts = _select_evidence_facts(processed_query, answer_text, facts_result.facts, candidates)
    if not evidence_facts:
        return SourceSelectionResult(sources=[], selected_source_ids=[], selected_facts=[], reason="no_evidence_facts")

    source_to_candidate = _best_candidate_by_source(candidates)
    source_to_facts: dict[str, list[StructuredFact]] = {}
    for fact in evidence_facts:
        source_to_facts.setdefault(fact.source_id, []).append(fact)

    if processed_query.question_intent == "comparison":
        covered_entities = {fact.entity for fact in evidence_facts if fact.entity and fact.entity != "unknown"}
        if len(covered_entities) < 2:
            return SourceSelectionResult(
                sources=[],
                selected_source_ids=[],
                selected_facts=[_fact_debug_item(f) for f in evidence_facts],
                reason="comparison_insufficient_entity_coverage",
            )

    ranked_source_ids = sorted(
        source_to_facts.keys(),
        key=lambda sid: _source_rank(
            source_id=sid,
            source_to_facts=source_to_facts,
            source_to_candidate=source_to_candidate,
            question_intent=processed_query.question_intent,
        ),
        reverse=True,
    )
    selected_ids = ranked_source_ids[: max(1, min(max_sources, _intent_source_limit(processed_query.question_intent)))]
    selected_sources: list[SourceItem] = []
    for source_id in selected_ids:
        cand = source_to_candidate.get(source_id)
        if cand is None:
            continue
        best_fact = max(source_to_facts.get(source_id, []), key=lambda f: f.score, default=None)
        snippet = best_fact.source_phrase if best_fact else (cand.text or "")[:220]
        selected_sources.append(
            SourceItem(
                document_title=cand.document_title,
                page=cand.page_number,
                snippet=snippet[:220],
                score=round(float(cand.score), 4),
                type=cand.source_type,
            )
        )

    if not selected_sources:
        return SourceSelectionResult(
            sources=[],
            selected_source_ids=[],
            selected_facts=[_fact_debug_item(f) for f in evidence_facts],
            reason="no_candidates_for_evidence_sources",
        )

    return SourceSelectionResult(
        sources=selected_sources,
        selected_source_ids=selected_ids,
        selected_facts=[_fact_debug_item(f) for f in evidence_facts],
        reason="ok",
    )


def _select_evidence_facts(
    processed_query: ProcessedQuery,
    answer_text: str,
    facts: list[StructuredFact],
    candidates: list[RetrievalCandidate],
) -> list[StructuredFact]:
    answer_norm = normalize_text(answer_text)
    candidate_source_ids = {f"{c.document_title}:p{c.page_number}" for c in candidates}
    selected: list[StructuredFact] = []
    for fact in facts:
        if fact.source_id not in candidate_source_ids:
            continue
        if not _fact_matches_intent(fact, processed_query):
            continue
        phrase_norm = normalize_text(fact.source_phrase)
        overlap_with_answer = _token_overlap_ratio(answer_norm, phrase_norm)
        if overlap_with_answer < 0.08 and not _contains_query_semantics(phrase_norm, processed_query):
            continue
        selected.append(fact)
    return selected


def _fact_matches_intent(fact: StructuredFact, processed_query: ProcessedQuery) -> bool:
    intent = processed_query.question_intent
    phrase = normalize_text(fact.source_phrase)
    entity_ok = _contains_entity(phrase, processed_query)
    relation_ok = _contains_relation(phrase, processed_query)
    if intent == "definition":
        return fact.attribute in {"definition", "fact"} and (entity_ok or relation_ok)
    if intent == "comparison":
        return (fact.attribute == "difference" and entity_ok) or (entity_ok and relation_ok)
    if intent == "composition":
        return fact.attribute == "components" or relation_ok or (entity_ok and "," in fact.source_phrase)
    if intent in {"diagram_elements", "diagram_explanation"}:
        return fact.source_type == "visual" or relation_ok or entity_ok
    if intent in {"attribute_lookup", "relation", "mechanism", "explanation"}:
        return entity_ok and (relation_ok or fact.attribute in {"storage", "attribute", "fact"})
    return entity_ok or relation_ok


def _best_candidate_by_source(candidates: list[RetrievalCandidate]) -> dict[str, RetrievalCandidate]:
    by_source: dict[str, RetrievalCandidate] = {}
    for cand in candidates:
        source_id = f"{cand.document_title}:p{cand.page_number}"
        current = by_source.get(source_id)
        if current is None or cand.score > current.score:
            by_source[source_id] = cand
    return by_source


def _source_rank(
    *,
    source_id: str,
    source_to_facts: dict[str, list[StructuredFact]],
    source_to_candidate: dict[str, RetrievalCandidate],
    question_intent: str,
) -> float:
    cand = source_to_candidate.get(source_id)
    facts = source_to_facts.get(source_id, [])
    if not cand:
        return 0.0
    best_fact_score = max((f.score for f in facts), default=0.0)
    fact_count_bonus = min(0.18, 0.06 * len(facts))
    visual_bonus = 0.07 if question_intent in {"diagram_elements", "diagram_explanation"} and cand.source_type == "visual" else 0.0
    return float(cand.score) + 0.45 * best_fact_score + fact_count_bonus + visual_bonus


def _intent_source_limit(intent: str) -> int:
    if intent in {"comparison", "composition", "diagram_elements", "diagram_explanation"}:
        return 4
    return 3


def _contains_entity(text_norm: str, processed_query: ProcessedQuery) -> bool:
    if not processed_query.entities:
        return False
    for ent in processed_query.entities:
        aliases = ENTITY_ALIASES.get(ent, [ent])
        if any(normalize_text(alias) in text_norm for alias in aliases if alias.strip()):
            return True
    return False


def _contains_relation(text_norm: str, processed_query: ProcessedQuery) -> bool:
    if not processed_query.normalized_relations:
        return False
    for rel in processed_query.normalized_relations:
        aliases = RELATION_ALIASES.get(rel, [rel])
        if any(normalize_text(alias) in text_norm for alias in aliases if alias.strip()):
            return True
    return False


def _contains_query_semantics(text_norm: str, processed_query: ProcessedQuery) -> bool:
    return _contains_entity(text_norm, processed_query) or _contains_relation(text_norm, processed_query)


def _token_overlap_ratio(a_norm: str, b_norm: str) -> float:
    a_tokens = {t for t in a_norm.split() if len(t) > 2}
    b_tokens = {t for t in b_norm.split() if len(t) > 2}
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / max(1, len(b_tokens))


def _looks_like_refusal(answer_text: str) -> bool:
    low = normalize_text(answer_text)
    markers = (
        "недостаточно данных",
        "не найден",
        "не могу ответить",
        "не удалось найти",
    )
    return any(marker in low for marker in markers)


def _fact_debug_item(fact: StructuredFact) -> dict:
    return {
        "source_id": fact.source_id,
        "entity": fact.entity,
        "attribute": fact.attribute,
        "score": round(float(fact.score), 4),
        "source_type": fact.source_type,
        "source_phrase": fact.source_phrase[:220],
    }
