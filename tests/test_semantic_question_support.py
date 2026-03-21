from __future__ import annotations

from app.retrieval.query_processing import normalize_and_expand_query
from app.schemas.models import RetrievalCandidate
from app.validation.grounding import GroundingValidator


def _cand(
    cid: str,
    text: str,
    *,
    score: float = 0.35,
    source_type: str = "text",
    has_diagram: bool = False,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id=cid,
        source_type=source_type,  # type: ignore[arg-type]
        score=score,
        document_id="doc1",
        document_title="Doc",
        page_id="doc1_p1",
        page_number=1,
        text=text,
        image_path="/tmp/p1.png",
        debug={"has_diagram": has_diagram},
    )


def test_intent_definition() -> None:
    q = normalize_and_expand_query("что такое heap")
    assert q.question_intent == "definition"
    assert "heap" in q.entities


def test_intent_attribute_lookup() -> None:
    q = normalize_and_expand_query("где хранятся ссылочные типы")
    assert q.question_intent == "attribute_lookup"
    assert "reference_types" in q.entities


def test_intent_comparison_mixed_ru_en() -> None:
    q = normalize_and_expand_query("в чем разница между stack и кучей")
    assert q.question_intent == "comparison"
    assert "stack" in q.entities
    assert "heap" in q.entities


def test_intent_mechanism() -> None:
    q = normalize_and_expand_query("как работает архитектура фон Неймана")
    assert q.question_intent in {"mechanism", "diagram_layout"}
    assert "von_neumann" in q.entities


def test_support_attribute_lookup_semantic() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("что хранится в стеке")
    context = [_cand("c1", "Стек — место хранения переменных примитивного типа.")]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is True
    assert support.entity_coverage >= 1.0


def test_support_compare_from_two_facts() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("чем стек отличается от кучи")
    context = [
        _cand("c1", "Стек хранит переменные примитивного типа."),
        _cand("c2", "Куча содержит данные ссылочного типа."),
    ]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is True
    assert support.reason in {"comparison_supported", "semantic_ok", "literal_ok"}


def test_support_diagram_question_with_visual_evidence() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("объясни схему архитектуры")
    context = [
        _cand("v1", "ALU Control Unit Memory blocks", source_type="visual", has_diagram=True, score=0.3),
    ]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is True
    assert support.question_intent == "diagram_layout"


def test_support_paraphrase_ru_en() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("в чем разница между stack и heap")
    context = [
        _cand("c1", "Стек хранит primitive types."),
        _cand("c2", "Heap stores reference type data."),
    ]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is True


def test_good_retrieval_weak_literal_still_allowed() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("где хранятся ссылочные типы")
    context = [_cand("c1", "Heap stores reference type data.", score=0.42)]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is True


def test_negative_insufficient_support() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("чем стек отличается от кучи")
    context = [_cand("c1", "Java byte это 8 бит и диапазон значений ограничен.", score=0.09)]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is False
