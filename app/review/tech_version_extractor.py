from __future__ import annotations

import re

from app.review.context_models import TextSpan, VersionMention
from app.review.span_patch import expand_to_sentence

TECH_ALIASES: dict[str, list[str]] = {
    "Java": ["java"],
    "JDK": ["jdk"],
    "Spring Boot": ["spring boot"],
    "Spring": ["spring"],
    "Hibernate": ["hibernate"],
    "JUnit": ["junit"],
    "Maven": ["maven"],
    "Gradle": ["gradle"],
    "Jakarta EE": ["jakarta ee", "java ee", "j2ee"],
    "TLS": ["tls", "ssl"],
    "Python": ["python"],
}

VERSION_TOKEN_RE = re.compile(r"v?\d+(?:\.\d+){0,2}", re.IGNORECASE)
DIRECT_VERSION_CHAIN_RE = re.compile(
    r"^\s*(?:[\(\[\{]?\s*)?(?:[:\-—–]\s*)?(v?\d+(?:\.\d+){0,2})(?:\s*/\s*(v?\d+(?:\.\d+){0,2}))*",
    re.IGNORECASE,
)
CLAUSE_STOP_RE = re.compile(r"[,;\n!?]")

CURRENT_MARKER_RE = r"(?:актуаль\w*|текущ\w*|current|latest)"
VERSION_WORD_RE = r"(?:верси\w*|version)"
BRIDGE_RE = r"[\s\(\)\[\]{}\"'«»,:;\-—–]*"


def extract_technology_versions(text: str) -> list[VersionMention]:
    lowered = text.lower()
    alias_to_technology = _alias_to_technology_map()
    results: list[VersionMention] = []

    for alias_lc, technology in alias_to_technology.items():
        alias_re = re.escape(alias_lc)
        for alias_match in re.finditer(rf"(?<![\w-]){alias_re}(?![\w-])", lowered, re.IGNORECASE):
            tail = text[alias_match.end() :]
            stop_match = CLAUSE_STOP_RE.search(tail)
            segment = tail[: stop_match.start()] if stop_match else tail
            chain_match = DIRECT_VERSION_CHAIN_RE.search(segment)
            if not chain_match:
                continue
            chain_text = chain_match.group(0)
            base_offset = alias_match.end()
            for version_match in VERSION_TOKEN_RE.finditer(chain_text):
                results.append(
                    _build_mention(
                        text=text,
                        technology=technology,
                        alias=alias_lc,
                        alias_start=alias_match.start(),
                        alias_end=alias_match.end(),
                        version_start=base_offset + version_match.start(),
                        version_end=base_offset + version_match.end(),
                    )
                )

    results.extend(_extract_current_version_pattern_mentions(text, alias_to_technology))
    return _deduplicate_mentions(results)


def _extract_current_version_pattern_mentions(
    text: str,
    alias_to_technology: dict[str, str],
) -> list[VersionMention]:
    alias_pattern = "|".join(sorted((re.escape(alias) for alias in alias_to_technology.keys()), key=len, reverse=True))
    if not alias_pattern:
        return []

    patterns = [
        re.compile(
            rf"(?<![\w-])(?P<alias>{alias_pattern})(?![\w-])"
            rf"{BRIDGE_RE}(?P<marker>{CURRENT_MARKER_RE})"
            rf"(?:{BRIDGE_RE}(?:{VERSION_WORD_RE}))?"
            rf"{BRIDGE_RE}(?P<version>v?\d+(?:\.\d+){{0,2}})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<marker>{CURRENT_MARKER_RE})"
            rf"(?:{BRIDGE_RE}(?:{VERSION_WORD_RE}))?"
            rf"{BRIDGE_RE}(?:of{BRIDGE_RE}|для{BRIDGE_RE})?"
            rf"(?<![\w-])(?P<alias>{alias_pattern})(?![\w-])"
            rf"{BRIDGE_RE}(?P<version>v?\d+(?:\.\d+){{0,2}})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<marker>{CURRENT_MARKER_RE})"
            rf"{BRIDGE_RE}(?<![\w-])(?P<alias>{alias_pattern})(?![\w-])"
            rf"{BRIDGE_RE}(?:{VERSION_WORD_RE})"
            rf"{BRIDGE_RE}(?P<version>v?\d+(?:\.\d+){{0,2}})",
            re.IGNORECASE,
        ),
    ]

    results: list[VersionMention] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            alias_raw = (match.group("alias") or "").strip().lower()
            technology = alias_to_technology.get(alias_raw)
            if not technology:
                continue
            results.append(
                _build_mention(
                    text=text,
                    technology=technology,
                    alias=alias_raw,
                    alias_start=match.start("alias"),
                    alias_end=match.end("alias"),
                    version_start=match.start("version"),
                    version_end=match.end("version"),
                )
            )
    return results


def _build_mention(
    *,
    text: str,
    technology: str,
    alias: str,
    alias_start: int,
    alias_end: int,
    version_start: int,
    version_end: int,
) -> VersionMention:
    sentence_span = expand_to_sentence(text, alias_start, version_end)
    version = text[version_start:version_end].lstrip("vV")
    return VersionMention(
        technology=technology,
        version=version,
        matched_text=text[alias_start:version_end],
        alias=alias,
        alias_span=TextSpan(alias_start, alias_end),
        version_span=TextSpan(version_start, version_end),
        sentence_span=sentence_span,
        sentence_text=text[sentence_span.start : sentence_span.end],
    )


def _alias_to_technology_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for technology, aliases in TECH_ALIASES.items():
        for alias in aliases:
            key = alias.strip().lower()
            if key and key not in mapping:
                mapping[key] = technology
    return mapping


def _deduplicate_mentions(items: list[VersionMention]) -> list[VersionMention]:
    unique: list[VersionMention] = []
    seen: set[tuple[str, str, int, int]] = set()
    for item in items:
        key = (item.technology, item.version, item.alias_span.start, item.version_span.start)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
