from __future__ import annotations

from app.answering.fact_extractor import extract_structured_facts
from app.retrieval.query_processing import normalize_and_expand_query
from app.retrieval.sense_disambiguation import disambiguate_entities
from app.schemas.models import RetrievalCandidate
from app.validation.confidence import estimate_confidence
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
    assert q.question_intent in {"diagram_explanation", "composition"}
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
    assert support.question_intent in {"diagram_explanation", "diagram_elements"}


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


def test_ram_disambiguation_prefers_machine_when_diagram_context() -> None:
    q = normalize_and_expand_query("какие элементы есть у Random Access Machine на схеме")
    if "ram" not in q.entities:
        q.entities.append("ram")
    decision = disambiguate_entities(q)
    assert decision.selected_sense.get("ram") == "ram_machine"


def test_stack_heap_fact_extraction_keeps_source_wording() -> None:
    q = normalize_and_expand_query("что хранится в стеке и что хранится в куче")
    context = [
        _cand("c1", "Стек хранит переменные примитивного типа."),
        _cand("c2", "Куча содержит данные ссылочного типа."),
    ]
    facts = extract_structured_facts(q, context).facts
    phrases = " ".join(f.source_phrase for f in facts).lower()
    assert "данные ссылочного типа" in phrases
    assert "примитивного типа" in phrases


def test_confidence_penalizes_empty_and_refusal_answers() -> None:
    q = normalize_and_expand_query("чем стек отличается от кучи")
    context = [_cand("c1", "Стек хранит переменные примитивного типа.", score=0.42)]
    facts_result = extract_structured_facts(q, context)
    validator = GroundingValidator()
    empty_validation = validator.validate("", context)
    empty_conf, _ = estimate_confidence(
        answer="",
        candidates=context,
        validation=empty_validation,
        mode="text",
        facts_result=facts_result,
        answer_mode="partial_answer",
    )
    refusal_validation = validator.validate("Недостаточно данных в материалах.", context)
    refusal_conf, _ = estimate_confidence(
        answer="Недостаточно данных в материалах.",
        candidates=context,
        validation=refusal_validation,
        mode="text",
        facts_result=facts_result,
        answer_mode="partial_answer",
    )
    assert empty_conf < 0.35
    assert refusal_conf < 0.45


def test_definition_requires_term_presence_not_semantic_only() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("что такое ооп")
    context = [_cand("c1", "Объектная модель в Java описывает классы и объекты.", score=0.55)]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.answer_allowed is False
    assert support.has_support is False
    assert support.definition_term_present is False


def test_definition_supported_for_ram_with_explicit_definition_phrase() -> None:
    validator = GroundingValidator()
    q = normalize_and_expand_query("что такое ram")
    context = [_cand("c1", "RAM / Random Access Memory – оперативная память (память с произвольным доступом).", score=0.52)]
    support = validator.assess_support(question=q.original, context_items=context, processed_query=q)
    assert support.definition_term_present is True
    assert support.definition_supported is True
    assert support.answer_allowed is True
