from __future__ import annotations

from app.answering.prompts import build_grounded_prompt
from app.answering.qwen_ollama import QwenVLAnswerer
from app.answering.minicpm_helper import MiniCPMVHelper
from app.indexing.bm25.index import BM25Index
from app.indexing.dense.index import DenseTextIndex
from app.indexing.store import ArtifactStore
from app.indexing.visual.index import VisualPageIndex
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_processing import normalize_and_expand_query
from app.routing.router import QueryRouter
from app.schemas.models import AskResponse, RetrievalCandidate, SourceItem
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

    def ask(self, question: str, top_k: int = 6, debug: bool = False) -> AskResponse:
        q = normalize_and_expand_query(question)
        route = self.router.decide(q.normalized, processed_query=q)
        candidates, retrieval_debug = self.retriever.retrieve(
            query=question,
            mode=route.mode,
            top_k=top_k,
            query_forms=q.retrieval_forms,
        )
        support = self.validator.assess_support(question=question, context_items=candidates, processed_query=q)

        if not support.answer_allowed:
            low_support_answer = (
                "Недостаточно данных в материалах преподавателя для уверенного ответа на этот вопрос. "
                "Попробуйте уточнить формулировку или загрузить слайды с этой темой."
            )
            sources = [
                SourceItem(
                    document_title=c.document_title,
                    page=c.page_number,
                    snippet=(c.text or "")[:220],
                    score=round(c.score, 4),
                    type=c.source_type,
                )
                for c in candidates[: max(0, min(top_k, 3))]
            ]
            debug_payload = None
            if debug:
                debug_payload = {
                    "router": {"mode": route.mode, "reasons": route.reasons},
                    "query": q.__dict__,
                    "retrieval": retrieval_debug,
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
                    },
                }
            return AskResponse(
                answer=low_support_answer,
                confidence=0.2,
                mode=route.mode,
                sources=sources,
                debug=debug_payload,
            )

        text_context, image_paths = self._assemble_context(candidates, mode=route.mode)
        if route.mode in {"visual", "hybrid"}:
            hints = self.minicpm_helper.extract_page_hints(image_paths)
            if hints:
                text_context = f"{text_context}\n\n[MiniCPM helper hints]\n" + "\n".join(hints[:6])
        prompt = build_grounded_prompt(mode=route.mode, question=question, text_context=text_context)
        answer = self.answerer.generate(prompt=prompt, image_paths=image_paths if route.mode != "text" else [])
        validation = self.validator.validate(answer=answer, context_items=candidates)
        safe_answer = self.validator.enforce(answer=answer, validation=validation)
        confidence = estimate_confidence(candidates=candidates, validation=validation, mode=route.mode)

        sources = [
            SourceItem(
                document_title=c.document_title,
                page=c.page_number,
                snippet=(c.text or "")[:220],
                score=round(c.score, 4),
                type=c.source_type,
            )
            for c in candidates[: top_k if top_k > 0 else 6]
        ]
        debug_payload = None
        if debug:
            debug_payload = {
                "router": {"mode": route.mode, "reasons": route.reasons},
                "query": q.__dict__,
                "retrieval": retrieval_debug,
                "context": {"text_context_preview": text_context[:2000], "images": image_paths},
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
                },
                "validation": {
                    "unsupported_facts": validation.unsupported_facts,
                    "grounded_ratio": validation.grounded_ratio,
                    "partial": validation.partial,
                },
            }
        return AskResponse(
            answer=safe_answer,
            confidence=round(confidence, 3),
            mode=route.mode,
            sources=sources,
            debug=debug_payload,
        )

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
