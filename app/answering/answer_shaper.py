from __future__ import annotations

from dataclasses import dataclass
import re

from app.answering.fact_extractor import FactExtractionResult, StructuredFact
from app.retrieval.query_processing import ProcessedQuery

COURSE_SOURCE_NOT_FOUND_MESSAGE = "Подходящий источник в материалах курса не найден. Лучше уточнить вопрос у преподавателя."


@dataclass
class ShapingPlan:
    answer_mode: str
    prompt: str


def build_controlled_synthesis_prompt(
    question: str,
    processed_query: ProcessedQuery,
    facts_result: FactExtractionResult,
    selected_sense: dict[str, str],
    support_has_support: bool = False,
    strongest_evidence: list[str] | None = None,
) -> ShapingPlan:
    facts = facts_result.facts
    strongest_evidence = [e.strip() for e in (strongest_evidence or []) if e.strip()]
    is_explanatory = processed_query.question_intent in {
        "process_explanation",
        "interaction_explanation",
        "diagram_explanation",
        "component_role",
    }
    if not facts:
        if support_has_support and strongest_evidence:
            evidence_block = "\n".join(f"- {line}" for line in strongest_evidence[:5])
            if is_explanatory:
                fallback_prompt = (
                    "Ты учебный ассистент. Нужно объяснить тему студенту простыми словами строго по подтвержденным фрагментам.\n"
                    "Нельзя придумывать факты и нельзя копировать OCR-обрывки дословно.\n"
                    "Обязательная структура ответа:\n"
                    "1) коротко назови тему,\n"
                    "2) назови основные элементы,\n"
                    "3) объясни роль каждого элемента,\n"
                    "4) объясни связи и поток взаимодействия по шагам,\n"
                    "5) короткий итог в 1 предложении.\n"
                    "Если вопрос про схему/рисунок, опирайся на найденные элементы схемы и не подменяй ответ общими определениями.\n"
                    "Если данных для одного из шагов нет, прямо напиши об ограничении.\n\n"
                    f"Вопрос: {question}\n"
                    f"Intent: {processed_query.question_intent}\n\n"
                    f"Strongest evidence:\n{evidence_block}\n\n"
                    "Верни только краткое, связное, понятное объяснение."
                )
                return ShapingPlan(answer_mode="fallback_synthesis", prompt=fallback_prompt)
            fallback_prompt = (
                "Ты учебный ассистент. Нужно дать аккуратный краткий ответ только по подтвержденным фрагментам.\n"
                "Эти фрагменты могут быть OCR-шумными, поэтому нельзя копировать их дословно.\n"
                "Нормализуй и переформулируй смысл простым русским языком.\n"
                "Запрещено добавлять факты, которых нет в фрагментах.\n\n"
                f"Вопрос: {question}\n"
                f"Intent: {processed_query.question_intent}\n"
                f"Expected answer shape: {processed_query.expected_answer_shape}\n\n"
                f"Strongest evidence:\n{evidence_block}\n\n"
                "Дай короткий ответ по сути без OCR-мусора, повторов и сырых обрывков."
            )
            return ShapingPlan(answer_mode="fallback_synthesis", prompt=fallback_prompt)
        refusal_prompt = (
            "Ты отвечаешь только по подтвержденным фактам из курса.\n"
            "Подходящего источника в материалах нет.\n"
            f"Верни дословно одну фразу без дополнений: '{COURSE_SOURCE_NOT_FOUND_MESSAGE}'."
        )
        return ShapingPlan(answer_mode="partial_answer", prompt=refusal_prompt)

    direct_answer = _has_direct_answer_shape(facts, processed_query.question_intent)
    answer_mode = "extractive" if direct_answer else "grounded_synthesis"
    facts_block = _format_facts(facts)
    senses = ", ".join(f"{k} -> {v}" for k, v in selected_sense.items()) or "нет"
    source_phrases = "\n".join(f"- {f.source_phrase}" for f in facts[:8])
    extra_explanation_rules = ""
    if is_explanatory:
        extra_explanation_rules = (
            "Для explanatory-вопроса отвечай простыми словами и строго по шагам:\n"
            "1) коротко назови тему,\n"
            "2) назови основные блоки/элементы,\n"
            "3) кратко объясни роль каждого,\n"
            "4) объясни их взаимодействие и поток выполнения,\n"
            "5) добавь краткий итог в 1 предложении.\n"
            "Если вопрос про схему/рисунок, опирайся на элементы и подписи найденной схемы.\n"
            "Не подменяй вопрос про взаимодействие перечислением общих принципов и терминов.\n"
            "Не перечисляй только названия блоков без объяснения взаимодействий.\n"
            "Не копируй сырые OCR-фразы, а аккуратно перефразируй подтвержденный смысл.\n"
            "Если подтверждений недостаточно, честно укажи ограничение.\n"
        )
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
        f"{extra_explanation_rules}"
        "Ответ должен быть коротким, полезным и строго grounded."
    )
    return ShapingPlan(answer_mode=answer_mode, prompt=prompt)


