from __future__ import annotations

import re

from app.answering.answer_shaper import (
    COURSE_SOURCE_NOT_FOUND_MESSAGE,
    build_answer_polishing_prompt,
    build_controlled_synthesis_prompt,
    build_fallback_answer_from_evidence,
    build_fallback_answer_from_facts,
)
from app.answering.fact_extractor import extract_structured_facts
from app.answering.source_selector import select_final_sources
from app.answering.prompts import build_grounded_prompt
from app.answering.qwen_ollama import QwenVLAnswerer
from app.answering.minicpm_helper import MiniCPMVHelper
from app.indexing.bm25.index import BM25Index
from app.indexing.dense.index import DenseTextIndex
from app.indexing.store import ArtifactStore
from app.indexing.visual.index import VisualPageIndex
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_processing import (
    ENTITY_ALIASES,
    ENTITY_EXPANSIONS,
    RELATION_ALIASES,
    ProcessedQuery,
    normalize_and_expand_query,
)
from app.retrieval.sense_disambiguation import disambiguate_entities
from app.routing.router import QueryRouter
from app.schemas.models import AskResponse, RetrievalCandidate
from app.utils.text import normalize_text
from app.validation.confidence import estimate_confidence
from app.validation.grounding import GroundingValidator


class RAGPipeline:
    def __init__(self) -> None:
        self.store = ArtifactStore()
        self.router = QueryRouter()
        self.retriever = HybridRetriever(
            store=self.store,
            bm25=BM25Index(),
            dense=DenseTextIndex(),
            visual=VisualPageIndex(),
        )
        self.answerer = QwenVLAnswerer()
        self.minicpm_helper = MiniCPMVHelper()
        self.validator = GroundingValidator()

    def ask(self, question: str, course_id: str, top_k: int = 6, debug: bool = False) -> AskResponse:
        if not course_id:
            raise ValueError("course_id is required")
        q = normalize_and_expand_query(question)
        sense_decision = disambiguate_entities(q)
        query_forms = list(q.retrieval_forms)
        for selected in sense_decision.selected_sense.values():
            query_forms.append(selected.replace("_", " "))
        route = self.router.decide(q.normalized, processed_query=q)
        retrieval_query = q.retrieval_queries_academic[0] if q.retrieval_queries_academic else q.normalized
        candidates, retrieval_debug = self.retriever.retrieve(
            query=retrieval_query,
            course_id=course_id,
            mode=route.mode,
            top_k=top_k,
            query_forms=query_forms,
            visual_query=q.visual_query,
        )
        support = self.validator.assess_support(question=question, context_items=candidates, processed_query=q)
        strongest_evidence = self._collect_strongest_evidence(
            candidates=candidates,
            question=question,
            processed_query=q,
        )
        facts_result = extract_structured_facts(
            processed_query=q,
            candidates=candidates,
            selected_sense=sense_decision.selected_sense,
        )
        used_support_fallback_facts = False
        if support.has_support and len(facts_result.facts) < 2 and support.supporting_facts:
            pseudo_candidates = [
                RetrievalCandidate(
                    candidate_id=f"support:{idx}",
                    source_type="text",
                    score=max(0.12, candidates[0].score * 0.55 if candidates else 0.15),
                    document_id=candidates[0].document_id if candidates else "support",
                    document_title=candidates[0].document_title if candidates else "support",
                    page_id=f"support_p{idx}",
                    page_number=candidates[0].page_number if candidates else 0,
                    text=fact,
                    image_path=None,
                    debug={"from_supporting_facts": True, "has_diagram": True if q.question_intent.startswith("diagram") else False},
                )
                for idx, fact in enumerate(support.supporting_facts[:6], start=1)
            ]
            fallback_facts = extract_structured_facts(
                processed_query=q,
                candidates=pseudo_candidates,
                selected_sense=sense_decision.selected_sense,
            )
            if fallback_facts.facts:
                merged = facts_result.facts + fallback_facts.facts
                seen: set[str] = set()
                dedup = []
                for fact in merged:
                    key = f"{fact.entity}|{fact.attribute}|{fact.source_phrase.lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    dedup.append(fact)
                facts_result.facts = dedup[:12]
                facts_result.rejected_fragments.extend(fallback_facts.rejected_fragments[:8])
                facts_result.contributing_sources = sorted(
                    set(facts_result.contributing_sources) | set(fallback_facts.contributing_sources)
                )
                facts_result.multi_source_fulfilled = len(facts_result.contributing_sources) >= 2 if facts_result.likely_multi_source else True
                used_support_fallback_facts = True
        minimum_evidence = self._has_minimum_grounded_evidence(
            support=support,
            facts_result=facts_result,
            strongest_evidence=strongest_evidence,
        )

        if not support.answer_allowed or not minimum_evidence:
            low_support_answer = COURSE_SOURCE_NOT_FOUND_MESSAGE
            conf, conf_breakdown = estimate_confidence(
                answer=low_support_answer,
                candidates=candidates,
                validation=self.validator.validate(answer=low_support_answer, context_items=candidates),
                mode=route.mode,
                facts_result=facts_result,
                sense_decision=sense_decision,
                answer_mode="refusal",
                final_sources=[],
            )
            sources = []
            debug_payload = None
            if debug:
                debug_payload = {
                    "router": {"mode": route.mode, "reasons": route.reasons},
                    "query": q.__dict__,
                    "selected_sense": sense_decision.selected_sense,
                    "sense_ambiguity": sense_decision.ambiguity,
                    "sense_reasons": sense_decision.reasons,
                    "retrieval": retrieval_debug,
                    "retrieved_candidates": retrieval_debug.get("final_candidates", []),
                    "retrieved_query_forms": retrieval_debug.get("query_forms_used", []),
                    "visual_query_used": retrieval_debug.get("visual_query_used"),
                    "expected_answer_shape": q.expected_answer_shape,
                    "structured_facts": [],
                    "rejected_bad_facts": facts_result.rejected_fragments,
                    "contributing_sources": [],
                    "final_source_selection": {"reason": "refusal", "selected_source_ids": [], "selected_facts": [], "final_sources_count": 0},
                    "verified_support_sources": [],
                    "final_user_sources": [],
                    "answer_mode": "refusal",
                    "confidence_breakdown": conf_breakdown,
                    "minimum_grounded_evidence": minimum_evidence,
                    "strongest_evidence": strongest_evidence,
                    "support": {
                        "has_support": support.has_support,
                        "answer_allowed": support.answer_allowed,
                        "coverage": support.coverage,
                        "overlap_terms": support.overlap_terms,
                        "question_intent": support.question_intent,
                        "entities": support.entities,
                        "normalized_relations": support.normalized_relations,
                        "entity_coverage": support.entity_coverage,
                        "relation_coverage": support.relation_coverage,
                        "source_quality": support.source_quality,
                        "supporting_facts": support.supporting_facts,
                        "reason": support.reason,
                        "has_semantic_alignment": support.has_semantic_alignment,
                        "aligned_support_sources": support.aligned_sources,
                        "aligned_sources": support.aligned_sources,
                        "definition_supported": support.definition_supported,
                        "definition_term_present": support.definition_term_present,
                        "definition_gate": support.definition_gate,
                        "explanation_gate": support.explanation_gate,
                    },
                }
            response = AskResponse(
                answer=low_support_answer,
                confidence=round(conf, 3),
                mode=route.mode,
                sources=sources,
                debug=debug_payload,
            )
            message_id = self.store.create_ask_message(
                course_id=course_id,
                question=question,
                answer=response.answer,
                answer_mode="refusal",
                confidence=response.confidence,
                question_intent=q.question_intent,
                entities=q.entities,
                selected_sense=sense_decision.selected_sense,
                expected_answer_shape=q.expected_answer_shape,
                support={
                    "has_support": support.has_support,
                    "answer_allowed": support.answer_allowed,
                    "coverage": support.coverage,
                    "reason": support.reason,
                    "has_semantic_alignment": support.has_semantic_alignment,
                    "aligned_sources": support.aligned_sources,
                    "definition_supported": support.definition_supported,
                    "definition_term_present": support.definition_term_present,
                    "explanation_gate": support.explanation_gate,
                },
                validation={},
                confidence_breakdown=conf_breakdown,
                debug_payload=debug_payload,
            )
            self.store.create_answer_sources(
                message_id=message_id,
                course_id=course_id,
                sources=[s.model_dump() for s in response.sources],
            )
            return response

        text_context, image_paths = self._assemble_context(candidates, mode=route.mode)
        if route.mode in {"visual", "hybrid"}:
            hints = self.minicpm_helper.extract_page_hints(image_paths)
            if hints:
                text_context = f"{text_context}\n\n[MiniCPM helper hints]\n" + "\n".join(hints[:6])
        shaping_plan = build_controlled_synthesis_prompt(
            question=question,
            processed_query=q,
            facts_result=facts_result,
            selected_sense=sense_decision.selected_sense,
            support_has_support=support.has_support and minimum_evidence,
            strongest_evidence=strongest_evidence,
        )
        synthesis_prompt = shaping_plan.prompt
        if shaping_plan.answer_mode == "partial_answer":
            prompt = synthesis_prompt
        else:
            prompt = (
                f"{synthesis_prompt}\n\n"
                f"Дополнительный retrieval context:\n{text_context}\n\n"
                f"Вопрос: {question}\n"
            )
        fallback_prompt = build_grounded_prompt(mode=route.mode, question=question, text_context=text_context)
        prompt = f"{prompt}\n\n[Fallback grounded context]\n{fallback_prompt}"
        answer = self.answerer.generate(
            prompt=prompt,
            image_paths=image_paths if route.mode != "text" else [],
            system_prompt="Строго придерживайся source-фактов. Не добавляй внешние знания.",
        )
        llm_answer_empty = not answer.strip()
        if llm_answer_empty:
            if facts_result.facts:
                answer = build_fallback_answer_from_facts(processed_query=q, facts_result=facts_result)
            elif minimum_evidence and strongest_evidence:
                answer = build_fallback_answer_from_evidence(processed_query=q, strongest_evidence=strongest_evidence)
            else:
                answer = COURSE_SOURCE_NOT_FOUND_MESSAGE
        validation = self.validator.validate(answer=answer, context_items=candidates)
        safe_answer = self.validator.enforce(answer=answer, validation=validation)
        should_polish = (
            support.answer_allowed
            and not self._looks_like_refusal(safe_answer)
            and (self._answer_needs_polishing(safe_answer) or self._evidence_is_noisy_or_short(facts_result, strongest_evidence))
        )
        if should_polish:
            evidence_phrases = [f.source_phrase for f in facts_result.facts[:6]] if facts_result.facts else strongest_evidence
            polishing_prompt = build_answer_polishing_prompt(
                question=question,
                draft_answer=safe_answer,
                processed_query=q,
                evidence_phrases=evidence_phrases,
            )
            polished_answer = self.answerer.generate(
                prompt=polishing_prompt,
                image_paths=[],
                system_prompt="Полируй только подтвержденный смысл. Не добавляй новых фактов.",
            ).strip()
            if polished_answer and not self._is_model_runtime_error(polished_answer):
                polished_validation = self.validator.validate(answer=polished_answer, context_items=candidates)
                polished_safe_answer = self.validator.enforce(answer=polished_answer, validation=polished_validation)
                if polished_validation.grounded_ratio >= validation.grounded_ratio - 0.01:
                    safe_answer = polished_safe_answer
                    validation = polished_validation
        final_source_selection = select_final_sources(
            processed_query=q,
            answer=safe_answer,
            candidates=candidates,
            facts_result=facts_result,
            support=support,
            strongest_evidence=strongest_evidence,
            max_sources=max(2, min(top_k, 4)) if top_k > 0 else 3,
        )
        if safe_answer.strip() and not self._looks_like_refusal(safe_answer) and not final_source_selection.sources:
            safe_answer = (
                f"{safe_answer.strip()}\n\n"
                "Ответ частичный: не удалось надежно верифицировать источники для всех утверждений."
            )
            validation = self.validator.validate(answer=safe_answer, context_items=candidates)
        confidence, conf_breakdown = estimate_confidence(
            answer=safe_answer,
            candidates=candidates,
            validation=validation,
            mode=route.mode,
            facts_result=facts_result,
            sense_decision=sense_decision,
            answer_mode=shaping_plan.answer_mode,
            final_sources=final_source_selection.sources,
        )

        sources = final_source_selection.sources
        debug_payload = None
        if debug:
            debug_payload = {
                "router": {"mode": route.mode, "reasons": route.reasons},
                "query": q.__dict__,
                "selected_sense": sense_decision.selected_sense,
                "sense_ambiguity": sense_decision.ambiguity,
                "sense_reasons": sense_decision.reasons,
                "expected_answer_shape": q.expected_answer_shape,
                "retrieval": retrieval_debug,
                "retrieved_candidates": retrieval_debug.get("final_candidates", []),
                "retrieved_query_forms": retrieval_debug.get("query_forms_used", []),
                "visual_query_used": retrieval_debug.get("visual_query_used"),
                "context": {"text_context_preview": text_context[:2000], "images": image_paths},
                "structured_facts": [f.__dict__ for f in facts_result.facts],
                "rejected_bad_facts": facts_result.rejected_fragments,
                "contributing_sources": facts_result.contributing_sources,
                "final_source_selection": {
                    "reason": final_source_selection.reason,
                    "selected_source_ids": final_source_selection.selected_source_ids,
                    "verified_source_ids": final_source_selection.verified_source_ids,
                    "selected_facts": final_source_selection.selected_facts,
                    "verification_details": final_source_selection.verification_details,
                    "final_sources_count": len(final_source_selection.sources),
                },
                "verified_support_sources": final_source_selection.verified_source_ids,
                "final_user_sources": [s.model_dump() for s in final_source_selection.sources],
                "likely_multi_source": facts_result.likely_multi_source,
                "multi_source_fulfilled": facts_result.multi_source_fulfilled,
                "answer_mode": shaping_plan.answer_mode,
                "used_support_fallback_facts": used_support_fallback_facts,
                "llm_answer_empty": llm_answer_empty,
                "minimum_grounded_evidence": minimum_evidence,
                "strongest_evidence": strongest_evidence,
                "support": {
                    "has_support": support.has_support,
                    "answer_allowed": support.answer_allowed,
                    "coverage": support.coverage,
                    "overlap_terms": support.overlap_terms,
                    "question_intent": support.question_intent,
                    "entities": support.entities,
                    "normalized_relations": support.normalized_relations,
                    "entity_coverage": support.entity_coverage,
                    "relation_coverage": support.relation_coverage,
                    "source_quality": support.source_quality,
                    "supporting_facts": support.supporting_facts,
                    "reason": support.reason,
                    "has_semantic_alignment": support.has_semantic_alignment,
                    "aligned_support_sources": support.aligned_sources,
                    "aligned_sources": support.aligned_sources,
                    "definition_supported": support.definition_supported,
                    "definition_term_present": support.definition_term_present,
                    "definition_gate": support.definition_gate,
                    "explanation_gate": support.explanation_gate,
                },
                "validation": {
                    "unsupported_facts": validation.unsupported_facts,
                    "grounded_ratio": validation.grounded_ratio,
                    "partial": validation.partial,
                },
                "confidence_breakdown": conf_breakdown,
            }
        response = AskResponse(
            answer=safe_answer,
            confidence=round(confidence, 3),
            mode=route.mode,
            sources=sources,
            debug=debug_payload,
        )
        message_id = self.store.create_ask_message(
            course_id=course_id,
            question=question,
            answer=response.answer,
            answer_mode=shaping_plan.answer_mode,
            confidence=response.confidence,
            question_intent=q.question_intent,
            entities=q.entities,
            selected_sense=sense_decision.selected_sense,
            expected_answer_shape=q.expected_answer_shape,
            support={
                "has_support": support.has_support,
                "answer_allowed": support.answer_allowed,
                "coverage": support.coverage,
                "reason": support.reason,
                "has_semantic_alignment": support.has_semantic_alignment,
                "aligned_support_sources": support.aligned_sources,
                "aligned_sources": support.aligned_sources,
                "definition_supported": support.definition_supported,
                "definition_term_present": support.definition_term_present,
                "definition_gate": support.definition_gate,
                "explanation_gate": support.explanation_gate,
            },
            validation={
                "unsupported_facts": validation.unsupported_facts,
                "grounded_ratio": validation.grounded_ratio,
                "partial": validation.partial,
            },
            confidence_breakdown=conf_breakdown,
            debug_payload=debug_payload,
        )
        self.store.create_answer_sources(
            message_id=message_id,
            course_id=course_id,
            sources=[s.model_dump() for s in response.sources],
        )
        return response

    @staticmethod
    def _collect_strongest_evidence(
        candidates: list[RetrievalCandidate],
        question: str,
        processed_query: ProcessedQuery,
    ) -> list[str]:
        q_tokens = {tok for tok in normalize_text(question).split() if len(tok) > 2}
        ranked: list[tuple[float, str]] = []
        for cand in candidates[:6]:
            snippet = " ".join((cand.text or "").split())
            if not snippet:
                continue
            snippet_norm = normalize_text(snippet)
            c_tokens = {tok for tok in snippet_norm.split() if len(tok) > 2}
            overlap_count = len(q_tokens & c_tokens)
            overlap = overlap_count / max(1, len(q_tokens))
            semantic_hit = RAGPipeline._contains_query_semantics(snippet_norm, processed_query)
            definition_ok = (
                processed_query.question_intent != "definition"
                or (overlap_count >= 1 and ("—" in snippet or " это " in snippet_norm or semantic_hit))
            )
            aligned = semantic_hit or overlap >= 0.2 or (overlap >= 0.12 and overlap_count >= 2)
            if not aligned or not definition_ok:
                continue
            quality_bonus = 0.03 if str(cand.debug.get("text_source", "ocr")) != "ocr" else 0.0
            relevance = float(cand.score) + 0.45 * overlap + (0.08 if semantic_hit else 0.0) + quality_bonus
            ranked.append((relevance, snippet[:260]))
        ranked.sort(key=lambda x: x[0], reverse=True)
        out: list[str] = []
        seen: set[str] = set()
        for _, snippet in ranked[:4]:
            key = normalize_text(snippet)
            if key in seen:
                continue
            seen.add(key)
            out.append(snippet)
        return out

    @staticmethod
    def _has_minimum_grounded_evidence(
        *,
        support,
        facts_result,
        strongest_evidence: list[str],
    ) -> bool:  # noqa: ANN001
        has_quality_fact = any(len((f.source_phrase or "").strip()) >= 16 and float(f.score) >= 0.12 for f in facts_result.facts[:6])
        has_supporting_fact = bool(support.supporting_facts)
        has_aligned_source = bool(support.has_semantic_alignment and support.aligned_sources)
        has_entity_support = support.entity_coverage >= 0.5 and (has_supporting_fact or support.relation_coverage >= 0.34)
        has_overlap_signal = support.coverage >= 0.16 and bool(support.overlap_terms) and (has_aligned_source or has_supporting_fact)
        has_fallback_alignment = bool(strongest_evidence) and (support.coverage >= 0.12 or has_aligned_source)
        if support.question_intent == "definition":
            return bool(
                support.definition_term_present
                and (support.definition_supported or has_quality_fact or has_supporting_fact)
            )
        if support.question_intent in {"process_explanation", "interaction_explanation", "diagram_explanation", "component_role"}:
            return bool(
                (support.explanation_gate.get("entity_present") or support.explanation_gate.get("topic_anchored"))
                and support.explanation_gate.get("component_coverage")
                and (
                    support.explanation_gate.get("relation_or_flow_support")
                    or support.explanation_gate.get("visual_evidence")
                )
                and (support.question_intent != "component_role" or support.explanation_gate.get("role_support"))
                and support.explanation_gate.get("multi_evidence_support")
            )
        return has_quality_fact or has_supporting_fact or has_aligned_source or has_entity_support or has_overlap_signal or has_fallback_alignment

    @staticmethod
    def _answer_needs_polishing(answer: str) -> bool:
        txt = (answer or "").strip()
        if not txt:
            return False
        if len(txt) < 40:
            return True
        noise_tokens = len(re.findall(r"(?:[^\w\s]{2,}|[0-9]{4,}|[A-Za-zА-Яа-я]{1})", txt))
        long_word = max((len(w) for w in txt.split()), default=0)
        return noise_tokens >= 3 or long_word >= 26 or txt.count(";") >= 4

    @staticmethod
    def _evidence_is_noisy_or_short(facts_result, strongest_evidence: list[str]) -> bool:  # noqa: ANN001
        if facts_result.facts:
            avg_len = sum(len(f.source_phrase.strip()) for f in facts_result.facts[:6]) / max(1, len(facts_result.facts[:6]))
            rejected_ratio = len(facts_result.rejected_fragments) / max(1, len(facts_result.facts) + len(facts_result.rejected_fragments))
            return avg_len < 56 or rejected_ratio > 0.45
        if strongest_evidence:
            avg_len = sum(len(s.strip()) for s in strongest_evidence[:4]) / max(1, len(strongest_evidence[:4]))
            return avg_len < 64
        return False

    @staticmethod
    def _looks_like_refusal(answer: str) -> bool:
        low = normalize_text(answer)
        return "подходящий источник" in low or "недостаточно данных" in low

    @staticmethod
    def _is_model_runtime_error(answer: str) -> bool:
        low = normalize_text(answer)
        return "не удалось получить ответ от модели" in low

    @staticmethod
    def _contains_query_semantics(text_norm: str, processed_query: ProcessedQuery) -> bool:
        for ent in processed_query.entities:
            aliases = ENTITY_ALIASES.get(ent, [ent]) + ENTITY_EXPANSIONS.get(ent, [])
            if any(normalize_text(alias) in text_norm for alias in aliases if alias.strip()):
                return True
        for rel in processed_query.normalized_relations:
            aliases = RELATION_ALIASES.get(rel, [rel])
            if any(normalize_text(alias) in text_norm for alias in aliases if alias.strip()):
                return True
        return False

    @staticmethod
    def _assemble_context(candidates: list[RetrievalCandidate], mode: str) -> tuple[str, list[str]]:
        if not candidates:
            return "Контекст не найден.", []
        text_blocks: list[str] = []
        images: list[str] = []
        seen_pages: set[str] = set()
        seen_text: set[str] = set()

        for c in candidates:
            if c.source_type == "visual" and c.image_path and c.page_id not in seen_pages:
                images.append(c.image_path)
                seen_pages.add(c.page_id)
            snippet = (c.text or "").strip()
            if snippet and snippet not in seen_text:
                text_blocks.append(
                    f"[{c.document_title} | page {c.page_number} | {c.source_type} | score={c.score:.3f}] {snippet}"
                )
                seen_text.add(snippet)

        if mode == "visual" and not images:
            # fallback: allow top page image from text candidates
            for c in candidates:
                if c.image_path and c.page_id not in seen_pages:
                    images.append(c.image_path)
                    seen_pages.add(c.page_id)
                    if len(images) >= 2:
                        break

        return "\n\n".join(text_blocks[:8]), images[:4]
