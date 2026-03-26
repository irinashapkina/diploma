from __future__ import annotations

from app.review.tech_version_extractor import extract_technology_versions
from app.services.java_material_review_service import JavaMaterialReviewService


class _DummyStore:
    pass


class _DummyStorage:
    pass


def test_extract_versions_from_compact_current_claim_forms() -> None:
    samples = [
        "Java (актуальная версия 21)",
        "Java — актуальная версия 21",
        "Текущая версия Java: 21",
        "Актуальная версия Java — 21",
        "Current version: Java 21",
        "Latest Java version 21",
        "Java\n(актуальная версия 21)",
    ]
    for sample in samples:
        mentions = extract_technology_versions(sample)
        assert any(m.technology == "Java" and m.version == "21" for m in mentions), sample


def test_scan_versions_creates_outdated_issue_for_compact_current_claim() -> None:
    service = JavaMaterialReviewService(store=_DummyStore(), storage=_DummyStorage())  # type: ignore[arg-type]
    text = "Java (актуальная версия 21)"
    issues = service._scan_versions(
        course_id="c1",
        fragment_id="doc_p1",
        text=text,
        normalized_text=text.lower(),
        baseline={"Java": {"recommended_version": "26"}},
    )
    assert issues
    issue = issues[0]
    assert issue["issue_type"] == "TECH_VERSION_OUTDATED"
    assert issue["claim_role"] in {"current_state_claim", "ambiguous_claim"}
    assert "26" in (issue.get("suggestion") or "")
    assert "актуальная версия" in (issue.get("suggestion") or "").lower()


def test_scan_versions_keeps_historical_mentions_ignored() -> None:
    service = JavaMaterialReviewService(store=_DummyStore(), storage=_DummyStorage())  # type: ignore[arg-type]
    text = "Java 21 вышла в 2023 году как новый LTS-релиз."
    issues = service._scan_versions(
        course_id="c1",
        fragment_id="doc_p1",
        text=text,
        normalized_text=text.lower(),
        baseline={"Java": {"recommended_version": "26"}},
    )
    assert issues == []
