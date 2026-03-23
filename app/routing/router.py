from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.retrieval.query_processing import ProcessedQuery


@dataclass
class RoutingDecision:
    mode: Literal["text", "visual", "hybrid"]
    reasons: list[str]


class QueryRouter:
    visual_markers = [
        "схем",
        "рисунк",
        "диаграм",
        "блок",
        "стрелк",
        "на слайде",
        "на странице",
        "архитектур",
        "устройств",
        "картинк",
        "объясни рисунок",
        "объясни схему",
        "что на диаграмме",
        "что обозначают блоки",
        "что изображено",
        "как устроено",
        "как связаны блоки",
        "what is shown",
        "explain diagram",
        "what is on the slide",
        "what is in the picture",
        "diagram",
        "figure",
        "architecture",
        "layout",
        "workflow",
    ]
    text_markers = [
        "что такое",
        "definition",
        "определение",
        "кто такой",
        "годы жизни",
        "дата",
        "термин",
        "когда",
    ]

    def decide(self, query: str, processed_query: ProcessedQuery | None = None) -> RoutingDecision:
        q = query.lower().strip()
        reasons: list[str] = []
        intent = processed_query.question_intent if processed_query else "general"

        visual_hits = sum(1 for m in self.visual_markers if m in q)
        text_hits = sum(1 for m in self.text_markers if m in q)
        has_visual_entity = bool(processed_query and any(e in {"alu", "von_neumann"} for e in processed_query.entities))

        if intent in {"diagram_elements", "diagram_explanation"}:
            reasons.append("intent_diagram")
            return RoutingDecision(mode="visual", reasons=reasons)
        if intent in {"comparison", "composition"} and (visual_hits >= 1 or has_visual_entity):
            reasons.append("semantic_intent_with_visual_cues")
            return RoutingDecision(mode="hybrid", reasons=reasons)

        if visual_hits >= 2:
            reasons.append("visual_markers>=2")
            return RoutingDecision(mode="visual", reasons=reasons)
        if visual_hits >= 1 and any(token in q for token in ["объясни", "поясни", "explain", "what is shown"]):
            reasons.append("visual_explain_intent")
            return RoutingDecision(mode="visual", reasons=reasons)
        if visual_hits >= 1 and text_hits == 0:
            reasons.append("visual_marker_present")
            return RoutingDecision(mode="hybrid", reasons=reasons)
        if text_hits >= 1 and visual_hits == 0:
            reasons.append("text_marker_present")
            return RoutingDecision(mode="text", reasons=reasons)
        reasons.append("default_hybrid")
        return RoutingDecision(mode="hybrid", reasons=reasons)
