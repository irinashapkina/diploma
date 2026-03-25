from __future__ import annotations

from app.answering.fact_extractor import extract_structured_facts
from app.answering.source_selector import select_final_sources
from app.retrieval.query_processing import normalize_and_expand_query
from app.schemas.models import RetrievalCandidate, SourceItem
from app.validation.confidence import estimate_confidence
from app.validation.grounding import GroundingValidator


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


def test_list_question_prefers_direct_list_source_over_thematic_source() -> None:
    q = normalize_and_expand_query("назови принципы архитектуры фон Неймана")
    candidates = [
        _cand("c13", "История развития архитектуры фон Неймана и обзор подходов.", score=0.62, page=13, title="Architecture"),
        _cand(
            "c7",
            "Принципы архитектуры фон Неймана: двоичное кодирование, адресность памяти, программное управление.",
            score=0.52,
            page=7,
            title="Architecture",
        ),
    ]
    facts_result = extract_structured_facts(q, [candidates[0]])  # structured facts only from thematic page
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer="Принципы: двоичное кодирование, адресность памяти, программное управление.",
        candidates=candidates,
        facts_result=facts_result,
        support=support,
        strongest_evidence=[candidates[1].text],
    )
    pages = [s.page for s in result.sources]
    assert 7 in pages


def test_definition_sources_must_follow_definition_evidence_not_thematic_pages() -> None:
    q = normalize_and_expand_query("что такое ram")
    candidates = [
        _cand("c24", "Тема памяти и иерархия памяти в архитектуре компьютера.", score=0.63, page=24, title="Slides"),
        _cand("c13", "В архитектуре используется память для хранения данных.", score=0.61, page=13, title="Slides"),
        _cand(
            "c5",
            "RAM / Random Access Memory — оперативная память (память с произвольным доступом).",
            score=0.52,
            page=5,
            title="Slides",
        ),
    ]
    facts_result = extract_structured_facts(q, [])  # emulate weak fact extraction path
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer="RAM — это оперативная память (память с произвольным доступом).",
        candidates=candidates,
        facts_result=facts_result,
        support=support,
        strongest_evidence=[candidates[2].text],
    )
    pages = {s.page for s in result.sources}
    assert 5 in pages
    assert 13 not in pages
    assert 24 not in pages


def test_definition_source_verification_works_when_definition_split_across_chunks() -> None:
    q = normalize_and_expand_query("что такое ram")
    candidates = [
        _cand("c24", "Иерархия памяти в вычислительной системе.", score=0.64, page=24, title="Slides"),
        _cand("c13", "Память хранит данные и инструкции.", score=0.62, page=13, title="Slides"),
        _cand("c5a", "RAM / Random Access Memory", score=0.53, page=5, title="Slides"),
        _cand("c5b", "— оперативная память (память с произвольным доступом).", score=0.5, page=5, title="Slides"),
    ]
    facts_result = extract_structured_facts(q, [])  # emulate extraction miss
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer="RAM — это оперативная память (память с произвольным доступом).",
        candidates=candidates,
        facts_result=facts_result,
        support=support,
        strongest_evidence=["RAM / Random Access Memory — оперативная память (память с произвольным доступом)."],
    )
    pages = {s.page for s in result.sources}
    assert 5 in pages
    assert 13 not in pages
    assert 24 not in pages


def test_explanatory_sources_keep_only_pages_that_confirm_interaction_claims() -> None:
    q = normalize_and_expand_query("как взаимодействуют блоки архитектуры фон Неймана")
    candidates = [
        _cand("c3", "История развития архитектуры фон Неймана.", score=0.63, page=3, title="Slides"),
        _cand("c7", "Память хранит команды и данные; устройство управления считывает команду и направляет выполнение в АЛУ.", score=0.56, page=7, title="Slides"),
        _cand("c8", "После операции АЛУ результат возвращается в память; ввод и вывод подают и получают данные.", score=0.54, page=8, title="Slides"),
    ]
    facts_result = extract_structured_facts(q, candidates)
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer=(
            "Основные блоки: память, устройство управления, АЛУ и ввод-вывод. "
            "УУ считывает команду из памяти, передает выполнение в АЛУ, после чего результат возвращается в память."
        ),
        candidates=candidates,
        facts_result=facts_result,
        support=support,
        strongest_evidence=[candidates[1].text, candidates[2].text],
    )
    pages = {s.page for s in result.sources}
    assert 7 in pages
    assert 8 in pages
    assert 3 not in pages


def test_explanatory_sources_can_fallback_to_aligned_support_when_claim_check_too_strict() -> None:
    q = normalize_and_expand_query("что делает алу на схеме архитектуры фон Неймана")
    candidates = [
        _cand("v7", "Память, УУ, АЛУ, Ввод, Вывод", score=0.58, source_type="visual", page=7, title="Slides"),
        _cand("t7", "АЛУ выполняет арифметические и логические операции.", score=0.5, page=7, title="Slides"),
    ]
    facts_result = extract_structured_facts(q, candidates)
    support = GroundingValidator().assess_support(q.original, candidates, processed_query=q)
    result = select_final_sources(
        processed_query=q,
        answer="АЛУ выполняет арифметические и логические операции и работает в связке с другими блоками схемы.",
        candidates=candidates,
        facts_result=facts_result,
        support=support,
        strongest_evidence=[candidates[1].text],
    )
    assert result.sources
    assert result.reason in {"ok", "aligned_support_fallback"}
