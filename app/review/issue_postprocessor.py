from __future__ import annotations

from collections import defaultdict
from typing import Any


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def postprocess_issues(raw_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in raw_issues if not item.get("drop_candidate")]
    deduped = _deduplicate(candidates)
    grouped = _group_by_claim(deduped)
    processed: list[dict[str, Any]] = []

    for _, group in grouped.items():
        kept = _suppress_weaker_biography(group)
        kept = _merge_related_outdated(kept)
        kept = _collapse_same_type(kept)
        processed.extend(kept)

    processed = _suppress_dominated_overlaps(processed)
    processed.sort(key=lambda item: (item.get("fragment_id", ""), item.get("created_at", "")))
    return processed


def _deduplicate(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int, str]] = set()
    for issue in issues:
        span = issue.get("claim_span") or [0, 0]
        key = (
            issue.get("fragment_id", ""),
            issue.get("issue_type", ""),
            int(span[0]),
            int(span[1]),
            issue.get("detected_text", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _group_by_claim(issues: list[dict[str, Any]]) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    buckets: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        span = issue.get("claim_span") or [0, 0]
        key = (issue.get("fragment_id", ""), int(span[0]), int(span[1]))
        buckets[key].append(issue)
    return buckets


def _suppress_weaker_biography(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reference_backed = [
        issue for issue in group if issue.get("issue_family") == "biography" and bool(issue.get("reference_backed"))
    ]
    if not reference_backed:
        return group
    primary_reference = max(reference_backed, key=lambda item: float(item.get("strength") or 0.0))
    suppressed_ids: list[str] = []
    out: list[dict[str, Any]] = []
    for issue in group:
        if issue.get("issue_family") == "biography" and not issue.get("reference_backed"):
            debug = issue.setdefault("debug", {})
            debug["postprocess"] = "suppressed_by_reference_backed_biography"
            suppressed_ids.append(str(issue.get("issue_id")))
            continue
        out.append(issue)
    if suppressed_ids:
        debug = primary_reference.setdefault("debug", {})
        debug["suppressed_issue_ids"] = suppressed_ids
    return out


def _merge_related_outdated(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outdated = [item for item in group if item.get("issue_family") == "outdated"]
    if len(outdated) < 2:
        return group
    primary = max(outdated, key=lambda item: float(item.get("strength") or 0.0))
    merged = dict(primary)
    merged["issue_type"] = "CURRENT_CLAIM_OUTDATED"
    merged["severity"] = _max_severity(outdated)
    merged["detected_text"] = "; ".join(sorted({item.get("detected_text", "") for item in outdated if item.get("detected_text")}))
    raw_evidence = [item.get("evidence", "") for item in outdated if item.get("evidence")]
    merged["evidence"] = ""
    merged["slot_updates"] = _collect_slot_updates(outdated)
    merged["suggestion"] = _build_unified_suggestion(merged.get("claim_text", ""), merged.get("claim_span", []), outdated)
    debug = merged.setdefault("debug", {})
    debug["merged_issue_ids"] = [item.get("issue_id") for item in outdated]
    debug["merged_raw_evidence"] = raw_evidence
    debug["postprocess"] = "merged_related_outdated_claim"
    keep_ids = {item.get("issue_id") for item in outdated}
    remaining = [item for item in group if item.get("issue_id") not in keep_ids]
    remaining.append(merged)
    return remaining


def _collapse_same_type(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}
    for issue in group:
        key = issue.get("issue_type", "")
        existing = bucket.get(key)
        if existing is None or float(issue.get("strength") or 0.0) > float(existing.get("strength") or 0.0):
            bucket[key] = issue
    return list(bucket.values())


def _max_severity(issues: list[dict[str, Any]]) -> str:
    return max((item.get("severity", "low") for item in issues), key=lambda sev: SEVERITY_RANK.get(sev, 0))


def _pick_best_suggestion(issues: list[dict[str, Any]]) -> str | None:
    ranked = sorted(issues, key=lambda item: float(item.get("strength") or 0.0), reverse=True)
    for item in ranked:
        suggestion = item.get("suggestion")
        if suggestion:
            return suggestion
    return None


def _collect_slot_updates(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for issue in issues:
        for slot in issue.get("slot_updates") or []:
            key = (int(slot.get("start", 0)), int(slot.get("end", 0)), str(slot.get("to", "")))
            if key in seen:
                continue
            seen.add(key)
            out.append(slot)
    return out


def _build_unified_suggestion(claim_text: str, claim_span: list[int], issues: list[dict[str, Any]]) -> str | None:
    if not claim_text:
        return _pick_best_suggestion(issues)
    slots: list[dict[str, Any]] = []
    for issue in issues:
        slots.extend(issue.get("slot_updates") or [])
    if not slots:
        return _pick_best_suggestion(issues)

    ordered = sorted(slots, key=lambda item: int(item.get("start", 0)), reverse=True)
    suggestion = claim_text
    claim_start = int(claim_span[0]) if len(claim_span) == 2 else 0
    for slot in ordered:
        rel_start = int(slot.get("start", 0)) - claim_start
        rel_end = int(slot.get("end", 0)) - claim_start
        replacement = str(slot.get("to", ""))
        if rel_start < 0 or rel_end > len(suggestion) or rel_start >= rel_end:
            continue
        if not _boundary_safe(suggestion, rel_start, rel_end):
            continue
        suggestion = f"{suggestion[:rel_start]}{replacement}{suggestion[rel_end:]}"
    return suggestion.strip() or None


def _boundary_safe(text: str, start: int, end: int) -> bool:
    if start < 0 or end > len(text) or start >= end:
        return False
    left_ok = start == 0 or not (_token(text[start - 1]) and _token(text[start]))
    right_ok = end == len(text) or not (_token(text[end - 1]) and _token(text[end]))
    return left_ok and right_ok


def _token(char: str) -> bool:
    return char.isalnum() or char in "._-"


def _suppress_dominated_overlaps(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for candidate in sorted(issues, key=lambda item: float(item.get("strength") or 0.0), reverse=True):
        dominated_by = _find_dominator(candidate, kept)
        if dominated_by is None:
            kept.append(candidate)
            continue
        debug = dominated_by.setdefault("debug", {})
        suppressed = debug.setdefault("suppressed_issue_ids", [])
        suppressed.append(candidate.get("issue_id"))
    return kept


def _find_dominator(candidate: dict[str, Any], existing: list[dict[str, Any]]) -> dict[str, Any] | None:
    cand_role = candidate.get("claim_role", "")
    cand_strength = float(candidate.get("strength") or 0.0)
    if cand_role != "ambiguous_claim" and cand_strength >= 0.65:
        return None
    for primary in existing:
        if primary.get("fragment_id") != candidate.get("fragment_id"):
            continue
        if not _overlap_or_adjacent(primary.get("claim_span"), candidate.get("claim_span")):
            continue
        primary_strength = float(primary.get("strength") or 0.0)
        if primary_strength < cand_strength + 0.15:
            continue
        if not _same_topic(primary, candidate):
            continue
        if primary.get("claim_role") == "current_state_claim" or primary.get("reference_backed") or primary.get(
            "issue_type"
        ) == "CURRENT_CLAIM_OUTDATED":
            return primary
    return None


def _overlap_or_adjacent(left_span: Any, right_span: Any) -> bool:
    if not left_span or not right_span:
        return False
    left_start, left_end = int(left_span[0]), int(left_span[1])
    right_start, right_end = int(right_span[0]), int(right_span[1])
    overlap = max(0, min(left_end, right_end) - max(left_start, right_start))
    if overlap > 0:
        return True
    gap = min(abs(left_end - right_start), abs(right_end - left_start))
    return gap <= 24


def _same_topic(primary: dict[str, Any], candidate: dict[str, Any]) -> bool:
    left_refs = set(primary.get("source_refs") or [])
    right_refs = set(candidate.get("source_refs") or [])
    if left_refs and right_refs and left_refs.intersection(right_refs):
        return True
    left_family = primary.get("issue_family")
    right_family = candidate.get("issue_family")
    return left_family == right_family
