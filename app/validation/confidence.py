from __future__ import annotations

from app.answering.fact_extractor import FactExtractionResult
from app.retrieval.sense_disambiguation import SenseDecision
from app.schemas.models import RetrievalCandidate, SourceItem
from app.validation.grounding import ValidationResult


def estimate_confidence(
    answer: str,
    candidates: list[RetrievalCandidate],
    validation: ValidationResult,
    mode: str,
    facts_result: FactExtractionResult | None = None,
    sense_decision: SenseDecision | None = None,
    answer_mode: str = "grounded_synthesis",
    final_sources: list[SourceItem] | None = None,
) -> tuple[float, dict]:
    text_answer = (answer or "").strip()
    if not candidates:
        return 0.0, {"reason": "no_candidates", "score": 0.0}
    top_scores = [c.score for c in candidates[:4]]
    retrieval_quality = sum(top_scores) / max(1, len(top_scores))
    score_spread = top_scores[0] - (top_scores[1] if len(top_scores) > 1 else 0.0)
    consistency = 0.15 if score_spread > 0.15 else 0.05
    mode_bonus = 0.08 if mode in {"visual", "hybrid"} and any(c.source_type == "visual" for c in candidates[:3]) else 0.0
    grounding = 0.35 * validation.grounded_ratio
    partial_penalty = 0.12 if validation.partial else 0.0
    empty_penalty = 0.45 if not text_answer else 0.0
    low_answer = text_answer.lower()
    refusal_penalty = 0.32 if ("недостаточно данных" in low_answer or "подходящий источник" in low_answer) else 0.0

    facts_count = len(facts_result.facts) if facts_result else 0
    rejected_count = len(facts_result.rejected_fragments) if facts_result else 0
    quality_facts = min(1.0, facts_count / 5.0) - min(0.25, rejected_count / 40.0)
    quality_facts = max(0.0, quality_facts)

    multi_source_bonus = 0.0
    multi_source_penalty = 0.0
    if facts_result and facts_result.likely_multi_source:
        if facts_result.multi_source_fulfilled:
            multi_source_bonus = 0.1
        else:
            multi_source_penalty = 0.12

    ambiguity_penalty = 0.0
    if sense_decision and sense_decision.ambiguity:
        ambiguity_penalty = min(0.18, sum(sense_decision.ambiguity.values()) / max(1, len(sense_decision.ambiguity)) * 0.2)

    source_faithfulness = _estimate_source_faithfulness(text_answer, facts_result)
    final_sources = final_sources or []
    final_source_quality = _estimate_final_source_quality(final_sources)
    final_source_bonus = 0.08 * final_source_quality
    no_final_sources_penalty = 0.14 if text_answer and not final_sources else 0.0
    weak_final_sources_penalty = 0.08 if final_sources and final_source_quality < 0.3 else 0.0
    synthesis_bonus = 0.05 if answer_mode in {"grounded_synthesis", "fallback_synthesis"} and text_answer else 0.0
    extractive_bonus = 0.03 if answer_mode == "extractive" and text_answer else 0.0
    partial_mode_penalty = 0.08 if answer_mode == "partial_answer" else 0.0

    conf = (
        0.30 * retrieval_quality
        + consistency
        + mode_bonus
        + grounding
        + 0.18 * quality_facts
        + 0.18 * source_faithfulness
        + final_source_bonus
        + synthesis_bonus
        + extractive_bonus
        + multi_source_bonus
        - partial_penalty
        - partial_mode_penalty
        - ambiguity_penalty
        - multi_source_penalty
        - no_final_sources_penalty
        - weak_final_sources_penalty
        - empty_penalty
        - refusal_penalty
    )
    score = max(0.0, min(1.0, conf))
    if not text_answer:
        score = min(score, 0.15)
    elif "недостаточно данных" in low_answer or "подходящий источник" in low_answer:
        score = min(score, 0.35)
    breakdown = {
        "retrieval_quality": round(retrieval_quality, 4),
        "consistency": round(consistency, 4),
        "mode_bonus": round(mode_bonus, 4),
        "grounding": round(grounding, 4),
        "quality_facts": round(quality_facts, 4),
        "source_faithfulness": round(source_faithfulness, 4),
        "final_source_quality": round(final_source_quality, 4),
        "final_source_bonus": round(final_source_bonus, 4),
        "multi_source_bonus": round(multi_source_bonus, 4),
        "multi_source_penalty": round(multi_source_penalty, 4),
        "ambiguity_penalty": round(ambiguity_penalty, 4),
        "no_final_sources_penalty": round(no_final_sources_penalty, 4),
        "weak_final_sources_penalty": round(weak_final_sources_penalty, 4),
        "empty_penalty": round(empty_penalty, 4),
        "refusal_penalty": round(refusal_penalty, 4),
        "partial_penalty": round(partial_penalty + partial_mode_penalty, 4),
        "answer_mode": answer_mode,
        "score": round(score, 4),
    }
    return score, breakdown


def _estimate_source_faithfulness(answer: str, facts_result: FactExtractionResult | None) -> float:
    if not answer or not facts_result or not facts_result.facts:
        return 0.0
    answer_tokens = set(_tokenize(answer))
    if not answer_tokens:
        return 0.0
    source_tokens: set[str] = set()
    for fact in facts_result.facts[:8]:
        source_tokens.update(_tokenize(fact.source_phrase))
    if not source_tokens:
        return 0.0
    overlap = len(answer_tokens & source_tokens) / max(1, len(answer_tokens))
    return max(0.0, min(1.0, overlap))


def _tokenize(text: str) -> list[str]:
    return [t for t in text.lower().split() if len(t) > 2]


def _estimate_final_source_quality(final_sources: list[SourceItem]) -> float:
    if not final_sources:
        return 0.0
    avg_score = sum(max(0.0, min(1.0, float(s.score))) for s in final_sources) / max(1, len(final_sources))
    coverage = min(1.0, len(final_sources) / 3.0)
    return 0.65 * avg_score + 0.35 * coverage
