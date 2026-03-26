from __future__ import annotations

from app.review.evidence_renderer import render_final_evidence
from app.services.java_material_review_service import JavaMaterialReviewService


def test_tech_version_outdated_is_human_friendly() -> None:
    issue = {
        "issue_type": "TECH_VERSION_OUTDATED",
        "issue_family": "outdated",
        "claim_text": "Java (актуальная версия 21)",
        "source_refs": ["Java"],
        "slot_updates": [{"from": "21", "to": "26"}],
        "evidence": "Упоминание Java 21 находится внутри current-status. Claim-role=current_state_claim.",
    }
    text = render_final_evidence(issue)
    assert "устаревш" in text.lower()
    assert "Java" in text
    assert "21" in text and "26" in text
    assert "Claim-role" not in text
    assert "current-status" not in text


def test_default_renderer_sanitizes_technical_tokens() -> None:
    issue = {
        "issue_type": "SOME_OTHER",
        "issue_family": "unknown",
        "evidence": "Claim-role=current_state_claim; baseline рекомендует 26 вместо 21.",
    }
    text = render_final_evidence(issue)
    assert "Claim-role" not in text
    assert "current_state_claim" not in text


class _DummyStore:
    pass


class _DummyStorage:
    pass


class _FakeLLM:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def render_evidence(self, payload):  # noqa: ANN001
        self.calls.append(payload)
        return {"evidence_text": "Короткая пользовательская причина.", "prompt_version": "test"}

    def render_suggestion(self, payload):  # noqa: ANN001
        return None


def test_llm_refine_evidence_applies_to_tech_version_issue() -> None:
    service = JavaMaterialReviewService(store=_DummyStore(), storage=_DummyStorage())  # type: ignore[arg-type]
    fake = _FakeLLM()
    service.llm = fake  # type: ignore[assignment]
    issues = [
        {
            "issue_id": "1",
            "issue_type": "TECH_VERSION_OUTDATED",
            "issue_family": "outdated",
            "severity": "high",
            "claim_text": "Java (актуальная версия 21)",
            "claim_role": "current_state_claim",
            "detected_text": "Java 21",
            "slot_updates": [{"from": "21", "to": "26"}],
            "source_refs": ["Java"],
            "reference_backed": False,
            "evidence": "В материале указана устаревшая версия Java.",
            "suggestion": "Java (актуальная версия 26)",
            "debug": {},
        }
    ]
    out = service._llm_refine_user_facing(issues)
    assert out[0]["evidence"] == "Короткая пользовательская причина."
    assert fake.calls, "LLM render_evidence was not called for TECH_VERSION_OUTDATED"
