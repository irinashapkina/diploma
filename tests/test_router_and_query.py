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


def test_router_visual_for_diagram_questions() -> None:
    r = QueryRouter().decide("объясни схему архитектуры фон Неймана")
    assert r.mode in {"visual", "hybrid"}
