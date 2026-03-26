from __future__ import annotations

from typing import Any
import re


def render_final_evidence(issue: dict[str, Any]) -> str:
    issue_type = str(issue.get("issue_type") or "")
    issue_family = str(issue.get("issue_family") or "")
    if issue_type == "CURRENT_CLAIM_OUTDATED":
        return _render_current_claim_outdated(issue)
    if issue_type == "TECH_VERSION_OUTDATED":
        return _render_tech_version_outdated(issue)
    if issue_type == "DATE_ACADEMIC_YEAR_MISMATCH":
        return _render_academic_year(issue)
    if issue_type == "PERSON_DATES_INCORRECT":
        return _render_person_reference(issue)
    if issue_family == "outdated":
        return _render_outdated_generic(issue)
    if issue_family == "metadata":
        return _render_metadata_generic(issue)
    if issue_family == "terminology":
        return _render_terminology_generic(issue)
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


def _render_tech_version_outdated(issue: dict[str, Any]) -> str:
    claim = str(issue.get("claim_text") or "").strip()
    updates = issue.get("slot_updates") or []
    technology = _pick_technology(issue)
    replacements = _format_slot_updates(updates)
    if replacements and technology:
        return f"В материале указана устаревшая актуальная версия {technology}: {replacements}."
    if replacements:
        return f"В материале указана устаревшая актуальная версия: {replacements}."
    if claim and technology:
        return f"Формулировка про актуальную версию {technology} выглядит устаревшей."
    if claim:
        return "Формулировка про актуальную версию технологии выглядит устаревшей."
    return "В тексте указана устаревшая версия технологии."


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


def _render_outdated_generic(issue: dict[str, Any]) -> str:
    updates = issue.get("slot_updates") or []
    replacements = _format_slot_updates(updates)
    if replacements:
        return f"В утверждении найдены устаревшие значения: {replacements}."
    claim = str(issue.get("claim_text") or "").strip()
    if claim:
        return "Утверждение в материале выглядит устаревшим и требует обновления."
    return "Найдено устаревшее утверждение, требующее обновления."


def _render_metadata_generic(issue: dict[str, Any]) -> str:
    updates = issue.get("slot_updates") or []
    replacements = _format_slot_updates(updates)
    if replacements:
        return f"В мета-информации документа найдено несовпадение: {replacements}."
    return "В мета-информации документа найдено несовпадение."


def _render_terminology_generic(issue: dict[str, Any]) -> str:
    detected = str(issue.get("detected_text") or "").strip()
    suggestion = str(issue.get("suggestion") or "").strip()
    if detected and suggestion:
        return f"Термин «{detected}» рекомендуется заменить на более актуальный: «{suggestion}»."
    if detected:
        return f"В тексте используется термин «{detected}», который требует уточнения."
    return "В тексте найден термин, требующий уточнения."


def _render_default(issue: dict[str, Any]) -> str:
    evidence = str(issue.get("evidence") or "").strip()
    cleaned = _sanitize_technical_evidence(evidence)
    if cleaned:
        return cleaned[:220]
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


def _pick_technology(issue: dict[str, Any]) -> str:
    refs = issue.get("source_refs") or []
    if not refs:
        return ""
    return str(refs[0]).strip()


def _sanitize_technical_evidence(evidence: str) -> str:
    if not evidence:
        return ""
    value = str(evidence).strip()
    value = re.sub(r"\b[Cc]laim-role\s*=\s*[\w_:-]+\b", "", value)
    value = re.sub(r"\bcurrent-status\b", "утверждение о текущем состоянии", value, flags=re.IGNORECASE)
    value = re.sub(r"\bbaseline\s+рекомендует\b", "рекомендуемое актуальное значение", value, flags=re.IGNORECASE)
    value = re.sub(r"\s{2,}", " ", value).strip(" ;,.-")
    if any(token in value.lower() for token in ("claim-role=", "slot_updates", "policy_action")):
        return ""
    return value