def build_answer_polishing_prompt(
    *,
    question: str,
    draft_answer: str,
    processed_query: ProcessedQuery,
    evidence_phrases: list[str],
) -> str:
    cleaned_evidence = [_normalize_phrase(p) for p in evidence_phrases if p.strip()]
    evidence_block = "\n".join(f"- {line}" for line in cleaned_evidence[:6])
    return (
        "Отполируй черновой ответ для студента.\n"
        "Нужно сохранить только подтвержденный смысл из evidence.\n"
        "Запрещено добавлять новые факты.\n"
        "Убери OCR-шум, обрывки, повторы и мусорные формулы.\n"
        "Ответ должен быть коротким и читабельным.\n\n"
        f"Вопрос: {question}\n"
        f"Intent: {processed_query.question_intent}\n"
        f"Черновой ответ:\n{draft_answer.strip()}\n\n"
        f"Evidence:\n{evidence_block or '- (нет)'}\n\n"
        "Верни только финальный ответ на русском."
    )


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


def build_fallback_answer_from_facts(processed_query: ProcessedQuery, facts_result: FactExtractionResult) -> str:
    facts = facts_result.facts[:8]
    if not facts:
        return COURSE_SOURCE_NOT_FOUND_MESSAGE
    if processed_query.question_intent == "diagram_elements":
        labels = _unique_phrases([f.source_phrase for f in facts])
        return "На схеме показаны: " + ", ".join(labels[:8]) + "."
    if processed_query.question_intent == "comparison":
        phrases = _unique_phrases([f.source_phrase for f in facts])
        if len(phrases) >= 2:
            return f"По материалам: {phrases[0]}, а также {phrases[1]}."
    if processed_query.question_intent == "fact_lookup":
        phrases = _unique_phrases([_normalize_phrase(f.source_phrase) for f in facts])
        return "По материалам перечислены: " + ", ".join(phrases[:6]) + "."
    if processed_query.question_intent == "composition":
        phrases = _unique_phrases([f.source_phrase for f in facts])
        return "По материалам, в состав входят: " + ", ".join(phrases[:6]) + "."
    if processed_query.question_intent in {"process_explanation", "interaction_explanation", "diagram_explanation", "component_role"}:
        phrases = _unique_phrases([_normalize_phrase(f.source_phrase) for f in facts])
        topic = phrases[0] if phrases else "тема"
        elements = ", ".join(phrases[:3]) if phrases else "элементы не выделены"
        flow = " затем ".join(phrases[3:5]) if len(phrases) > 3 else ""
        if flow:
            return f"Тема: {topic}. Основные элементы: {elements}. По материалам, взаимодействие по шагам: {flow}."
        return f"Тема: {topic}. Основные элементы: {elements}. По материалам, их связь описана в найденных фрагментах."
    return "По материалам: " + "; ".join(_unique_phrases([f.source_phrase for f in facts])[:4]) + "."


def build_fallback_answer_from_evidence(processed_query: ProcessedQuery, strongest_evidence: list[str]) -> str:
    phrases = _unique_phrases([_normalize_phrase(p) for p in strongest_evidence if p.strip()])
    if not phrases:
        return COURSE_SOURCE_NOT_FOUND_MESSAGE
    if processed_query.question_intent == "diagram_elements":
        return "На слайде показаны: " + ", ".join(phrases[:6]) + "."
    if processed_query.question_intent == "comparison" and len(phrases) >= 2:
        return f"По материалам: {phrases[0]}; {phrases[1]}."
    if processed_query.question_intent == "fact_lookup":
        return "По материалам перечислены: " + ", ".join(phrases[:6]) + "."
    if processed_query.question_intent in {"process_explanation", "interaction_explanation", "diagram_explanation", "component_role"}:
        if len(phrases) >= 2:
            return f"Тема: {phrases[0]}. Основные элементы и их связь по материалам: {phrases[1]}."
        return "По материалам, объяснение ограничено: " + phrases[0] + "."
    return phrases[0] if len(phrases[0].split()) >= 3 else "По материалам: " + "; ".join(phrases[:3]) + "."


def _unique_phrases(phrases: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        p = " ".join(phrase.split()).strip(" ,.;:")
        key = p.lower()
        if not p or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _normalize_phrase(phrase: str) -> str:
    txt = " ".join(phrase.split()).strip(" ,.;:")
    txt = re.sub(r"[|]{2,}", " ", txt)
    txt = re.sub(r"(.)\1{3,}", r"\1\1", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()
