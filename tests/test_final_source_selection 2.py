from __future__ import annotations

from app.answering.fact_extractor import FactExtractionResult, extract_structured_facts
from app.answering.source_selector import select_final_sources
from app.retrieval.query_processing import normalize_and_expand_query
from app.schemas.models import RetrievalCandidate, SourceItem
from app.validation.confidence import estimate_confidence
from app.validation.grounding import GroundingValidator, SupportAssessment


def _cand(
    cid: str,
    text: str,
    *,
    score: float = 0.35,
    source_type: str = "text",
    page: int = 1,
    title: str = "Doc",
) -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id=cid,
        source_type=source_type,  # type: ignore[arg-type]
        score=score,
        document_id=f"doc-{cid}",
        document_title=title,
        page_id=f"doc-{cid}_p{page}",
        page_number=page,
        text=text,
        image_path=f"/tmp/p{page}.png",
        debug={"has_diagram": source_type == "visual", "text_source": "pdf", "pdf_text_quality": 0.8, "ocr_text_quality": 0.6},
    )


def test_final_sources_keep_only_evidence_for_answer() -> None:
    q = normalize_and_expand_query("чем стек отличается от кучи")
    candidates = [
        _cand("a1", "Стек хранит переменные примитивного типа.", score=0.52, page=1, title="Slides A"),
        _cand("a2", "Куча содержит данные ссылочного типа.", score=0.5, page=2, title="Slides A"),
        _cand("b1", "Java — популярный язык программирования общего назначения.", score=0.49, page=9, title="Slides B"),
    ]
    facts = extract_structured_facts(q, candidates)
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer="Стек хранит примитивные значения, а куча содержит ссылочные данные.",
        candidates=candidates,
        facts_result=facts,
        support=support,
    )
    assert result.reason == "ok"
    assert len(result.sources) == 2
    assert all(source.document_title == "Slides A" for source in result.sources)
    assert all(source.page in {1, 2} for source in result.sources)


def test_final_sources_are_empty_for_refusal_answer() -> None:
    q = normalize_and_expand_query("как устроена схема")
    candidates = [
        _cand("v1", "ALU, Control Unit, Memory", score=0.41, source_type="visual", page=3, title="Architecture"),
    ]
    facts = extract_structured_facts(q, candidates)
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer="Недостаточно данных в материалах для полного ответа.",
        candidates=candidates,
        facts_result=facts,
        support=support,
    )
    assert result.sources == []
    assert result.reason in {"refusal_answer", "insufficient_support"}


def test_confidence_penalizes_missing_final_sources() -> None:
    q = normalize_and_expand_query("что хранится в стеке")
    candidates = [_cand("c1", "Стек хранит переменные примитивного типа.", score=0.42)]
    facts_result = extract_structured_facts(q, candidates)
    validator = GroundingValidator()
    validation = validator.validate("По материалам, стек хранит примитивные значения.", candidates)

    conf_without_sources, _ = estimate_confidence(
        answer="По материалам, стек хранит примитивные значения.",
        candidates=candidates,
        validation=validation,
        mode="text",
        facts_result=facts_result,
        answer_mode="grounded_synthesis",
        final_sources=[],
    )
    conf_with_sources, _ = estimate_confidence(
        answer="По материалам, стек хранит примитивные значения.",
        candidates=candidates,
        validation=validation,
        mode="text",
        facts_result=facts_result,
        answer_mode="grounded_synthesis",
        final_sources=[
            SourceItem(
                document_title="Doc",
                page=1,
                snippet="Стек хранит переменные примитивного типа.",
                score=0.42,
                type="text",
            )
        ],
    )
    assert conf_with_sources > conf_without_sources


def test_support_fallback_sources_when_no_structured_facts() -> None:
    q = normalize_and_expand_query("как работает архитектура")
    candidates = [
        _cand("d1", "На схеме показаны ALU, Control Unit и память.", score=0.44, title="Lecture 3", page=7),
        _cand("d2", "Общие сведения о курсе.", score=0.31, title="Lecture 1", page=1),
    ]
    empty_facts = FactExtractionResult(
        facts=[],
        rejected_fragments=[],
        contributing_sources=[],
        likely_multi_source=False,
        multi_source_fulfilled=True,
    )
    support = SupportAssessment(
        has_support=True,
        answer_allowed=True,
        coverage=0.5,
        overlap_terms=["архитектура"],
        question_intent=q.question_intent,
        entities=q.entities,
        normalized_relations=q.normalized_relations,
        entity_coverage=0.8,
        relation_coverage=0.6,
        source_quality=0.6,
        supporting_facts=["на схеме показаны alu control unit и память"],
        reason="semantic_ok",
    )
    result = select_final_sources(
        processed_query=q,
        answer="По материалам, архитектура включает ALU, Control Unit и память.",
        candidates=candidates,
        facts_result=empty_facts,
        support=support,
    )
    assert result.sources
    assert result.reason in {"support_fallback", "ok"}
    assert result.sources[0].document_title == "Lecture 3"
