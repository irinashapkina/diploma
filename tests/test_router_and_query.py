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
    assert q.question_intent in {"mechanism", "explanation"}


def test_router_visual_for_diagram_questions() -> None:
    q = normalize_and_expand_query("объясни схему архитектуры фон Неймана")
    r = QueryRouter().decide(q.normalized, processed_query=q)
    assert r.mode in {"visual", "hybrid"}
