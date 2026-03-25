from __future__ import annotations

from typing import Any

from app.indexing.store import ArtifactStore
from app.services.json_review_storage import JsonReviewStorage
from app.services.review_pdf_apply_service import ReviewPdfApplyService


class ReviewWorkflowService:
    def __init__(self, store: ArtifactStore, storage: JsonReviewStorage, pdf_apply: ReviewPdfApplyService) -> None:
        self.store = store
        self.storage = storage
        self.pdf_apply = pdf_apply

    def accept_issue(self, issue_id: str, teacher_id: str, comment: str | None = None) -> dict[str, Any]:
        issue = self.storage.get_review_issue(issue_id)
        if not issue:
            raise ValueError(f"Issue not found: {issue_id}")
        decision = self.storage.create_review_decision(
            issue_id=issue_id,
            teacher_id=teacher_id,
            decision_type="accept",
            comment=comment,
        )
        self.storage.update_issue_status(issue["course_id"], issue_id, "accepted")
        apply_result = self.pdf_apply.apply_issue_to_pdf(
            course_id=issue["course_id"],
            issue_id=issue_id,
            teacher_id=teacher_id,
            decision_id=decision["decision_id"],
        )
        return {"decision": decision, "apply_result": apply_result.to_payload()}

    def edit_issue(self, issue_id: str, teacher_id: str, edited_text: str, comment: str | None = None) -> dict[str, Any]:
        issue = self.storage.get_review_issue(issue_id)
        if not issue:
            raise ValueError(f"Issue not found: {issue_id}")
        if not edited_text.strip():
            raise ValueError("edited_text must not be empty.")
        decision = self.storage.create_review_decision(
            issue_id=issue_id,
            teacher_id=teacher_id,
            decision_type="edit",
            edited_text=edited_text.strip(),
            comment=comment,
        )
        self.storage.update_issue_status(issue["course_id"], issue_id, "edited")
        apply_result = self.pdf_apply.apply_issue_to_pdf(
            course_id=issue["course_id"],
            issue_id=issue_id,
            teacher_id=teacher_id,
            applied_text_override=edited_text.strip(),
            decision_id=decision["decision_id"],
        )
        return {"decision": decision, "apply_result": apply_result.to_payload()}

    def reject_issue(self, issue_id: str, teacher_id: str, comment: str | None = None) -> dict[str, Any]:
        issue = self.storage.get_review_issue(issue_id)
        if not issue:
            raise ValueError(f"Issue not found: {issue_id}")
        decision = self.storage.create_review_decision(
            issue_id=issue_id,
            teacher_id=teacher_id,
            decision_type="reject",
            comment=comment,
        )
        self.storage.update_issue_status(issue["course_id"], issue_id, "rejected")
        return {"decision": decision, "issue_id": issue_id, "status": "rejected"}
