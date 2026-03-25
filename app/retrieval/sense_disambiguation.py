from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.query_processing import ProcessedQuery
from app.utils.text import normalize_for_retrieval, normalize_text


@dataclass
class SenseOption:
    sense_id: str
    labels: list[str]
    cues: list[str]
    anti_cues: list[str]
    intents: list[str]


@dataclass
class SenseDecision:
    selected_sense: dict[str, str]
    ambiguity: dict[str, float]
    reasons: dict[str, list[str]]


AMBIGUOUS_SENSES: dict[str, list[SenseOption]] = {
    "ram": [
        SenseOption(
            sense_id="ram_machine",
            labels=["random access machine", "машина с произвольным доступом"],
            cues=["machine", "архитектура", "схема", "блок", "alu", "control unit", "аккумулятор", "команда"],
            anti_cues=["оперативная память", "озу", "байт", "ячейка памяти"],
            intents=["composition", "diagram_elements", "diagram_explanation", "process_explanation", "interaction_explanation"],
        ),
        SenseOption(
            sense_id="ram_memory",
            labels=["random access memory", "оперативная память", "озу"],
            cues=["memory", "память", "оперативная", "ячейка", "байт", "адрес", "доступ к данным"],
            anti_cues=["alu", "control unit", "архитектура машины"],
            intents=["definition", "attribute_lookup", "comparison"],
        ),
    ],
}


def disambiguate_entities(processed_query: ProcessedQuery) -> SenseDecision:
    q_norm = normalize_text(processed_query.original)
    q_stem = normalize_for_retrieval(processed_query.original)
    selected: dict[str, str] = {}
    ambiguity: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    for entity in processed_query.entities:
        options = AMBIGUOUS_SENSES.get(entity, [])
        if not options:
            continue
        scored: list[tuple[str, float, list[str]]] = []
        for option in options:
            score = 0.0
            why: list[str] = []
            for label in option.labels:
                if _contains_phrase(q_norm, q_stem, label):
                    score += 0.45
                    why.append(f"label:{label}")
            for cue in option.cues:
                if _contains_phrase(q_norm, q_stem, cue):
                    score += 0.18
                    why.append(f"cue:{cue}")
            for anti in option.anti_cues:
                if _contains_phrase(q_norm, q_stem, anti):
                    score -= 0.2
                    why.append(f"anti:{anti}")
            if processed_query.question_intent in option.intents:
                score += 0.14
                why.append(f"intent:{processed_query.question_intent}")
            scored.append((option.sense_id, score, why))
        scored.sort(key=lambda x: x[1], reverse=True)
        if not scored:
            continue
        best_id, best_score, best_why = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0.0
        margin = best_score - second_score
        selected[entity] = best_id
        ambiguity[entity] = max(0.0, 1.0 - max(0.0, margin))
        reasons[entity] = best_why[:6]
    return SenseDecision(selected_sense=selected, ambiguity=ambiguity, reasons=reasons)


def _contains_phrase(q_norm: str, q_stem: str, phrase: str) -> bool:
    p_norm = normalize_text(phrase)
    if p_norm and p_norm in q_norm:
        return True
    p_stem = normalize_for_retrieval(phrase)
    if p_stem and p_stem in q_stem:
        return True
    p_tokens = [t for t in p_stem.split() if t]
    q_tokens = set(q_stem.split())
    return bool(p_tokens) and all(tok in q_tokens for tok in p_tokens)
