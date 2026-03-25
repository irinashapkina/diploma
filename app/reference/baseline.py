from __future__ import annotations

from dataclasses import asdict

from app.reference.fact_models import MergedTechnologyBaseline


def merge_technology_snapshots(technology_name: str, snapshots: list[dict]) -> dict | None:
    if not snapshots:
        return None
    ranked = sorted(snapshots, key=_snapshot_rank, reverse=True)
    best = ranked[0]
    best_fact = best.get("fact", {})

    deprecated_versions: list[str] = []
    for item in ranked:
        deprecated_versions.extend(item.get("fact", {}).get("deprecated_versions") or [])

    merged = MergedTechnologyBaseline(
        technology_name=technology_name,
        current_version=_best_field_by_rank(ranked, ("current_version", "recommended_version", "latest_lts_version")),
        current_release_year=best_fact.get("current_release_year"),
        current_label=best_fact.get("current_label"),
        recommended_version=_best_field_by_rank(
            ranked,
            ("recommended_version", "current_version", "latest_lts_version"),
        ),
        latest_lts_version=_best_field_by_rank(ranked, ("latest_lts_version", "recommended_version")),
        min_supported_version=_min_version_field(ranked, ("min_supported_version",)),
        deprecated_versions=sorted(set(deprecated_versions)),
        support_status=best_fact.get("support_status"),
        source_title=best.get("source_name"),
        source_url=best.get("source_url"),
        parser_name=best_fact.get("parser_name"),
        confidence=float(best_fact.get("confidence") or 0.0),
        fact_kind=best_fact.get("fact_kind") or "release_baseline",
    )
    return asdict(merged)


def format_baseline_evidence_text(baseline: MergedTechnologyBaseline) -> str:
    parts: list[str] = []
    if baseline.current_label and baseline.current_version:
        parts.append(f"Актуальный {baseline.current_label}-релиз {baseline.technology_name} — {baseline.current_version}")
    elif baseline.current_version:
        parts.append(f"Актуальная версия {baseline.technology_name} — {baseline.current_version}")
    if baseline.current_release_year:
        parts.append(f"релиз: {baseline.current_release_year}")
    if baseline.latest_lts_version and baseline.latest_lts_version != baseline.current_version:
        parts.append(f"LTS: {baseline.latest_lts_version}")
    if baseline.support_status:
        parts.append(baseline.support_status)
    return "; ".join(parts)


def _snapshot_rank(snapshot: dict) -> tuple[float, int]:
    fact = snapshot.get("fact", {})
    confidence = float(fact.get("confidence") or 0.0)
    priority = int(fact.get("source_priority") or 0)
    return confidence, priority


def _best_field_by_rank(snapshots: list[dict], keys: tuple[str, ...]) -> str | None:
    for snapshot in snapshots:
        fact = snapshot.get("fact", {})
        for key in keys:
            candidate = fact.get(key)
            if candidate:
                return str(candidate)
    return None


def _min_version_field(snapshots: list[dict], keys: tuple[str, ...]) -> str | None:
    values: list[str] = []
    for snapshot in snapshots:
        fact = snapshot.get("fact", {})
        for key in keys:
            candidate = fact.get(key)
            if candidate:
                values.append(str(candidate))
    if not values:
        return None
    return min(values, key=_version_tuple)


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value).replace("-", ".").split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
    return tuple(parts or [0])
