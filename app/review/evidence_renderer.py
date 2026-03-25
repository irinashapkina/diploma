from __future__ import annotations

from typing import Any


def render_final_evidence(issue: dict[str, Any]) -> str:
    issue_type = str(issue.get("issue_type") or "")
    if issue_type == "CURRENT_CLAIM_OUTDATED":
        return _render_current_claim_outdated(issue)
    if issue_type == "DATE_ACADEMIC_YEAR_MISMATCH":
        return _render_academic_year(issue)
    if issue_type == "PERSON_DATES_INCORRECT":
        return _render_person_reference(issue)
    return _render_default(issue)


def _render_current_claim_outdated(issue: dict[str, Any]) -> str:
    claim = str(issue.get("claim_text") or "").strip()
    updates = issue.get("slot_updates") or []
    replacements = _format_slot_updates(updates)
    if replacements:
        return (
            "В утверждении о текущем состоянии найдены устаревшие значения. "
            f"Нужно обновить: {replacements}."
        )
    if claim:
        return f"Утверждение о текущем состоянии выглядит устаревшим: «{claim}»."
    return "Утверждение о текущем состоянии содержит устаревшие данные."


def _render_academic_year(issue: dict[str, Any]) -> str:
    updates = issue.get("slot_updates") or []
    replacements = _format_slot_updates(updates)
    if replacements:
        return f"В учебной мета-информации найдено несовпадение года: {replacements}."
    return "В учебной мета-информации найдено несовпадение учебного года."


def _render_person_reference(issue: dict[str, Any]) -> str:
    refs = issue.get("source_refs") or []
    if refs:
        return "Даты жизни в тексте противоречат reference-источнику по персоне."
    return "Даты жизни в тексте выглядят некорректно по сравнению с эталонными данными."


def _render_default(issue: dict[str, Any]) -> str:
    evidence = str(issue.get("evidence") or "").strip()
    if evidence:
        return evidence[:220]
    return "Найдено замечание по локальному утверждению."


def _format_slot_updates(updates: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in updates:
        old = str(item.get("from") or "").strip()
        new = str(item.get("to") or "").strip()
        if not old or not new:
            continue
        chunks.append(f"{old} → {new}")
    return ", ".join(chunks)
