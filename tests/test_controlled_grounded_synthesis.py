from __future__ import annotations

from app.answering.answer_shaper import build_controlled_synthesis_prompt
from app.answering.fact_extractor import extract_structured_facts
from app.pipeline.rag_pipeline import RAGPipeline
from app.retrieval.query_processing import normalize_and_expand_query
from app.retrieval.sense_disambiguation import disambiguate_entities
from app.schemas.models import RetrievalCandidate
from app.validation.confidence import estimate_confidence
from app.validation.grounding import GroundingValidator, SupportAssessment


def _cand(
    cid: str,
    text: str,
    *,
    score: float = 0.35,
    source_type: str = "text",
    page: int = 1,
    has_diagram: bool = False,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        candidate_id=cid,
        source_type=source_type,  # type: ignore[arg-type]
        score=score,
        document_id="doc1",
        document_title="Doc",
        page_id=f"doc1_p{page}",
        page_number=page,
        text=text,
        image_path=f"/tmp/p{page}.png",
        debug={"has_diagram": has_diagram, "text_source": "pdf", "pdf_text_quality": 0.8, "ocr_text_quality": 0.7},
    )


def test_random_access_machine_not_disambiguated_as_memory() -> None:
    q = normalize_and_expand_query("какие элементы есть у Random Access Machine на схеме")
    if "ram" not in q.entities:
        q.entities.append("ram")
    decision = disambiguate_entities(q)
    assert decision.selected_sense.get("ram") == "ram_machine"


def test_comparison_built_from_source_attributes() -> None:
    q = normalize_and_expand_query("чем стек отличается от кучи")
    candidates = [
        _cand("c1", "Стек хранит переменные примитивного типа.", score=0.45),
        _cand("c2", "Куча содержит данные ссылочного типа.", score=0.44, page=2),
    ]
    facts_result = extract_structured_facts(q, candidates)
    entities = {f.entity for f in facts_result.facts}
    phrases = " ".join(f.source_phrase for f in facts_result.facts).lower()
    assert "stack" in entities or "heap" in entities
    assert "примитивного типа" in phrases
    assert "данные ссылочного типа" in phrases


def test_composition_extracts_components() -> None:
    q = normalize_and_expand_query("что входит в архитектуру фон Неймана")
    candidates = [
        _cand(
            "c1",
            "Архитектура фон Неймана включает: устройство ввода, устройство вывода, память, арифметико-логическое устройство, устройство управления.",
            score=0.48,
        )
    ]
    facts_result = extract_structured_facts(q, candidates)
    assert any(f.attribute == "components" for f in facts_result.facts)
    phrases = " ".join(f.source_phrase for f in facts_result.facts).lower()
    assert "устройство ввода" in phrases
    assert "устройство управления" in phrases


def test_diagram_elements_extracts_list() -> None:
    q = normalize_and_expand_query("какие элементы есть у Random Access Machine на схеме")
    candidates = [
        _cand("v1", "ALU, Control Unit, Memory, Input, Output", source_type="visual", has_diagram=True, score=0.41),
        _cand("v2", "На схеме RAM показаны блоки ALU и Control Unit.", source_type="visual", has_diagram=True, page=2),
    ]
    facts_result = extract_structured_facts(q, candidates, selected_sense={"ram": "ram_machine"})
    assert facts_result.likely_multi_source is True
    assert facts_result.multi_source_fulfilled is True
    assert len(facts_result.contributing_sources) >= 2


def test_answer_prompt_is_grounded_synthesis_not_raw_snippet_dump() -> None:
    q = normalize_and_expand_query("чем стек отличается от кучи")
    candidates = [
        _cand("c1", "Стек хранит переменные примитивного типа.", score=0.45),
        _cand("c2", "Куча содержит данные ссылочного типа.", score=0.44, page=2),
    ]
    facts_result = extract_structured_facts(q, candidates)
    plan = build_controlled_synthesis_prompt(q.original, q, facts_result, selected_sense={})
    assert plan.answer_mode == "grounded_synthesis"
    assert "Structured facts" in plan.prompt
    assert "Source phrases (verbatim)" in plan.prompt


