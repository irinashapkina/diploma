from __future__ import annotations

from app.schemas.models import RetrievalCandidate
from app.validation.grounding import ValidationResult


def estimate_confidence(
    candidates: list[RetrievalCandidate],
    validation: ValidationResult,
    mode: str,
) -> float:
    if not candidates:
        return 0.0
    top_scores = [c.score for c in candidates[:4]]
    retrieval_quality = sum(top_scores) / max(1, len(top_scores))
    score_spread = top_scores[0] - (top_scores[1] if len(top_scores) > 1 else 0.0)
    consistency = 0.15 if score_spread > 0.15 else 0.05
    mode_bonus = 0.08 if mode in {"visual", "hybrid"} and any(c.source_type == "visual" for c in candidates[:3]) else 0.0
    grounding = 0.35 * validation.grounded_ratio
    partial_penalty = 0.12 if validation.partial else 0.0

    conf = 0.35 * retrieval_quality + consistency + mode_bonus + grounding - partial_penalty
    return max(0.0, min(1.0, conf))

