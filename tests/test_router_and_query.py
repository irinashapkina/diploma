from app.retrieval.query_processing import normalize_and_expand_query
from app.routing.router import QueryRouter


def test_router_visual_intent() -> None:
    r = QueryRouter().decide("что изображено на схеме ram")
    assert r.mode in {"visual", "hybrid"}


def test_query_expansion_contains_alias() -> None:
    q = normalize_and_expand_query("как работает ram")
    forms = " ".join(q.retrieval_forms).lower()
    assert "random access machine" in forms
    assert "random access memory" in forms
    assert "оперативная память" in forms
    assert q.question_intent in {"general", "diagram_explanation", "composition", "process_explanation"}


def test_router_visual_for_diagram_questions() -> None:
    q = normalize_and_expand_query("объясни схему архитектуры фон Неймана")
    r = QueryRouter().decide(q.normalized, processed_query=q)
    assert r.mode in {"visual", "hybrid"}


def test_student_style_query_rewrite_for_explanatory_question() -> None:
    q = normalize_and_expand_query("я не понимаю как работает архитектура фон Неймана объясни подробно как они взаимодействуют там")
    assert q.question_intent in {"process_explanation", "interaction_explanation", "diagram_explanation"}
    assert 2 <= len(q.retrieval_queries_academic) <= 5
    forms = " | ".join(q.retrieval_queries_academic).lower()
    assert "архитектура фон неймана" in forms
    assert any(marker in forms for marker in ["взаимодейств", "схема", "алу", "память"])
    visual_words = q.visual_query.split()
    assert len(visual_words) <= 14
    assert "понимаю" not in visual_words


def test_component_role_intent_detected() -> None:
    q = normalize_and_expand_query("объясни по схеме что делает УУ и как оно связано с памятью")
    assert q.question_intent in {"component_role", "diagram_explanation", "interaction_explanation"}
    assert len(q.visual_query.split()) <= 14