def test_confidence_drops_for_noisy_extraction_or_refusal() -> None:
    q = normalize_and_expand_query("что хранится в стеке и что хранится в куче")
    noisy_candidates = [
        _cand("c1", "123 456 !!!", score=0.42),
        _cand("c2", "слайд 5", score=0.41, page=2),
    ]
    facts_result = extract_structured_facts(q, noisy_candidates)
    validator = GroundingValidator()
    validation = validator.validate("Недостаточно данных в материалах.", noisy_candidates)
    confidence, breakdown = estimate_confidence(
        answer="Недостаточно данных в материалах.",
        candidates=noisy_candidates,
        validation=validation,
        mode="text",
        facts_result=facts_result,
        answer_mode="partial_answer",
    )
    assert confidence < 0.5
    assert breakdown["quality_facts"] <= 0.2


def test_pipeline_diagram_elements_non_empty_with_empty_llm_answer(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [
        _cand("v1", "Random Access Machine (1960е)", source_type="visual", has_diagram=True, score=0.51),
        _cand(
            "v2",
            "входная read-only лента, выходная write-only лента, ALU, Control Unit",
            source_type="visual",
            has_diagram=True,
            score=0.49,
            page=4,
        ),
        _cand("t3", "Random Access Memory — Оперативная память.", score=0.42, page=4),
    ]

    monkeypatch.setattr(
        pipeline.retriever,
        "retrieve",
        lambda **kwargs: (candidates, {"final_candidates": []}),
    )
    monkeypatch.setattr(pipeline.answerer, "generate", lambda prompt, image_paths, system_prompt=None: "")
    monkeypatch.setattr(
        pipeline.validator,
        "assess_support",
        lambda question, context_items, processed_query=None: SupportAssessment(
            has_support=True,
            answer_allowed=True,
            coverage=0.6,
            overlap_terms=["ram", "схеме"],
            question_intent="diagram_elements",
            entities=["ram_machine"],
            normalized_relations=["diagram_elements"],
            entity_coverage=1.0,
            relation_coverage=1.0,
            source_quality=0.8,
            supporting_facts=["входная read-only лента", "выходная write-only лента", "alu", "control unit"],
            reason="diagram_supported",
        ),
    )
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg1")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("какие элементы есть у Random Access Machine на схеме", course_id="course1", debug=True)
    assert resp.answer.strip() != ""
    assert ("read-only" in resp.answer.lower()) or ("write-only" in resp.answer.lower())
    assert "оперативная память" not in " ".join(f["source_phrase"] for f in resp.debug["structured_facts"]).lower()


def test_confidence_is_strongly_capped_for_empty_answer() -> None:
    q = normalize_and_expand_query("какие элементы есть у Random Access Machine на схеме")
    candidates = [_cand("v1", "ALU, Control Unit, read-only tape", source_type="visual", has_diagram=True, score=0.9)]
    facts_result = extract_structured_facts(q, candidates, selected_sense={"ram": "ram_machine"})
    validator = GroundingValidator()
    validation = validator.validate("", candidates)
    confidence, _ = estimate_confidence(
        answer="",
        candidates=candidates,
        validation=validation,
        mode="visual",
        facts_result=facts_result,
        answer_mode="grounded_synthesis",
    )
    assert confidence <= 0.15


def test_pipeline_polishes_noisy_ocr_answer_when_support_exists(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [
        _cand(
            "c1",
            "stack primitiv var.. store ;;; 111 ###",
            score=0.47,
            source_type="text",
            page=7,
        )
    ]
    monkeypatch.setattr(
        pipeline.retriever,
        "retrieve",
        lambda **kwargs: (candidates, {"final_candidates": []}),
    )
    monkeypatch.setattr(
        pipeline.validator,
        "assess_support",
        lambda question, context_items, processed_query=None: SupportAssessment(
            has_support=True,
            answer_allowed=True,
            coverage=0.52,
            overlap_terms=["stack", "store"],
            question_intent="attribute_lookup",
            entities=["stack"],
            normalized_relations=["storage"],
            entity_coverage=1.0,
            relation_coverage=0.7,
            source_quality=0.62,
            supporting_facts=["stack primitiv var store"],
            reason="semantic_ok",
        ),
    )

    def _generate(prompt: str, image_paths: list[str], system_prompt: str | None = None) -> str:
        if "Отполируй черновой ответ" in prompt:
            return "По материалам слайда, в стеке хранятся переменные примитивного типа."
        return "stack primitiv var.. store ;;; 111 ###"

    monkeypatch.setattr(pipeline.answerer, "generate", _generate)
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-polish")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("что хранится в стеке", course_id="course1", debug=True)
    assert "примитивного типа" in resp.answer.lower()
    assert "###" not in resp.answer
    assert "подходящий источник" not in resp.answer.lower()


def test_pipeline_returns_refusal_when_no_supported_source(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [
        _cand("c1", "Java byte это 8 бит.", score=0.08, page=3),
    ]
    monkeypatch.setattr(
        pipeline.retriever,
        "retrieve",
        lambda **kwargs: (candidates, {"final_candidates": []}),
    )
    monkeypatch.setattr(
        pipeline.validator,
        "assess_support",
        lambda question, context_items, processed_query=None: SupportAssessment(
            has_support=False,
            answer_allowed=False,
            coverage=0.1,
            overlap_terms=[],
            question_intent="comparison",
            entities=["stack", "heap"],
            normalized_relations=["compare"],
            entity_coverage=0.0,
            relation_coverage=0.0,
            source_quality=0.15,
            supporting_facts=[],
            reason="insufficient_semantic_support",
        ),
    )
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-refusal")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("чем стек отличается от кучи", course_id="course1", debug=True)
    assert resp.answer == "Подходящий источник в материалах курса не найден. Лучше уточнить вопрос у преподавателя."
    assert resp.sources == []


def test_pipeline_rephrases_answer_from_single_strong_page(monkeypatch) -> None:
    pipeline = RAGPipeline()
    candidates = [
        _cand("c1", "Куча содержит данные ссылочного типа.", score=0.5, page=2),
    ]
    monkeypatch.setattr(
        pipeline.retriever,
        "retrieve",
        lambda **kwargs: (candidates, {"final_candidates": []}),
    )
    monkeypatch.setattr(
        pipeline.validator,
        "assess_support",
        lambda question, context_items, processed_query=None: SupportAssessment(
            has_support=True,
            answer_allowed=True,
            coverage=0.56,
            overlap_terms=["куча", "ссылочного"],
            question_intent="attribute_lookup",
            entities=["heap"],
            normalized_relations=["storage"],
            entity_coverage=1.0,
            relation_coverage=0.8,
            source_quality=0.84,
            supporting_facts=["куча содержит данные ссылочного типа"],
            reason="semantic_ok",
        ),
    )

    def _generate(prompt: str, image_paths: list[str], system_prompt: str | None = None) -> str:
        if "Отполируй черновой ответ" in prompt:
            return "По материалам курса, в куче хранятся данные ссылочного типа."
        return "Куча содержит данные ссылочного типа."

    monkeypatch.setattr(pipeline.answerer, "generate", _generate)
    monkeypatch.setattr(pipeline.store, "create_ask_message", lambda **kwargs: "msg-single")
    monkeypatch.setattr(pipeline.store, "create_answer_sources", lambda **kwargs: None)

    resp = pipeline.ask("что хранится в куче", course_id="course1", debug=True)
    assert "ссылочного типа" in resp.answer.lower()
    assert len(resp.sources) >= 1
    assert resp.sources[0].page == 2
