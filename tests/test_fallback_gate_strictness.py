from __future__ import annotations

from app.answering.fact_extractor import FactExtractionResult
from app.pipeline.rag_pipeline import RAGPipeline
from app.schemas.models import RetrievalCandidate
from app.validation.grounding import SupportAssessment


def _cand(
    cid: str,
    text: str,
    *,
    score: float = 0.4,
    page: int = 1,
    title: str = "Slides",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id=cid,
        source_type="text",  # type: ignore[arg-type]
        score=score,
        document_id="doc1",
        document_title=title,
        page_id=f"doc1_p{page}",
        page_number=page,
        text=text,
        image_path=f"/tmp/p{page}.png",
        debug={"text_source": "pdf", "pdf_text_quality": 0.9, "ocr_text_quality": 0.2},
    )


def test_definition_oop_returns_refusal_without_evidence(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [_cand("c1", "Java byte это 8 бит.", score=0.58, page=4)]
    monkeypatch.setattr(pipeline.retriever, "retrieve", lambda **kwargs: (candidates, {"final_candidates": []}))
    monkeypatch.setattr(
        pipeline.answerer,
        "generate",
        lambda *args, **kwargs: "OOP — это объектно-ориентированное программирование.",  # must be blocked by gate
    )
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-oop")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("что такое ооп", course_id="course1", debug=True)
    assert resp.answer == "Подходящий источник в материалах курса не найден. Лучше уточнить вопрос у преподавателя."
    assert resp.sources == []
    assert resp.debug["answer_mode"] == "refusal"


def test_definition_ram_allowed_with_explicit_source(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [_cand("c1", "Random Access Memory — оперативная память.", score=0.51, page=5)]
    monkeypatch.setattr(pipeline.retriever, "retrieve", lambda **kwargs: (candidates, {"final_candidates": []}))
    monkeypatch.setattr(pipeline.answerer, "generate", lambda *args, **kwargs: "")
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-ram")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("что такое ram", course_id="course1", debug=True)
    assert "оператив" in resp.answer.lower()
    assert any(src.page == 5 for src in resp.sources)
    assert "подходящий источник" not in resp.answer.lower()


def test_page12_answer_allowed_with_empty_structured_facts_if_supporting_evidence_exists(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [_cand("c12", "Программисты выбирают степени двойки из-за двоичной адресации и выравнивания памяти.", score=0.49, page=12)]
    monkeypatch.setattr(pipeline.retriever, "retrieve", lambda **kwargs: (candidates, {"final_candidates": []}))
    monkeypatch.setattr(
        "app.pipeline.rag_pipeline.extract_structured_facts",
        lambda **kwargs: FactExtractionResult(
            facts=[],
            rejected_fragments=[],
            contributing_sources=[],
            likely_multi_source=False,
            multi_source_fulfilled=True,
        ),
    )
    monkeypatch.setattr(
        pipeline.validator,
        "assess_support",
        lambda question, context_items, processed_query=None: SupportAssessment(
            has_support=True,
            answer_allowed=True,
            coverage=0.41,
            overlap_terms=["программисты", "степени", "двойки"],
            question_intent="explanation",
            entities=[],
            normalized_relations=[],
            entity_coverage=1.0,
            relation_coverage=1.0,
            source_quality=0.8,
            supporting_facts=["степени двойки удобны для двоичной адресации и выравнивания памяти"],
            reason="literal_ok",
            has_semantic_alignment=True,
            aligned_sources=["Slides:p12"],
            definition_supported=False,
        ),
    )
    monkeypatch.setattr(
        pipeline.answerer,
        "generate",
        lambda *args, **kwargs: "Программисты часто предпочитают степени двойки из-за двоичной адресации и выравнивания памяти.",
    )
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-p12")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("почему программисты любят числа равные степеням двойки", course_id="course1", debug=True)
    assert "подходящий источник" not in resp.answer.lower()
    assert any(src.page == 12 for src in resp.sources)


def test_von_neumann_sources_must_include_page7_not_only_page13(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [
        _cand("c13", "Исторический контекст развития вычислительной техники.", score=0.58, page=13),
        _cand("c7", "Принципы фон Неймана: двоичное кодирование, адресность памяти, программное управление.", score=0.46, page=7),
    ]
    monkeypatch.setattr(pipeline.retriever, "retrieve", lambda **kwargs: (candidates, {"final_candidates": []}))
    monkeypatch.setattr(
        "app.pipeline.rag_pipeline.extract_structured_facts",
        lambda **kwargs: FactExtractionResult(
            facts=[],
            rejected_fragments=[],
            contributing_sources=[],
            likely_multi_source=True,
            multi_source_fulfilled=False,
        ),
    )
    monkeypatch.setattr(
        pipeline.validator,
        "assess_support",
        lambda question, context_items, processed_query=None: SupportAssessment(
            has_support=True,
            answer_allowed=True,
            coverage=0.36,
            overlap_terms=["фон", "неймана", "принципы"],
            question_intent="composition",
            entities=["von_neumann"],
            normalized_relations=["composition"],
            entity_coverage=1.0,
            relation_coverage=0.7,
            source_quality=0.81,
            supporting_facts=["принципы фон Неймана: двоичность, адресность, программное управление"],
            reason="composition_supported",
            has_semantic_alignment=True,
            aligned_sources=["Slides:p7"],
            definition_supported=False,
        ),
    )
    monkeypatch.setattr(
        pipeline.answerer,
        "generate",
        lambda *args, **kwargs: "Ключевые принципы архитектуры фон Неймана: двоичное кодирование, адресность памяти и программное управление.",
    )
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-vn")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("назови принципы архитектуры фон Неймана", course_id="course1", debug=True)
    pages = {s.page for s in resp.sources}
    assert 7 in pages
    assert not (pages == {13})
