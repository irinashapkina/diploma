from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.models import RetrievalCandidate
from app.utils.text import tokenize_mixed

_re_nums = re.compile(r"\b\d{1,4}\b")
_STOPWORDS = {
    "что",
    "такое",
    "как",
    "почему",
    "зачем",
    "когда",
    "где",
    "кто",
    "это",
    "ли",
    "and",
    "the",
    "what",
    "is",
    "are",
    "how",
    "why",
    "when",
    "where",
}


@dataclass
class ValidationResult:
    answer: str
    unsupported_facts: list[str]
    grounded_ratio: float
    partial: bool


@dataclass
class SupportAssessment:
    has_support: bool
    coverage: float
    overlap_terms: list[str]
    reason: str


class GroundingValidator:
    def assess_support(self, question: str, context_items: list[RetrievalCandidate]) -> SupportAssessment:
        q_tokens = [t for t in tokenize_mixed(question) if len(t) >= 3 and t not in _STOPWORDS]
        if not q_tokens or not context_items:
            return SupportAssessment(has_support=False, coverage=0.0, overlap_terms=[], reason="no_tokens_or_context")

        context_text = "\n".join((c.text or "") for c in context_items).lower()
        overlap_terms = sorted({t for t in q_tokens if t in context_text})
        coverage = len(overlap_terms) / max(1, len(set(q_tokens)))
        top_score = max((c.score for c in context_items), default=0.0)

        # Require overlap on content terms from the question, not on stopwords.
        has_support = coverage >= 0.34 and top_score >= 0.12 and len(overlap_terms) >= 1
        reason = "ok" if has_support else "low_coverage_or_low_score"
        return SupportAssessment(
            has_support=has_support,
            coverage=coverage,
            overlap_terms=overlap_terms[:12],
            reason=reason,
        )

    def validate(self, answer: str, context_items: list[RetrievalCandidate]) -> ValidationResult:
        context_text = "\n".join((c.text or "") for c in context_items).lower()
        nums = _re_nums.findall(answer)
        unsupported: list[str] = []
        for n in nums:
            if n not in context_text:
                unsupported.append(n)

        partial = "недостаточно данных" in answer.lower() or "частич" in answer.lower()
        grounded_ratio = max(0.0, 1.0 - (len(unsupported) / max(1, len(nums))))
        return ValidationResult(
            answer=answer,
            unsupported_facts=unsupported,
            grounded_ratio=grounded_ratio,
            partial=partial,
        )

    def enforce(self, answer: str, validation: ValidationResult) -> str:
        if not validation.unsupported_facts:
            return answer
        trimmed = answer
        for token in validation.unsupported_facts:
            trimmed = re.sub(rf"\b{re.escape(token)}\b", "[неподтверждено]", trimmed)
        if "недостаточно данных" not in trimmed.lower():
            trimmed += "\n\nНедостаточно данных в материалах для подтверждения части фактов."
        return trimmed
