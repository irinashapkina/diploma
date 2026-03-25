from __future__ import annotations

from dataclasses import dataclass
import re

from app.review.context_models import TextSpan
from app.review.span_patch import adjust_to_token_boundaries, expand_to_clause, expand_to_sentence

CURRENT_MARKERS = (
    "сейчас",
    "текущ",
    "актуаль",
    "на данный момент",
    "currently",
    "current",
    "latest",
    "as of",
)
HISTORICAL_MARKERS = (
    "истор",
    "раньше",
    "в ",
    "introduced",
    "released in",
    "historical",
    "retrospective",
)
ORIGIN_MARKERS = (
    "первая версия",
    "first version",
    "появил",
    "origin",
    "был создан",
    "was created",
    "initial release",
)
BIO_MARKERS = (
    "родился",
    "род.",
    "умер",
    "биограф",
    "born",
    "died",
)
ACADEMIC_MARKERS = (
    "учебный год",
    "semester",
    "семестр",
    "поток",
    "курс лекций",
    "кафедр",
)
EXAMPLE_MARKERS = (
    "например",
    "пример",
    "for example",
    "e.g.",
    "цитата",
    "quote",
)

YEAR_RANGE_RE = re.compile(r"\b\d{3,4}\s*[-–—]\s*\d{3,4}\b")
NAME_LIKE_RE = re.compile(r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’.\-]+\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’.\-]+")


@dataclass(slots=True)
class ClaimContext:
    claim_span: TextSpan
    claim_text: str
    role: str
    confidence: float
    triggers: list[str]


def extract_claim_context(text: str, start: int, end: int, hint: str | None = None) -> ClaimContext:
    sentence = expand_to_sentence(text, start, end)
    sentence_text = text[sentence.start : sentence.end]
    segments = _split_segments(sentence_text, sentence.start)
    selected = _pick_segment(segments, anchor_abs=start, hint=hint)
    claim_span = adjust_to_token_boundaries(text, selected)
    claim_span, claim_text = _trim_span_and_text(text, claim_span)
    if not claim_text:
        clause = expand_to_clause(text, start, end)
        claim_span = adjust_to_token_boundaries(text, clause)
        claim_span, claim_text = _trim_span_and_text(text, claim_span)
    role, confidence, triggers = classify_claim_role(claim_text, hint=hint)
    return ClaimContext(
        claim_span=claim_span,
        claim_text=claim_text,
        role=role,
        confidence=confidence,
        triggers=[*triggers, f"segment_span={claim_span.start}:{claim_span.end}"],
    )


def classify_claim_role(claim_text: str, hint: str | None = None) -> tuple[str, float, list[str]]:
    lowered = claim_text.lower()
    score = {
        "current_state_claim": 0,
        "historical_reference": 0,
        "origin_or_first_version": 0,
        "biography_fact": 0,
        "academic_metadata": 0,
        "example_or_quote": 0,
        "ambiguous_claim": 0,
    }
    triggers: list[str] = []

    def add_points(role: str, points: int, marker: str) -> None:
        score[role] += points
        triggers.append(f"{role}:{marker}")

    for marker in CURRENT_MARKERS:
        if marker in lowered:
            add_points("current_state_claim", 2, marker)
    for marker in HISTORICAL_MARKERS:
        if marker in lowered:
            add_points("historical_reference", 2, marker)
    for marker in ORIGIN_MARKERS:
        if marker in lowered:
            add_points("origin_or_first_version", 3, marker)
    for marker in BIO_MARKERS:
        if marker in lowered:
            add_points("biography_fact", 2, marker)
    for marker in ACADEMIC_MARKERS:
        if marker in lowered:
            add_points("academic_metadata", 3, marker)
    for marker in EXAMPLE_MARKERS:
        if marker in lowered:
            add_points("example_or_quote", 2, marker)

    if YEAR_RANGE_RE.search(claim_text) and NAME_LIKE_RE.search(claim_text):
        add_points("biography_fact", 4, "name+year-range")
    if "\"" in claim_text or "«" in claim_text:
        add_points("example_or_quote", 1, "quotes")
    if hint == "biography":
        add_points("biography_fact", 2, "hint:biography")
    if hint == "date":
        add_points("academic_metadata", 1, "hint:date")
    if hint == "version":
        add_points("current_state_claim", 1, "hint:version")

    ranked = sorted(score.items(), key=lambda item: item[1], reverse=True)
    best_role, best_score = ranked[0]
    second_score = ranked[1][1]

    if best_score == 0:
        return "ambiguous_claim", 0.45, ["no-strong-markers"]
    if best_score - second_score <= 1 and best_role not in {"biography_fact", "academic_metadata"}:
        return "ambiguous_claim", 0.52, triggers

    confidence = min(0.97, 0.5 + best_score * 0.09)
    return best_role, confidence, triggers


def is_current_state_role(role: str) -> bool:
    return role == "current_state_claim"


def is_reviewable_current_role(role: str) -> bool:
    return role in {"current_state_claim", "ambiguous_claim"}


def _split_segments(sentence_text: str, absolute_start: int) -> list[TextSpan]:
    spans: list[TextSpan] = []
    local_start = 0
    for idx, char in enumerate(sentence_text):
        if char not in ",;":
            continue
        if idx > local_start:
            spans.append(TextSpan(absolute_start + local_start, absolute_start + idx))
        local_start = idx + 1
    if local_start < len(sentence_text):
        spans.append(TextSpan(absolute_start + local_start, absolute_start + len(sentence_text)))
    return [span for span in spans if span.end - span.start >= 4]


def _pick_segment(segments: list[TextSpan], anchor_abs: int, hint: str | None = None) -> TextSpan:
    if not segments:
        return TextSpan(anchor_abs, anchor_abs)
    containing = [span for span in segments if span.start <= anchor_abs <= span.end]
    if containing:
        return containing[0]
    return segments[0]


def _trim_span_and_text(text: str, span: TextSpan) -> tuple[TextSpan, str]:
    start, end = span.start, span.end
    while start < end and text[start] in " ,;:":
        start += 1
    while end > start and text[end - 1] in " ,;:":
        end -= 1
    return TextSpan(start, end), text[start:end]
