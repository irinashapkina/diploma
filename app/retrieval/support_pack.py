from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.query_processing import ENTITY_ALIASES, ENTITY_EXPANSIONS, ProcessedQuery
from app.schemas.models import RetrievalCandidate
from app.utils.text import normalize_text


@dataclass
class SupportPack:
    relevant_pages: list[str]
    supporting_units: list[dict]
    diagram_labels: list[str]
    matched_entities: list[str]
    matched_aliases: list[str]
    neighbor_pages: list[str]
    reasons: list[str]
    coverage_score: float
    evidence_confidence: float

    def as_prompt_block(self, max_units: int = 8) -> str:
        units = self.supporting_units[:max_units]
        lines = [
            f"- {u['source_id']} | type={u['source_type']} | score={u['score']:.3f} | reason={u['reason']} | {u['snippet']}"
            for u in units
        ]
        labels = ", ".join(self.diagram_labels[:10]) if self.diagram_labels else "нет"
        return (
            "Support pack summary:\n"
            f"Relevant pages: {', '.join(self.relevant_pages[:10]) or 'нет'}\n"
            f"Neighbor pages: {', '.join(self.neighbor_pages[:10]) or 'нет'}\n"
            f"Matched entities: {', '.join(self.matched_entities[:10]) or 'нет'}\n"
            f"Matched aliases: {', '.join(self.matched_aliases[:10]) or 'нет'}\n"
            f"Diagram labels: {labels}\n"
            f"Coverage score: {self.coverage_score:.3f}; evidence confidence: {self.evidence_confidence:.3f}\n"
            f"Selection reasons: {', '.join(self.reasons[:8]) or 'нет'}\n"
            f"Support units:\n{chr(10).join(lines) if lines else '- нет'}"
        )


def build_support_pack(
    *,
    processed_query: ProcessedQuery,
    candidates: list[RetrievalCandidate],
    support,
    strongest_evidence: list[str],
    max_units: int = 10,
) -> SupportPack:
    matched_entities: list[str] = []
    matched_aliases: list[str] = []
    relevant_pages: list[str] = []
    neighbor_pages: list[str] = []
    reasons: list[str] = []
    units: list[dict] = []
    diagram_labels: list[str] = []

    alias_hits: set[str] = set()
    for cand in candidates[:14]:
        source_id = f"{cand.document_title}:p{cand.page_number}"
        source_text = normalize_text(cand.text or "")
        if source_id not in relevant_pages:
            relevant_pages.append(source_id)
        is_neighbor = bool(cand.debug.get("is_neighbor_page") or cand.debug.get("is_neighbor_chunk"))
        if is_neighbor and source_id not in neighbor_pages:
            neighbor_pages.append(source_id)
        entity_hits_for_unit: list[str] = []
        for ent in processed_query.entities:
            aliases = ENTITY_ALIASES.get(ent, [ent]) + ENTITY_EXPANSIONS.get(ent, [])
            hit_alias = next((a for a in aliases if normalize_text(a) and normalize_text(a) in source_text), None)
            if hit_alias:
                entity_hits_for_unit.append(ent)
                alias_hits.add(normalize_text(hit_alias))
                if ent not in matched_entities:
                    matched_entities.append(ent)
        label_hits = [lbl for lbl in processed_query.component_labels if lbl and lbl in source_text]
        if bool(cand.debug.get("has_diagram", False)):
            diagram_labels.extend(_extract_diagram_labels(cand.text or "", processed_query))
        reason_tags: list[str] = []
        if entity_hits_for_unit:
            reason_tags.append("entity_match")
        if label_hits:
            reason_tags.append("label_match")
        if cand.source_type == "visual" or bool(cand.debug.get("has_diagram", False)):
            reason_tags.append("diagram_support")
        if is_neighbor:
            reason_tags.append("neighbor_context")
        if cand.candidate_id.startswith("pageagg:"):
            reason_tags.append("page_aggregate")
        if not reason_tags:
            reason_tags.append("semantic_candidate")
        reason = "+".join(reason_tags)
        if reason not in reasons:
            reasons.append(reason)
        units.append(
            {
                "source_id": source_id,
                "source_type": cand.source_type,
                "score": float(cand.score),
                "reason": reason,
                "entity_hits": entity_hits_for_unit,
                "label_hits": label_hits,
                "snippet": " ".join((cand.text or "").split())[:220],
            }
        )
    units.sort(key=lambda x: x["score"], reverse=True)

    matched_aliases = sorted(alias_hits)
    uniq_labels = _dedup(diagram_labels)
    selected_units = units[:max_units]
    strong_unit_count = len([u for u in selected_units if u["score"] >= 0.12])
    coverage_score = (
        0.35 * min(1.0, len(matched_entities) / max(1, len(processed_query.entities) or 1))
        + 0.25 * min(1.0, strong_unit_count / max(1, min(max_units, 6)))
        + 0.2 * min(1.0, len(uniq_labels) / 6.0)
        + 0.2 * min(1.0, len(strongest_evidence) / 4.0)
    )
    evidence_confidence = min(
        1.0,
        0.45 * max((u["score"] for u in selected_units), default=0.0)
        + 0.25 * float(getattr(support, "coverage", 0.0))
        + 0.15 * float(getattr(support, "entity_coverage", 0.0))
        + 0.15 * float(getattr(support, "source_quality", 0.0)),
    )
    return SupportPack(
        relevant_pages=relevant_pages[:12],
        supporting_units=selected_units,
        diagram_labels=uniq_labels[:12],
        matched_entities=matched_entities,
        matched_aliases=matched_aliases[:12],
        neighbor_pages=neighbor_pages[:8],
        reasons=reasons[:12],
        coverage_score=max(0.0, min(1.0, coverage_score)),
        evidence_confidence=max(0.0, min(1.0, evidence_confidence)),
    )


def _extract_diagram_labels(text: str, processed_query: ProcessedQuery) -> list[str]:
    raw = text or ""
    parts = []
    for sep in [",", ";", "\n", "|", "->", "→", "/"]:
        if sep in raw:
            parts.extend(raw.split(sep))
        else:
            parts.append(raw)
    labels: list[str] = []
    for part in parts:
        lbl = normalize_text(part).strip(" -:")
        if not lbl:
            continue
        if len(lbl) <= 2:
            continue
        if len(lbl.split()) > 5:
            continue
        if lbl in processed_query.component_labels:
            labels.append(lbl)
            continue
        if any(normalize_text(alias) == lbl for aliases in ENTITY_ALIASES.values() for alias in aliases):
            labels.append(lbl)
            continue
        if any(tok in lbl for tok in ("алу", "уу", "память", "процессор", "ввод", "вывод", "control", "memory", "alu")):
            labels.append(lbl)
    return labels


def _dedup(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
