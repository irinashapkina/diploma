from __future__ import annotations

from datetime import datetime, timezone
import re
import uuid
from typing import Any

from app.config.settings import settings
from app.indexing.store import ArtifactStore
from app.reference.person_facts import PersonLifeDatesResolver
from app.review.claim_classifier import extract_claim_context, is_current_state_role, is_reviewable_current_role
from app.review.context_classifier import classify_term_mention, classify_version_mention
from app.review.context_models import PolicyAction, TermMention, TextSpan
from app.review.date_patterns import ACADEMIC_YEAR_PATTERN, FLOW_PATTERN, SEMESTER_PATTERN, YEAR_PATTERN
from app.review.evidence_renderer import render_final_evidence
from app.review.issue_postprocessor import postprocess_issues
from app.review.java_terms import SUSPICIOUS_JAVA_TERMS
from app.review.llm_assistant import ReviewLLMAssistant
from app.review.person_life_dates import extract_person_life_dates, render_person_life_dates
from app.review.suggestion_validator import validate_suggestion
from app.review.tech_version_extractor import extract_technology_versions
from app.review.text_normalizer import normalize_confusable_text
from app.review.version_patterns import VERSION_PATTERNS
from app.services.json_review_storage import JsonReviewStorage

CURRENT_YEAR = datetime.now(timezone.utc).year
PERSON_YEAR_RANGE_RE = re.compile(r"\(\s*(?P<birth>\d{3,4})\s*[-–—]\s*(?P<death>\d{3,4})\s*\)")


