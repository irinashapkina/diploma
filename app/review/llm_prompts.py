from __future__ import annotations

import json


ROLE_TRIAGE_SYSTEM = (
    "Ты классификатор учебных claim. Возвращай только JSON без markdown.\n"
    "Запрещено придумывать факты, используй только входные поля."
)

EVIDENCE_RENDER_SYSTEM = (
    "Ты редактор user-facing объяснений для замечаний преподавателя.\n"
    "Верни только JSON. Текст должен быть коротким, понятным, без внутреннего тех.жаргона."
)

SUGGESTION_RENDER_SYSTEM = (
    "Ты редактор локальных правок claim.\n"
    "Верни только JSON. Разрешено редактировать только данный claim, без переписывания соседнего текста."
)


def build_role_triage_prompt(payload: dict) -> str:
    schema = {
        "role": "current_state_claim | historical_reference | origin_or_first_version | biography_fact | academic_metadata | example_or_quote | ambiguous_claim",
        "confidence": "float 0..1",
        "should_create_issue": "bool",
        "reasoning_short": "string <= 180 chars",
    }
    return (
        "Задача: уточни роль claim и решение по issue для неоднозначного случая.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
    )


def build_evidence_render_prompt(payload: dict) -> str:
    schema = {"evidence_text": "string <= 220 chars"}
    return (
        "Задача: сформулируй человекочитаемое объяснение для замечания.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
    )


def build_suggestion_render_prompt(payload: dict) -> str:
    schema = {
        "replacement_text": "string <= 260 chars",
        "confidence": "float 0..1",
        "notes": "string <= 120 chars",
    }
    return (
        "Задача: собрать аккуратную локальную замену claim по slot updates.\n"
        "Нельзя переписывать текст вне claim.\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
    )
