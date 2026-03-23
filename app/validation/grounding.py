from __future__ import annotations

import re
from dataclasses import dataclass

from app.retrieval.query_processing import (
    ENTITY_ALIASES,
    RELATION_ALIASES,
    ProcessedQuery,
    normalize_and_expand_query,
)
from app.schemas.models import RetrievalCandidate
from app.utils.text import normalize_for_retrieval, normalize_text, tokenize_mixed

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
    answer_allowed: bool
    coverage: float
    overlap_terms: list[str]
    question_intent: str
    entities: list[str]
    normalized_relations: list[str]
    entity_coverage: float
    relation_coverage: float
    source_quality: float
    supporting_facts: list[str]
    reason: str


class GroundingValidator:
    def assess_support(
        self,
        question: str,
        context_items: list[RetrievalCandidate],
        processed_query: ProcessedQuery | None = None,
    ) -> SupportAssessment:
        pq = processed_query or normalize_and_expand_query(question)
        q_tokens = [t for t in tokenize_mixed(question) if len(t) >= 3 and t not in _STOPWORDS]
        if not q_tokens or not context_items:
            return SupportAssessment(
                has_support=False,
                answer_allowed=False,
                coverage=0.0,
                overlap_terms=[],
                question_intent=pq.question_intent,
                entities=pq.entities,
                normalized_relations=pq.normalized_relations,
                entity_coverage=0.0,
                relation_coverage=0.0,
                source_quality=0.0,
                supporting_facts=[],
                reason="no_tokens_or_context",
            )

        context_text = "\n".join((c.text or "") for c in context_items).lower()
        overlap_terms = sorted({t for t in q_tokens if t in context_text})
        coverage = len(overlap_terms) / max(1, len(set(q_tokens)))
        top_score = max((c.score for c in context_items), default=0.0)

        entity_hits = self._find_entity_hits(context_text, pq.entities)
        entity_coverage = len(entity_hits) / max(1, len(pq.entities)) if pq.entities else 1.0
        relation_hits = self._find_relation_hits(context_text, pq.normalized_relations)
        relation_coverage = (
            len(relation_hits) / max(1, len(pq.normalized_relations)) if pq.normalized_relations else 1.0
        )
        source_quality = self._estimate_source_quality(context_items)
        supporting_facts = self._collect_supporting_facts(context_items, pq.entities, pq.normalized_relations)

        comparison_supported = self._comparison_supported(pq, context_items)
        diagram_supported = self._diagram_supported(pq, context_items)
        composition_supported = self._composition_supported(pq, context_items)
        literal_support = coverage >= 0.26 and top_score >= 0.10 and len(overlap_terms) >= 1
        has_semantic_signals = bool(pq.entities) or bool(pq.normalized_relations)
        semantic_support = has_semantic_signals and entity_coverage >= 0.5 and (
            relation_coverage >= 0.34 or bool(supporting_facts)
        )
        strong_retrieval_support = (
            top_score >= 0.22 and entity_coverage >= 0.5 and len(supporting_facts) >= 1 and source_quality >= 0.28
        )

        has_support = literal_support or semantic_support or comparison_supported or diagram_supported or composition_supported
        answer_allowed = has_support or strong_retrieval_support

        reason = "semantic_ok"
        if comparison_supported:
            reason = "comparison_supported"
        elif diagram_supported:
            reason = "diagram_supported"
        elif composition_supported:
            reason = "composition_supported"
        elif literal_support and not semantic_support:
            reason = "literal_ok"
        elif strong_retrieval_support and not has_support:
            reason = "strong_retrieval_semantic_partial"
        elif not answer_allowed:
            reason = "insufficient_semantic_support"

        return SupportAssessment(
            has_support=has_support,
            answer_allowed=answer_allowed,
            coverage=coverage,
            overlap_terms=overlap_terms[:12],
            question_intent=pq.question_intent,
            entities=pq.entities,
            normalized_relations=pq.normalized_relations,
            entity_coverage=entity_coverage,
            relation_coverage=relation_coverage,
            source_quality=source_quality,
            supporting_facts=supporting_facts[:10],
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

    @staticmethod
    def _find_entity_hits(context_text: str, entities: list[str]) -> list[str]:
        hits: list[str] = []
        for entity in entities:
            aliases = ENTITY_ALIASES.get(entity, [entity])
            if any(_contains_alias(context_text, alias) for alias in aliases):
                hits.append(entity)
        return hits

    @staticmethod
    def _find_relation_hits(context_text: str, relations: list[str]) -> list[str]:
        hits: list[str] = []
        for relation in relations:
            aliases = RELATION_ALIASES.get(relation, [relation])
            if any(_contains_alias(context_text, alias) for alias in aliases):
                hits.append(relation)
        return hits

    @staticmethod
    def _collect_supporting_facts(
        context_items: list[RetrievalCandidate],
        entities: list[str],
        relations: list[str],
    ) -> list[str]:
        facts: list[str] = []
        relation_aliases: list[str] = []
        for rel in relations:
            relation_aliases.extend(RELATION_ALIASES.get(rel, []))
        relation_aliases = list(dict.fromkeys(relation_aliases))
        for cand in context_items[:6]:
            txt = (cand.text or "").strip().lower()
            if not txt:
                continue
            has_entity = False
            for ent in entities:
                aliases = ENTITY_ALIASES.get(ent, [ent])
                if any(_contains_alias(txt, alias) for alias in aliases):
                    has_entity = True
                    break
            has_relation = not relations or any(_contains_alias(txt, alias) for alias in relation_aliases)
            if has_entity and has_relation:
                facts.append(txt[:220])
            elif has_entity and len(txt) > 40:
                facts.append(txt[:220])
        return facts

    @staticmethod
    def _comparison_supported(pq: ProcessedQuery, context_items: list[RetrievalCandidate]) -> bool:
        if pq.question_intent != "comparison" or len(pq.entities) < 2:
            return False
        matched_entities: set[str] = set()
        for cand in context_items[:8]:
            txt = (cand.text or "").lower()
            for ent in pq.entities:
                aliases = ENTITY_ALIASES.get(ent, [ent])
                if any(_contains_alias(txt, alias) for alias in aliases):
                    matched_entities.add(ent)
        return len(matched_entities) >= 2

    @staticmethod
    def _diagram_supported(pq: ProcessedQuery, context_items: list[RetrievalCandidate]) -> bool:
        if pq.question_intent not in {"diagram_elements", "diagram_explanation"}:
            return False
        has_visual = any(c.source_type == "visual" for c in context_items[:5])
        has_diagram_flag = any(bool(c.debug.get("has_diagram", False)) for c in context_items[:5])
        return has_visual or has_diagram_flag

    @staticmethod
    def _composition_supported(pq: ProcessedQuery, context_items: list[RetrievalCandidate]) -> bool:
        if pq.question_intent != "composition":
            return False
        tokens = ("состоит", "входит", "компонент", "contains", "consists")
        return any(any(tok in (c.text or "").lower() for tok in tokens) for c in context_items[:6])

    @staticmethod
    def _estimate_source_quality(context_items: list[RetrievalCandidate]) -> float:
        if not context_items:
            return 0.0
        values: list[float] = []
        for cand in context_items[:6]:
            text_source = str(cand.debug.get("text_source", "ocr"))
            pdf_q = float(cand.debug.get("pdf_text_quality", 0.0))
            ocr_q = float(cand.debug.get("ocr_text_quality", 0.0))
            source_prior = 0.85 if text_source == "pdf" else (0.68 if text_source == "pdf+ocr" else 0.45)
            if cand.source_type == "visual":
                source_prior += 0.08
            score = 0.55 * source_prior + 0.3 * pdf_q + 0.15 * ocr_q
            values.append(max(0.0, min(1.0, score)))
        return sum(values) / max(1, len(values))


def _contains_alias(context_text: str, alias: str) -> bool:
    context_norm = normalize_text(context_text)
    alias_norm = normalize_text(alias)
    if alias_norm and alias_norm in context_norm:
        return True
    context_stem = normalize_for_retrieval(context_norm)
    alias_stem = normalize_for_retrieval(alias_norm)
    if alias_stem and alias_stem in context_stem:
        return True
    alias_tokens = [t for t in alias_stem.split() if t]
    context_tokens = set(context_stem.split())
    return bool(alias_tokens) and all(t in context_tokens for t in alias_tokens)
