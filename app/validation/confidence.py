from __future__ import annotations

from app.answering.fact_extractor import FactExtractionResult
from app.retrieval.sense_disambiguation import SenseDecision
from app.schemas.models import RetrievalCandidate
from app.validation.grounding import ValidationResult


def estimate_confidence(
    answer: str,
    candidates: list[RetrievalCandidate],
    validation: ValidationResult,
    mode: str,
    facts_result: FactExtractionResult | None = None,
    sense_decision: SenseDecision | None = None,
    answer_mode: str = "grounded_synthesis",
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
    refusal_penalty = 0.32 if "недостаточно данных" in text_answer.lower() else 0.0

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
    synthesis_bonus = 0.05 if answer_mode == "grounded_synthesis" and text_answer else 0.0
    extractive_bonus = 0.03 if answer_mode == "extractive" and text_answer else 0.0
    partial_mode_penalty = 0.08 if answer_mode == "partial_answer" else 0.0

    conf = (
        0.30 * retrieval_quality
        + consistency
        + mode_bonus
        + grounding
        + 0.18 * quality_facts
        + 0.18 * source_faithfulness
        + synthesis_bonus
        + extractive_bonus
        + multi_source_bonus
        - partial_penalty
        - partial_mode_penalty
        - ambiguity_penalty
        - multi_source_penalty
        - empty_penalty
        - refusal_penalty
    )
    score = max(0.0, min(1.0, conf))
    breakdown = {
        "retrieval_quality": round(retrieval_quality, 4),
        "consistency": round(consistency, 4),
        "mode_bonus": round(mode_bonus, 4),
        "grounding": round(grounding, 4),
        "quality_facts": round(quality_facts, 4),
        "source_faithfulness": round(source_faithfulness, 4),
        "multi_source_bonus": round(multi_source_bonus, 4),
        "multi_source_penalty": round(multi_source_penalty, 4),
        "ambiguity_penalty": round(ambiguity_penalty, 4),
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
