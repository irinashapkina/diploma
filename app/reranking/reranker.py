from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.schemas.models import RetrievalCandidate
from app.utils.text import tokenize_mixed


@dataclass
class RerankConfig:
    text_weight: float = 0.45
    dense_weight: float = 0.35
    lexical_weight: float = 0.15
    visual_bonus: float = 0.25
    diagram_bonus: float = 0.08
    noise_penalty: float = 0.12


class HeuristicReranker:
    def __init__(self, cfg: RerankConfig | None = None) -> None:
        self.cfg = cfg or RerankConfig()

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        mode: str,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        q_tokens = set(tokenize_mixed(query))
        rescored: list[RetrievalCandidate] = []
        for cand in candidates:
            text = cand.text or ""
            text_tokens = set(tokenize_mixed(text))
            overlap = len(q_tokens & text_tokens) / max(1, len(q_tokens))
            partial = fuzz.partial_ratio(query.lower(), text.lower()) / 100.0 if text else 0.0
            bm25_score = float(cand.debug.get("bm25_score", 0.0))
            dense_score = float(cand.debug.get("dense_score", 0.0))
            visual_score = float(cand.debug.get("visual_score", 0.0))
            has_diagram = bool(cand.debug.get("has_diagram", False))
            text_len = len(text.strip())
            noise = 1.0 if text_len < 40 else 0.0

            score = (
                self.cfg.text_weight * bm25_score
                + self.cfg.dense_weight * dense_score
                + self.cfg.lexical_weight * (0.6 * overlap + 0.4 * partial)
            )
            if mode in {"visual", "hybrid"}:
                score += self.cfg.visual_bonus * visual_score
            if has_diagram and mode in {"visual", "hybrid"}:
                score += self.cfg.diagram_bonus
            score -= self.cfg.noise_penalty * noise
            cand.score = score
            cand.debug["overlap"] = overlap
            cand.debug["partial_ratio"] = partial
            rescored.append(cand)

        rescored.sort(key=lambda x: x.score, reverse=True)
        filtered = [c for c in rescored if c.score > 0.02]
        return filtered[:top_k]

