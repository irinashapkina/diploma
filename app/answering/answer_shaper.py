from __future__ import annotations

from dataclasses import dataclass

from app.answering.fact_extractor import FactExtractionResult, StructuredFact
from app.retrieval.query_processing import ProcessedQuery


@dataclass
class ShapingPlan:
    answer_mode: str
    prompt: str


def build_controlled_synthesis_prompt(
    question: str,
    processed_query: ProcessedQuery,
    facts_result: FactExtractionResult,
    selected_sense: dict[str, str],
) -> ShapingPlan:
    facts = facts_result.facts
    if not facts:
        refusal_prompt = (
            "Ты отвечаешь только по подтвержденным фактам из курса.\n"
            "Фактов недостаточно для уверенного ответа.\n"
            "Сформулируй краткий честный частичный ответ: "
            "'Недостаточно данных в материалах для полного ответа' и добавь, что именно не найдено."
        )
        return ShapingPlan(answer_mode="partial_answer", prompt=refusal_prompt)

    direct_answer = _has_direct_answer_shape(facts, processed_query.question_intent)
    answer_mode = "extractive" if direct_answer else "grounded_synthesis"
    facts_block = _format_facts(facts)
    senses = ", ".join(f"{k} -> {v}" for k, v in selected_sense.items()) or "нет"
    source_phrases = "\n".join(f"- {f.source_phrase}" for f in facts[:8])
    prompt = (
        "Ты учебный ассистент. Разрешено использовать только подтвержденные факты ниже.\n"
        "Нельзя добавлять детали, которых нет в source phrases.\n"
        "Сохраняй терминологию преподавателя: если термин уже есть в source phrases, используй его дословно.\n"
        "Нельзя подменять термин более свободным аналогом без причины.\n\n"
        f"Вопрос: {question}\n"
        f"Intent: {processed_query.question_intent}\n"
        f"Expected answer shape: {processed_query.expected_answer_shape}\n"
        f"Selected sense: {senses}\n"
        f"Likely multi source: {facts_result.likely_multi_source}\n"
        f"Multi source fulfilled: {facts_result.multi_source_fulfilled}\n\n"
        f"Structured facts:\n{facts_block}\n\n"
        f"Source phrases (verbatim):\n{source_phrases}\n\n"
        "Собери связный ответ на русском:\n"
        "1) ответ по форме вопроса,\n"
        "2) объединение 2-3 фактов при необходимости,\n"
        "3) без списка источников в конце,\n"
        "4) если данных частично не хватает, явно пометь частичность.\n"
        "Ответ должен быть коротким, полезным и строго grounded."
    )
    return ShapingPlan(answer_mode=answer_mode, prompt=prompt)


def _format_facts(facts: list[StructuredFact]) -> str:
    lines: list[str] = []
    for idx, fact in enumerate(facts[:10], start=1):
        lines.append(
            f"{idx}. type={fact.fact_type}; entity={fact.entity}; attribute={fact.attribute}; "
            f"value={fact.value}; source={fact.source_id}; score={fact.score:.3f}"
        )
    return "\n".join(lines)


def _has_direct_answer_shape(facts: list[StructuredFact], question_intent: str) -> bool:
    if question_intent == "definition":
        return any(("—" in f.source_phrase or "это" in f.source_phrase.lower()) for f in facts[:3])
    if question_intent == "attribute_lookup":
        return any(("хран" in f.source_phrase.lower() or "contains" in f.source_phrase.lower()) for f in facts[:3])
    return False
