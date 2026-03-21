from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class RoutingDecision:
    mode: Literal["text", "visual", "hybrid"]
    reasons: list[str]


class QueryRouter:
    visual_markers = [
        "схем",
        "рисунк",
        "диаграм",
        "на слайде",
        "на странице",
        "архитектур",
        "что изображено",
        "как устроено",
        "what is shown",
        "diagram",
        "figure",
        "architecture",
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

    def decide(self, query: str) -> RoutingDecision:
        q = query.lower().strip()
        reasons: list[str] = []

        visual_hits = sum(1 for m in self.visual_markers if m in q)
        text_hits = sum(1 for m in self.text_markers if m in q)

        if visual_hits >= 2:
            reasons.append("visual_markers>=2")
            return RoutingDecision(mode="visual", reasons=reasons)
        if visual_hits >= 1 and text_hits == 0:
            reasons.append("visual_marker_present")
            return RoutingDecision(mode="hybrid", reasons=reasons)
        if text_hits >= 1 and visual_hits == 0:
            reasons.append("text_marker_present")
            return RoutingDecision(mode="text", reasons=reasons)
        reasons.append("default_hybrid")
        return RoutingDecision(mode="hybrid", reasons=reasons)