class JavaMaterialReviewService:
    def __init__(self, store: ArtifactStore, storage: JsonReviewStorage) -> None:
        self.store = store
        self.storage = storage
        self.person_resolver = PersonLifeDatesResolver()
        self.llm = ReviewLLMAssistant()

    def scan_course(self, course_id: str, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
        course = self.store.get_course(course_id)
        if course is None:
            raise ValueError(f"Course not found: {course_id}")

        baseline = baseline or {}
        pages = self.store.list_pages(course_id=course_id)
        raw_issues: list[dict[str, Any]] = []

        for page in pages:
            fragment_text = page.merged_text or page.ocr_text_clean or page.pdf_text_raw or ""
            if not fragment_text.strip():
                continue
            normalized_text = normalize_confusable_text(fragment_text)
            fragment_id = page.page_id

            raw_issues.extend(
                self._scan_dates(
                    course_id=course_id,
                    fragment_id=fragment_id,
                    text=fragment_text,
                    normalized_text=normalized_text,
                    course_year_label=course.year_label,
                )
            )
            raw_issues.extend(self._scan_terms(course_id, fragment_id, fragment_text, normalized_text))
            raw_issues.extend(self._scan_versions(course_id, fragment_id, fragment_text, normalized_text, baseline))
            raw_issues.extend(self._scan_person_dates(course_id, fragment_id, fragment_text, normalized_text))

        processed_issues = postprocess_issues(raw_issues)
        processed_issues = self._render_final_evidence(processed_issues)
        processed_issues = self._llm_refine_user_facing(processed_issues)
        suggestions = [
            {
                "issue_id": issue["issue_id"],
                "course_id": issue["course_id"],
                "fragment_id": issue["fragment_id"],
                "suggested_text": issue["suggestion"],
                "status": "draft",
                "created_at": issue["created_at"],
            }
            for issue in processed_issues
            if issue.get("suggestion")
        ]

        scan_id = str(uuid.uuid4())
        summary = {
            "course_id": course_id,
            "scan_id": scan_id,
            "total_pages": len(pages),
            "raw_candidates_total": len(raw_issues),
            "issues_total": len(processed_issues),
            "suggestions_total": len(suggestions),
        }
        self.storage.save_scan_run(course_id, scan_id, summary, processed_issues, suggestions)
        return summary

    def _scan_dates(
        self,
        course_id: str,
        fragment_id: str,
        text: str,
        normalized_text: str,
        course_year_label: str,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []

        for match in ACADEMIC_YEAR_PATTERN.finditer(text):
            claim = extract_claim_context(text, match.start(), match.end(), hint="date")
            if claim.role not in {"academic_metadata", "current_state_claim", "ambiguous_claim"}:
                continue
            year_value = match.group(0)
            if year_value == course_year_label:
                continue
            suggested_claim = claim.claim_text.replace(year_value, course_year_label, 1)
            issues.append(
                self._issue(
                    course_id=course_id,
                    fragment_id=fragment_id,
                    issue_type="DATE_ACADEMIC_YEAR_MISMATCH",
                    issue_family="metadata",
                    severity="medium",
                    detected_text=year_value,
                    normalized_text=normalized_text,
                    evidence=f"Найден учебный год {year_value}, курс сейчас размечен как {course_year_label}.",
                    claim=claim,
                    suggestion=suggested_claim,
                    strength=0.74,
                    slot_updates=[
                        {
                            "kind": "academic_year",
                            "start": match.start(),
                            "end": match.end(),
                            "from": year_value,
                            "to": course_year_label,
                        }
                    ],
                )
            )

        for match in YEAR_PATTERN.finditer(text):
            year = int(match.group(0))
            if year > CURRENT_YEAR:
                continue
            claim = extract_claim_context(text, match.start(), match.end(), hint="date")
            if not is_reviewable_current_role(claim.role):
                continue
            if year > CURRENT_YEAR - 2:
                continue
            severity = "high" if is_current_state_role(claim.role) else "low"
            issues.append(
                self._issue(
                    course_id=course_id,
                    fragment_id=fragment_id,
                    issue_type="DATE_OUTDATED_REFERENCE",
                    issue_family="outdated",
                    severity=severity,
                    detected_text=match.group(0),
                    normalized_text=normalized_text,
                    evidence=f"Год {year} используется в claim-роли {claim.role}, похожей на current-state утверждение.",
                    claim=claim,
                    suggestion=None,
                    strength=0.82 if severity == "high" else 0.58,
                    slot_updates=[
                        {
                            "kind": "year",
                            "start": match.start(),
                            "end": match.end(),
                            "from": match.group(0),
                            "to": str(CURRENT_YEAR),
                        }
                    ],
                )
            )

        for pattern, issue_type in ((FLOW_PATTERN, "DATE_OUTDATED_FLOW"), (SEMESTER_PATTERN, "DATE_OUTDATED_SEMESTER")):
            for match in pattern.finditer(text):
                claim = extract_claim_context(text, match.start(), match.end(), hint="date")
                if claim.role not in {"academic_metadata", "ambiguous_claim"}:
                    continue
                if str(CURRENT_YEAR) in match.group(0):
                    continue
                issues.append(
                    self._issue(
                        course_id=course_id,
                        fragment_id=fragment_id,
                        issue_type=issue_type,
                        issue_family="metadata",
                        severity="medium",
                        detected_text=match.group(0),
                        normalized_text=normalized_text,
                        evidence=f"Academic metadata выглядит устаревшей: {match.group(0)}.",
                        claim=claim,
                        suggestion=None,
                        strength=0.68,
                    )
                )
        return issues

    def _scan_terms(self, course_id: str, fragment_id: str, text: str, normalized_text: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for term, meta in SUSPICIOUS_JAVA_TERMS.items():
            for match in re.finditer(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.IGNORECASE):
                mention = TermMention(
                    term=term,
                    technology=meta.get("technology", "Java"),
                    matched_text=match.group(0),
                    term_span=TextSpan(match.start(), match.end()),
                    sentence_span=TextSpan(max(0, match.start() - 80), min(len(text), match.end() + 120)),
                    sentence_text=text[max(0, match.start() - 80) : min(len(text), match.end() + 120)],
                    preferred_term=meta.get("preferred_term"),
                )
                cls = classify_term_mention(text, mention)
                if cls.policy_action not in (PolicyAction.create_issue, PolicyAction.review_only):
                    continue

                claim = extract_claim_context(text, match.start(), match.end(), hint="term")
                suggestion = None
                if mention.preferred_term:
                    suggestion = _replace_inside_claim(
                        claim.claim_text,
                        claim_span=claim.claim_span,
                        target_span=mention.term_span,
                        replacement=mention.preferred_term,
                    )

                issues.append(
                    self._issue(
                        course_id=course_id,
                        fragment_id=fragment_id,
                        issue_type=meta.get("issue_type", "TERM_OUTDATED"),
                        issue_family="terminology",
                        severity="medium" if cls.policy_action == PolicyAction.create_issue else "low",
                        detected_text=match.group(0),
                        normalized_text=normalized_text,
                        evidence=cls.reason,
                        claim=claim,
                        suggestion=suggestion,
                        source_refs=[meta.get("technology", "Java")],
                        strength=cls.confidence,
                    )
                )
        return issues

    def _scan_versions(
        self,
        course_id: str,
        fragment_id: str,
        text: str,
        normalized_text: str,
        baseline: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []

        for mention in extract_technology_versions(text):
            recommended = _pick_baseline_version(baseline, mention.technology)
            if not recommended or not _version_less_than(mention.version, recommended):
                continue

            claim = extract_claim_context(text, mention.alias_span.start, mention.version_span.end, hint="version")
            classification = classify_version_mention(text, mention)
            if classification.policy_action == PolicyAction.ignore:
                continue
            if not is_reviewable_current_role(claim.role):
                continue

            severity = "high" if is_current_state_role(claim.role) else "medium"
            replacement = f"{mention.technology} {recommended}"
            suggestion = _replace_inside_claim(
                claim.claim_text,
                claim_span=claim.claim_span,
                target_span=TextSpan(mention.alias_span.start, mention.version_span.end),
                replacement=replacement,
            )
            evidence = (
                f"{classification.reason} Claim-role={claim.role}; baseline рекомендует {recommended} "
                f"вместо {mention.version}."
            )
            issues.append(
                self._issue(
                    course_id=course_id,
                    fragment_id=fragment_id,
                    issue_type="TECH_VERSION_OUTDATED",
                    issue_family="outdated",
                    severity=severity,
                    detected_text=mention.matched_text,
                    normalized_text=normalized_text,
                    evidence=evidence,
                    claim=claim,
                    suggestion=suggestion,
                    source_refs=[mention.technology],
                    strength=max(classification.confidence, claim.confidence),
                    slot_updates=[
                        {
                            "kind": "version",
                            "start": mention.alias_span.start,
                            "end": mention.version_span.end,
                            "from": mention.matched_text,
                            "to": replacement,
                        }
                    ],
                )
            )

        for technology, pattern, issue_type in VERSION_PATTERNS:
            for match in pattern.finditer(text):
                claim = extract_claim_context(text, match.start(), match.end(), hint="version")
                if not is_reviewable_current_role(claim.role):
                    continue
                issues.append(
                    self._issue(
                        course_id=course_id,
                        fragment_id=fragment_id,
                        issue_type=issue_type,
                        issue_family="outdated",
                        severity="medium" if claim.role == "ambiguous_claim" else "high",
                        detected_text=match.group(0),
                        normalized_text=normalized_text,
                        evidence=f"Версионный паттерн требует проверки в claim-роли {claim.role}.",
                        claim=claim,
                        suggestion=None,
                        source_refs=[technology],
                        strength=0.63,
                    )
                )
        return issues

    def _scan_person_dates(self, course_id: str, fragment_id: str, text: str, normalized_text: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        seen_spans: set[tuple[int, int]] = set()

        for mention in extract_person_life_dates(text):
            seen_spans.add((mention.start, mention.end))
            claim = extract_claim_context(text, mention.start, mention.end, hint="biography")
            ref = self.person_resolver.resolve(mention.person_name)

            if ref:
                suggested_dates = render_person_life_dates(mention, ref.birth_year, ref.death_year, ref.is_living)
                if suggested_dates and suggested_dates != mention.matched_text:
                    suggestion = _replace_inside_claim(
                        claim.claim_text,
                        claim_span=claim.claim_span,
                        target_span=TextSpan(mention.start, mention.end),
                        replacement=suggested_dates,
                    )
                    issues.append(
                        self._issue(
                            course_id=course_id,
                            fragment_id=fragment_id,
                            issue_type="PERSON_DATES_INCORRECT",
                            issue_family="biography",
                            severity="high",
                            detected_text=mention.matched_text,
                            normalized_text=normalized_text,
                            evidence=f"Reference contradiction for {mention.person_name}: {ref.formatted_life_dates}.",
                            claim=claim,
                            suggestion=suggestion,
                            source_refs=[ref.source_url],
                            reference_backed=True,
                            strength=max(ref.confidence, claim.confidence),
                        )
                    )

            if mention.death_year and mention.death_year > CURRENT_YEAR:
                issues.append(
                    self._issue(
                        course_id=course_id,
                        fragment_id=fragment_id,
                        issue_type="PERSON_DATES_FUTURE_DEATH_YEAR",
                        issue_family="biography",
                        severity="medium",
                        detected_text=mention.matched_text,
                        normalized_text=normalized_text,
                        evidence=f"Heuristic: year-of-death {mention.death_year} is in the future.",
                        claim=claim,
                        suggestion=None,
                        reference_backed=False,
                        strength=0.52,
                    )
                )

        for match in PERSON_YEAR_RANGE_RE.finditer(text):
            start, end = match.start(), match.end()
            if any(span_start <= start <= span_end for span_start, span_end in seen_spans):
                continue
            birth = int(match.group("birth"))
            death = int(match.group("death"))
            if death <= CURRENT_YEAR:
                continue
            claim = extract_claim_context(text, start, end, hint="biography")
            issues.append(
                self._issue(
                    course_id=course_id,
                    fragment_id=fragment_id,
                    issue_type="PERSON_DATES_FUTURE_DEATH_YEAR",
                    issue_family="biography",
                    severity="low",
                    detected_text=match.group(0),
                    normalized_text=normalized_text,
                    evidence=f"Heuristic biography check: suspicious range {birth}-{death}.",
                    claim=claim,
                    suggestion=None,
                    reference_backed=False,
                    strength=0.45,
                )
            )

        return issues

    def _issue(
        self,
        course_id: str,
        fragment_id: str,
        issue_type: str,
        issue_family: str,
        severity: str,
        detected_text: str,
        normalized_text: str,
        evidence: str,
        claim,
        suggestion: str | None,
        source_refs: list[str] | None = None,
        reference_backed: bool = False,
        strength: float = 0.5,
        slot_updates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        role = claim.role
        claim_confidence = claim.confidence
        llm_debug: dict[str, Any] = {}
        drop_candidate = False
        if (
            self.llm.enabled
            and role == "ambiguous_claim"
            and claim_confidence < settings.review_llm_triage_claim_confidence_lt
            and issue_family in {"outdated", "metadata", "terminology"}
        ):
            triage_payload = {
                "issue_type": issue_type,
                "issue_family": issue_family,
                "claim_text": claim.claim_text,
                "claim_role_deterministic": role,
                "claim_confidence_deterministic": round(claim_confidence, 3),
                "detected_text": detected_text,
                "evidence_raw": evidence,
                "source_refs": source_refs or [],
            }
            triage = self.llm.triage_claim(triage_payload)
            if triage:
                role = triage["role"]
                claim_confidence = triage["confidence"]
                drop_candidate = not triage["should_create_issue"]
                llm_debug = {
                    "triage_used": True,
                    "triage_prompt_version": triage.get("prompt_version"),
                    "triage_reasoning": triage.get("reasoning_short"),
                    "triage_should_create_issue": triage["should_create_issue"],
                    "triage_role": triage["role"],
                    "triage_confidence": triage["confidence"],
                }
            else:
                llm_debug = {"triage_used": True, "triage_fallback": "invalid_or_unavailable"}

        validated_suggestion = _validate_claim_suggestion(claim.claim_text, suggestion)
        return {
            "issue_id": str(uuid.uuid4()),
            "course_id": course_id,
            "fragment_id": fragment_id,
            "issue_type": issue_type,
            "issue_family": issue_family,
            "severity": severity,
            "detected_text": detected_text,
            "normalized_text": normalized_text,
            "evidence": evidence,
            "suggestion": validated_suggestion,
            "source_refs": source_refs or [],
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "claim_span": claim.claim_span.as_list(),
            "claim_text": claim.claim_text,
            "claim_role": role,
            "claim_confidence": round(claim_confidence, 3),
            "reference_backed": reference_backed,
            "strength": round(float(strength), 3),
            "slot_updates": slot_updates or [],
            "drop_candidate": drop_candidate,
            "debug": {"claim_triggers": claim.triggers, "llm": llm_debug},
        }

    def _llm_refine_user_facing(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.llm.enabled:
            for issue in issues:
                debug = issue.setdefault("debug", {})
                debug.setdefault("llm", {})
                debug["llm"]["enabled"] = False
                debug["llm"]["fallback"] = "review_llm_enabled=false"
            return issues
        for issue in issues:
            debug = issue.setdefault("debug", {})
            llm_debug = debug.setdefault("llm", {})
            evidence_payload = {
                "issue_type": issue.get("issue_type"),
                "issue_family": issue.get("issue_family"),
                "severity": issue.get("severity"),
                "claim_text": issue.get("claim_text"),
                "claim_role": issue.get("claim_role"),
                "detected_text": issue.get("detected_text"),
                "slot_updates": issue.get("slot_updates") or [],
                "source_refs": issue.get("source_refs") or [],
                "reference_backed": bool(issue.get("reference_backed")),
                "evidence_raw": issue.get("evidence"),
            }
            should_refine_evidence = issue.get("issue_type") in {
                "CURRENT_CLAIM_OUTDATED",
                "PERSON_DATES_INCORRECT",
            } or issue.get("claim_role") == "ambiguous_claim"
            if should_refine_evidence:
                rendered = self.llm.render_evidence(evidence_payload)
                if rendered and rendered.get("evidence_text"):
                    issue["evidence"] = rendered["evidence_text"]
                    llm_debug["evidence_used"] = True
                    llm_debug["evidence_prompt_version"] = rendered.get("prompt_version")
                else:
                    llm_debug["evidence_fallback"] = "invalid_or_unavailable"

            should_refine_suggestion = bool(issue.get("slot_updates")) and (
                issue.get("issue_type") == "CURRENT_CLAIM_OUTDATED" or issue.get("suggestion") is None
            )
            if not should_refine_suggestion:
                continue
            suggestion_payload = {
                "claim_text": issue.get("claim_text"),
                "issue_type": issue.get("issue_type"),
                "slot_updates": issue.get("slot_updates") or [],
                "deterministic_suggestion": issue.get("suggestion"),
                "constraints": {
                    "local_only": True,
                    "max_length": 260,
                    "preserve_meaning_outside_slots": True,
                },
            }
            rendered = self.llm.render_suggestion(suggestion_payload)
            if not rendered:
                llm_debug["suggestion_fallback"] = "invalid_or_unavailable"
                continue
            candidate = _validate_claim_suggestion(issue.get("claim_text", ""), rendered.get("replacement_text"))
            if not candidate:
                llm_debug["suggestion_fallback"] = "validation_failed"
                continue
            issue["suggestion"] = candidate
            llm_debug["suggestion_used"] = True
            llm_debug["suggestion_prompt_version"] = rendered.get("prompt_version")
            llm_debug["suggestion_confidence"] = rendered.get("confidence")
            llm_debug["suggestion_notes"] = rendered.get("notes")
        return issues

    def _render_final_evidence(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for issue in issues:
            debug = issue.setdefault("debug", {})
            raw_evidence = issue.get("evidence", "")
            debug["internal_evidence"] = raw_evidence
            issue["evidence"] = render_final_evidence(issue)
            debug["final_evidence_renderer"] = "deterministic-v1"
        return issues


def _pick_baseline_version(baseline: dict[str, Any], technology: str) -> str | None:
    item = baseline.get(technology)
    if not item:
        return None
    return item.get("recommended_version") or item.get("current_version") or item.get("latest_lts_version")


def _version_less_than(left: str, right: str) -> bool:
    return _version_key(left) < _version_key(right)


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in value.replace("v", "").split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
    return tuple(parts or [0])


def _replace_inside_claim(claim_text: str, claim_span: TextSpan, target_span: TextSpan, replacement: str) -> str:
    rel_start = max(0, target_span.start - claim_span.start)
    rel_end = min(len(claim_text), target_span.end - claim_span.start)
    if rel_start >= rel_end:
        return replacement
    return f"{claim_text[:rel_start]}{replacement}{claim_text[rel_end:]}"


def _validate_claim_suggestion(original_claim: str, suggested_claim: str | None) -> str | None:
    if not suggested_claim:
        return None
    if len(original_claim) > 420:
        return None
    validation = validate_suggestion(original_claim, suggested_claim, mode="REWRITE_LOCAL")
    if not validation.accepted:
        return None
    return suggested_claim.strip()
