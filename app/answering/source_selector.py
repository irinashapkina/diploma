from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import re

from app.answering.fact_extractor import FactExtractionResult, StructuredFact
from app.retrieval.query_processing import ENTITY_ALIASES, ENTITY_EXPANSIONS, ProcessedQuery, RELATION_ALIASES
from app.schemas.models import RetrievalCandidate, SourceItem
from app.utils.text import normalize_text
from app.validation.grounding import SupportAssessment

_ANSWER_SENTENCE_SPLIT_RE = re.compile(r"[.!?;\n]+")


@dataclass
class SourceSelectionResult:
    sources: list[SourceItem]
    selected_source_ids: list[str]
    verified_source_ids: list[str]
    selected_facts: list[dict]
    reason: str
    verification_details: list[dict] = field(default_factory=list)


def select_final_sources(
    *,
    processed_query: ProcessedQuery,
    answer: str,
    candidates: list[RetrievalCandidate],
    facts_result: FactExtractionResult,
    support: SupportAssessment,
    strongest_evidence: list[str] | None = None,
    max_sources: int = 4,
) -> SourceSelectionResult:
    if not candidates:
        return SourceSelectionResult(sources=[], selected_source_ids=[], verified_source_ids=[], selected_facts=[], reason="no_candidates")
    answer_text = (answer or "").strip()
    if not answer_text:
        return SourceSelectionResult(sources=[], selected_source_ids=[], verified_source_ids=[], selected_facts=[], reason="empty_answer")
    if _looks_like_refusal(answer_text):
        return SourceSelectionResult(sources=[], selected_source_ids=[], verified_source_ids=[], selected_facts=[], reason="refusal_answer")
    if not support.answer_allowed and not facts_result.facts:
        return SourceSelectionResult(sources=[], selected_source_ids=[], verified_source_ids=[], selected_facts=[], reason="insufficient_support")

    evidence_facts = _select_evidence_facts(processed_query, answer_text, facts_result.facts, candidates)

    source_to_facts: dict[str, list[StructuredFact]] = {}
    for fact in evidence_facts:
        source_to_facts.setdefault(fact.source_id, []).append(fact)

    if processed_query.question_intent == "comparison":
        covered_entities = {fact.entity for fact in evidence_facts if fact.entity and fact.entity != "unknown"}
        if len(covered_entities) < 2:
            return SourceSelectionResult(
                sources=[],
                selected_source_ids=[],
                verified_source_ids=[],
                selected_facts=[_fact_debug_item(f) for f in evidence_facts],
                reason="comparison_insufficient_entity_coverage",
            )

    source_to_candidate = _best_candidate_by_source(candidates)
    source_to_candidates = _group_candidates_by_source(candidates)
    strongest_norm = [normalize_text(s) for s in (strongest_evidence or []) if s.strip()]
    supporting_norm = [normalize_text(s) for s in (support.supporting_facts or []) if s.strip()]
    answer_claims_norm = _extract_answer_claims(normalize_text(answer_text), processed_query)
    source_ids: set[str] = set()
    verification_details: list[dict] = []
    answer_norm = normalize_text(answer_text)
    for source_id, cand in source_to_candidate.items():
        source_text_norm = _source_text_norm(source_to_candidates.get(source_id, [cand]))
        if not source_text_norm:
            continue
        verified, verify_reason, verify_metrics = _source_confirms_answer(
            source_id=source_id,
            candidate=cand,
            source_text_norm=source_text_norm,
            processed_query=processed_query,
            support=support,
            answer_norm=answer_norm,
            strongest_evidence_norm=strongest_norm,
            supporting_facts_norm=supporting_norm,
            answer_claims_norm=answer_claims_norm,
        )
        verification_details.append(
            {
                "source_id": source_id,
                "verified": verified,
                "reason": verify_reason,
                **verify_metrics,
            }
        )
        if verified:
            source_ids.add(source_id)

    if not source_ids:
        return SourceSelectionResult(
            sources=[],
            selected_source_ids=[],
            verified_source_ids=[],
            selected_facts=[_fact_debug_item(f) for f in evidence_facts],
            reason="no_verified_sources",
            verification_details=verification_details[:24],
        )

    ranked_source_ids = sorted(
        source_ids,
        key=lambda sid: _source_rank(
            source_id=sid,
            source_to_facts=source_to_facts,
            source_to_candidate=source_to_candidate,
            source_to_candidates=source_to_candidates,
            question_intent=processed_query.question_intent,
            processed_query=processed_query,
            support=support,
            answer_text=answer_text,
            strongest_evidence_norm=strongest_norm,
            supporting_facts_norm=supporting_norm,
            answer_claims_norm=answer_claims_norm,
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
                material_type=str(cand.debug.get("material_type", "document")),
                source_label=_source_label(cand),
                time_start_sec=_float_or_none(cand.debug.get("time_start_sec")),
                time_end_sec=_float_or_none(cand.debug.get("time_end_sec")),
            )
        )

    if not selected_sources:
        return SourceSelectionResult(
            sources=[],
            selected_source_ids=[],
            verified_source_ids=sorted(source_ids),
            selected_facts=[_fact_debug_item(f) for f in evidence_facts],
            reason="no_candidates_for_evidence_sources",
            verification_details=verification_details[:24],
        )

    return SourceSelectionResult(
        sources=selected_sources,
        selected_source_ids=selected_ids,
        verified_source_ids=sorted(source_ids),
        selected_facts=[_fact_debug_item(f) for f in evidence_facts],
        reason="ok",
        verification_details=verification_details[:24],
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
    if intent in {"process_explanation", "interaction_explanation", "component_role"}:
        return entity_ok and (relation_ok or fact.attribute in {"interaction", "flow", "mechanism", "fact"})
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


def _group_candidates_by_source(candidates: list[RetrievalCandidate]) -> dict[str, list[RetrievalCandidate]]:
    grouped: dict[str, list[RetrievalCandidate]] = {}
    for cand in candidates:
        source_id = f"{cand.document_title}:p{cand.page_number}"
        grouped.setdefault(source_id, []).append(cand)
    return grouped


def _source_text_norm(candidates: list[RetrievalCandidate]) -> str:
    blocks = [normalize_text(c.text or "") for c in candidates if (c.text or "").strip()]
    blocks = [b for b in blocks if b]
    if not blocks:
        return ""
    return " ".join(blocks)


def _source_rank(
    *,
    source_id: str,
    source_to_facts: dict[str, list[StructuredFact]],
    source_to_candidate: dict[str, RetrievalCandidate],
    source_to_candidates: dict[str, list[RetrievalCandidate]],
    question_intent: str,
    processed_query: ProcessedQuery,
    support: SupportAssessment,
    answer_text: str,
    strongest_evidence_norm: list[str],
    supporting_facts_norm: list[str],
    answer_claims_norm: list[str],
) -> float:
    cand = source_to_candidate.get(source_id)
    facts = source_to_facts.get(source_id, [])
    if not cand:
        return 0.0
    source_text_norm = _source_text_norm(source_to_candidates.get(source_id, [cand]))
    if not source_text_norm:
        return 0.0
    best_fact_score = max((f.score for f in facts), default=0.0)
    fact_count_bonus = min(0.18, 0.06 * len(facts))
    visual_bonus = 0.07 if question_intent in {"diagram_elements", "diagram_explanation"} and cand.source_type == "visual" else 0.0
    answer_overlap = _token_overlap_ratio(normalize_text(answer_text), source_text_norm)
    question_overlap, semantic_hit = _candidate_alignment_to_question(source_text_norm, processed_query)
    list_bonus = 0.12 if _is_list_question(processed_query) and _looks_like_list_fragment(cand.text or "", source_text_norm) else 0.0
    aligned_bonus = 0.08 if source_id in set(support.aligned_sources) else 0.0
    strongest_overlap = _best_overlap(source_text_norm, strongest_evidence_norm)
    supporting_overlap = _best_overlap(source_text_norm, supporting_facts_norm)
    claim_overlap = _best_overlap(source_text_norm, answer_claims_norm)
    strongest_bonus = 0.18 * strongest_overlap
    supporting_bonus = 0.22 * supporting_overlap
    claim_bonus = 0.25 * claim_overlap
    semantic_bonus = 0.08 if semantic_hit else 0.0
    definition_bonus = 0.16 if processed_query.question_intent == "definition" and _definition_source_match(source_text_norm, cand.text or "", processed_query) else 0.0
    return (
        float(cand.score)
        + 0.35 * best_fact_score
        + fact_count_bonus
        + 0.35 * question_overlap
        + 0.16 * answer_overlap
        + visual_bonus
        + aligned_bonus
        + strongest_bonus
        + supporting_bonus
        + claim_bonus
        + semantic_bonus
        + definition_bonus
        + list_bonus
    )


def _intent_source_limit(intent: str) -> int:
    if intent in {"comparison", "composition", "diagram_elements", "diagram_explanation", "fact_lookup"}:
        return 4
    return 3


def _contains_entity(text_norm: str, processed_query: ProcessedQuery) -> bool:
    if not processed_query.entities and not processed_query.component_labels:
        return False
    for ent in processed_query.entities:
        aliases = ENTITY_ALIASES.get(ent, [ent]) + ENTITY_EXPANSIONS.get(ent, [])
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


def _fallback_sources_from_candidates(
    *,
    processed_query: ProcessedQuery,
    answer_text: str,
    candidates: list[RetrievalCandidate],
    support: SupportAssessment,
    max_sources: int,
) -> list[SourceItem]:
    answer_norm = normalize_text(answer_text)
    ranked: list[tuple[float, RetrievalCandidate]] = []
    strongest_source_set = set(support.aligned_sources)
    for cand in candidates[:8]:
        text = (cand.text or "").strip()
        if not text:
            continue
        text_norm = normalize_text(text)
        overlap = _token_overlap_ratio(answer_norm, text_norm)
        question_overlap, semantic_hit = _candidate_alignment_to_question(text_norm, processed_query)
        if question_overlap < 0.14 and not semantic_hit:
            continue
        if processed_query.question_intent == "definition" and not _looks_like_definition_fragment(text, text_norm):
            continue
        if not support.has_semantic_alignment and question_overlap < 0.2:
            continue
        source_id = f"{cand.document_title}:p{cand.page_number}"
        list_bonus = 0.12 if _is_list_question(processed_query) and _looks_like_list_fragment(text, text_norm) else 0.0
        aligned_bonus = 0.08 if source_id in strongest_source_set else 0.0
        rank = float(cand.score) + 0.25 * overlap + 0.45 * question_overlap + (0.08 if semantic_hit else 0.0) + list_bonus + aligned_bonus
        ranked.append((rank, cand))
    ranked.sort(key=lambda x: x[0], reverse=True)
    out: list[SourceItem] = []
    seen: set[str] = set()
    limit = max(1, min(max_sources, _intent_source_limit(processed_query.question_intent)))
    for _, cand in ranked:
        sid = f"{cand.document_title}:p{cand.page_number}"
        if sid in seen:
            continue
        seen.add(sid)
        out.append(
            SourceItem(
                document_title=cand.document_title,
                page=cand.page_number,
                snippet=(cand.text or "")[:220],
                score=round(float(cand.score), 4),
                type=cand.source_type,
                material_type=str(cand.debug.get("material_type", "document")),
                source_label=_source_label(cand),
                time_start_sec=_float_or_none(cand.debug.get("time_start_sec")),
                time_end_sec=_float_or_none(cand.debug.get("time_end_sec")),
            )
        )
        if len(out) >= limit:
            break
    return out


def _candidate_alignment_to_question(text_norm: str, processed_query: ProcessedQuery) -> tuple[float, bool]:
    semantic_hit = _contains_query_semantics(text_norm, processed_query)
    query_terms = {
        t
        for t in normalize_text(" ".join(processed_query.keywords + processed_query.entities + processed_query.normalized_relations)).split()
        if len(t) > 2
    }
    text_terms = {t for t in text_norm.split() if len(t) > 2}
    overlap = len(query_terms & text_terms) / max(1, len(query_terms))
    return overlap, semantic_hit


def _looks_like_definition_fragment(raw_text: str, text_norm: str) -> bool:
    return (
        "—" in raw_text
        or "–" in raw_text
        or " - " in raw_text
        or "=" in raw_text
        or " это " in text_norm
        or "означает" in text_norm
        or "называется" in text_norm
        or "расшифров" in text_norm
        or "definition" in text_norm
        or "is an" in text_norm
        or "is a" in text_norm
    )


def _is_list_question(processed_query: ProcessedQuery) -> bool:
    if processed_query.question_intent in {"composition", "diagram_elements", "comparison", "fact_lookup"}:
        return True
    query_text = normalize_text(processed_query.original)
    markers = ("назови", "перечисли", "какие", "принципы", "этапы", "виды", "состав", "из чего состоит")
    return any(marker in query_text for marker in markers)


def _looks_like_list_fragment(raw_text: str, text_norm: str) -> bool:
    separators = (",", ";", "•", " - ", "—", "\n")
    has_sep = any(sep in raw_text for sep in separators)
    list_markers = ("включает", "состоит", "принципы", "этапы", "компоненты", "includes", "consists")
    return has_sep or any(marker in text_norm for marker in list_markers)


def _source_has_direct_alignment(
    *,
    source_id: str,
    candidate: RetrievalCandidate,
    processed_query: ProcessedQuery,
    support: SupportAssessment,
    answer_text: str,
    strongest_evidence_norm: list[str],
) -> bool:
    text = normalize_text(candidate.text or "")
    if not text:
        return False
    question_overlap, semantic_hit = _candidate_alignment_to_question(text, processed_query)
    answer_overlap = _token_overlap_ratio(normalize_text(answer_text), text)
    from_aligned = source_id in set(support.aligned_sources)
    from_strongest = bool(strongest_evidence_norm) and any(_token_overlap_ratio(sn, text) >= 0.2 for sn in strongest_evidence_norm)
    list_hit = _is_list_question(processed_query) and _looks_like_list_fragment(candidate.text or "", text)
    if processed_query.question_intent == "definition" and not _looks_like_definition_fragment(candidate.text or "", text):
        return False
    return semantic_hit or question_overlap >= 0.2 or answer_overlap >= 0.2 or from_aligned or from_strongest or list_hit


def _best_overlap(text_norm: str, evidence_norm: list[str]) -> float:
    if not evidence_norm:
        return 0.0
    return max((_token_overlap_ratio(text_norm, ev) for ev in evidence_norm), default=0.0)


def _extract_answer_claims(answer_norm: str, processed_query: ProcessedQuery, max_claims: int = 4) -> list[str]:
    claims: list[str] = []
    for part in _ANSWER_SENTENCE_SPLIT_RE.split(answer_norm):
        sent = normalize_text(part)
        if len(sent.split()) < 3:
            continue
        semantic_hit = _contains_query_semantics(sent, processed_query)
        if semantic_hit or _token_overlap_ratio(sent, normalize_text(processed_query.original)) >= 0.16:
            claims.append(sent)
    if not claims and answer_norm:
        claims = [answer_norm]
    return claims[:max_claims]


def _definition_source_match(source_text_norm: str, raw_text: str, processed_query: ProcessedQuery) -> bool:
    text_norm = source_text_norm
    if not text_norm:
        return False
    if not _looks_like_definition_fragment(raw_text, text_norm):
        return False
    target_terms = _definition_target_terms(processed_query)
    return any(term in text_norm for term in target_terms)


def _definition_target_terms(processed_query: ProcessedQuery) -> list[str]:
    terms: list[str] = []
    if processed_query.entities:
        for ent in processed_query.entities:
            aliases = ENTITY_ALIASES.get(ent, [ent]) + ENTITY_EXPANSIONS.get(ent, [])
            terms.extend(normalize_text(alias) for alias in aliases if alias.strip())
    else:
        q_norm = normalize_text(processed_query.original)
        tokens = [t for t in q_norm.split() if len(t) >= 2 and t not in {"что", "такое", "означает", "дай", "определение", "расшифруй", "это"}]
        terms.extend(tokens[:4])
    return [t for t in dict.fromkeys(terms) if t]


def _source_confirms_answer(
    *,
    source_id: str,
    candidate: RetrievalCandidate,
    source_text_norm: str,
    processed_query: ProcessedQuery,
    support: SupportAssessment,
    answer_norm: str,
    strongest_evidence_norm: list[str],
    supporting_facts_norm: list[str],
    answer_claims_norm: list[str],
) -> tuple[bool, str, dict]:
    text_norm = source_text_norm
    if not text_norm:
        return False
    answer_overlap = _token_overlap_ratio(answer_norm, text_norm)
    question_overlap, semantic_hit = _candidate_alignment_to_question(text_norm, processed_query)
    strongest_overlap = _best_overlap(text_norm, strongest_evidence_norm)
    supporting_overlap = _best_overlap(text_norm, supporting_facts_norm)
    claim_overlap = _best_overlap(text_norm, answer_claims_norm)
    aligned_hit = source_id in set(support.aligned_sources)
    metrics = {
        "answer_overlap": round(answer_overlap, 4),
        "question_overlap": round(question_overlap, 4),
        "claim_overlap": round(claim_overlap, 4),
        "supporting_overlap": round(supporting_overlap, 4),
        "strongest_overlap": round(strongest_overlap, 4),
        "semantic_hit": bool(semantic_hit),
        "aligned_hit": bool(aligned_hit),
        "source_type": candidate.source_type,
    }

    if processed_query.question_intent == "definition":
        if not _definition_source_match(text_norm, candidate.text or "", processed_query):
            return False, "definition_fragment_missing", metrics
        verdict = (
            answer_overlap >= 0.18
            or claim_overlap >= 0.2
            or supporting_overlap >= 0.2
            or strongest_overlap >= 0.2
            or aligned_hit
        )
        return verdict, ("definition_verified" if verdict else "definition_overlap_low"), metrics

    if processed_query.question_intent in {"process_explanation", "interaction_explanation", "diagram_explanation", "component_role"}:
        has_flow_or_visual = (
            candidate.source_type == "visual"
            or any(
                tok in text_norm
                for tok in ("взаимодейств", "связ", "сначала", "затем", "переда", "направля", "возвращ", "flow", "interaction", "блок")
            )
        )
        metrics["has_flow_or_visual"] = bool(has_flow_or_visual)
        verdict = (
            (claim_overlap >= 0.2 or answer_overlap >= 0.2 or supporting_overlap >= 0.22 or strongest_overlap >= 0.22)
            and has_flow_or_visual
            and (
                semantic_hit
                or question_overlap >= 0.12
                or aligned_hit
                or supporting_overlap >= 0.26
                or strongest_overlap >= 0.26
            )
        )
        return verdict, ("explanatory_verified" if verdict else "explanatory_insufficient_alignment"), metrics

    if not semantic_hit and question_overlap < 0.14:
        return False, "question_alignment_too_low", metrics

    verdict = (
        answer_overlap >= 0.2
        or claim_overlap >= 0.2
        or supporting_overlap >= 0.24
        or strongest_overlap >= 0.24
        or (aligned_hit and (semantic_hit or question_overlap >= 0.16))
        or (_is_list_question(processed_query) and _looks_like_list_fragment(candidate.text or "", text_norm) and question_overlap >= 0.14)
    )
    return verdict, ("general_verified" if verdict else "general_overlap_low"), metrics


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_label(candidate: RetrievalCandidate) -> str | None:
    label = str(candidate.debug.get("time_label") or "").strip()
    if label:
        return label
    if str(candidate.debug.get("material_type", "document")) == "video":
        start = _float_or_none(candidate.debug.get("time_start_sec"))
        end = _float_or_none(candidate.debug.get("time_end_sec"))
        if start is not None and end is not None:
            return f"{int(start)}-{int(end)} sec"
    return None
