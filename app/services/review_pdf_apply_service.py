from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import uuid
from typing import Any

import fitz

from app.config.settings import settings
from app.db.models import DocumentDB, MaterialRevisionDB, PageDB, ReviewIssueDB
from app.db.session import SessionLocal
from app.indexing.index_manager import IndexManager
from app.indexing.store import ArtifactStore
from app.services.json_review_storage import JsonReviewStorage

logger = logging.getLogger(__name__)

LOCAL_APPLY_ISSUE_TYPES = {
    "DATE_ACADEMIC_YEAR_MISMATCH",
    "PERSON_DATES_INCORRECT",
    "CURRENT_CLAIM_OUTDATED",
}


@dataclass(slots=True)
class ApplyResult:
    apply_id: str
    course_id: str
    issue_id: str
    status: str
    mode_used: str
    fallback_used: bool
    message: str
    updated_pdf_path: str | None
    source_pdf_path: str | None
    page_number: int | None
    fragment_id: str | None
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "apply_id": self.apply_id,
            "course_id": self.course_id,
            "issue_id": self.issue_id,
            "status": self.status,
            "mode_used": self.mode_used,
            "fallback_used": self.fallback_used,
            "message": self.message,
            "updated_pdf_path": self.updated_pdf_path,
            "source_pdf_path": self.source_pdf_path,
            "page_number": self.page_number,
            "fragment_id": self.fragment_id,
            "created_at": self.created_at,
        }


class ReviewPdfApplyService:
    def __init__(self, store: ArtifactStore, storage: JsonReviewStorage) -> None:
        self.store = store
        self.storage = storage
        self.index_manager = IndexManager(store=store)

    def apply_issue_to_pdf(
        self,
        course_id: str,
        issue_id: str,
        teacher_id: str | None = None,
        applied_text_override: str | None = None,
        decision_id: str | None = None,
    ) -> ApplyResult:
        issue = self.storage.get_review_issue(issue_id)
        if issue is None:
            raise ValueError(f"Issue not found: {issue_id}")
        if issue.get("course_id") != course_id:
            raise ValueError("Issue does not belong to requested course.")

        fragment_id = str(issue.get("fragment_id") or "")
        mapping = _parse_fragment_id(fragment_id)
        if mapping is None:
            return self._fallback_only(course_id, issue_id, issue, "Невозможно связать issue с page/document.")
        document_id, page_number = mapping

        document = self.store.get_document(document_id)
        if document is None:
            return self._fallback_only(course_id, issue_id, issue, "Document для issue не найден.")

        source_pdf = Path(document.source_pdf)
        if not source_pdf.exists():
            return self._fallback_only(course_id, issue_id, issue, "Исходный PDF не найден на диске.")

        suggestion = str(applied_text_override or issue.get("suggestion") or "").strip()
        applicability = self._is_locally_applicable(issue, suggestion)
        mode = "annotation_only"
        fallback_used = True
        message = "Применен fallback annotation mode."
        updated_pdf_path: Path | None = None

        try:
            with fitz.open(source_pdf) as pdf:
                page_index = max(0, page_number - 1)
                if page_index >= len(pdf):
                    raise ValueError("Page number out of range.")
                page = pdf[page_index]
                updated_pdf_path = self._build_output_path(course_id, document_id)
                updated_pdf_path.parent.mkdir(parents=True, exist_ok=True)

                if applicability:
                    replaced = self._try_replace_on_page(page, issue, suggestion)
                    if replaced == "direct_replace":
                        mode = "direct_replace"
                        fallback_used = False
                        message = "Локальная замена в PDF выполнена."
                    elif replaced == "overlay_replace":
                        mode = "overlay_replace"
                        fallback_used = False
                        message = "Применен overlay replacement."
                    else:
                        self._add_annotation(page, issue, suggestion)
                else:
                    self._add_annotation(page, issue, suggestion)

                pdf.save(updated_pdf_path, garbage=4, deflate=True)
        except Exception as exc:
            logger.warning("PDF apply failed for issue %s: %s", issue_id, exc)
            return self._fallback_only(course_id, issue_id, issue, f"PDF patch failed: {exc}")

        if suggestion and issue.get("claim_text"):
            self._apply_text_revision_to_page(
                course_id=course_id,
                document_id=document_id,
                page_number=page_number,
                claim_text=str(issue.get("claim_text")),
                replacement=suggestion,
            )

        version = self.storage.create_document_version(
            document_id=document_id,
            storage_path=str(updated_pdf_path.as_posix()) if updated_pdf_path else str(source_pdf.as_posix()),
            created_from_issue_id=issue_id,
            created_by_teacher_id=teacher_id,
            meta={"mode": mode, "fallback_used": fallback_used},
        )

        result = ApplyResult(
            apply_id=str(uuid.uuid4()),
            course_id=course_id,
            issue_id=issue_id,
            status="applied" if not fallback_used else "partial",
            mode_used=mode,
            fallback_used=fallback_used,
            message=message,
            updated_pdf_path=str(updated_pdf_path.as_posix()) if updated_pdf_path else None,
            source_pdf_path=str(source_pdf.as_posix()),
            page_number=page_number,
            fragment_id=fragment_id,
            created_at=_utc_now_iso(),
        )
        result_payload = result.to_payload() | {"document_version_id": version["document_version_id"]}
        self.storage.save_apply_result(course_id, result_payload)
        self.storage.update_issue_status(course_id, issue_id, "applied" if not fallback_used else "review", result_payload)
        self._create_material_revision(
            course_id=course_id,
            issue_id=issue_id,
            document_id=document_id,
            document_version_id=version["document_version_id"],
            decision_id=decision_id,
            suggestion=suggestion,
            mode=mode,
            fallback_used=fallback_used,
            message=message,
            updated_pdf_path=result.updated_pdf_path,
            teacher_id=teacher_id,
            status="applied" if not fallback_used else "partial",
        )
        self._reindex_document(course_id=course_id, document_id=document_id, document_version_id=version["document_version_id"])
        return result

    def _try_replace_on_page(self, page: fitz.Page, issue: dict[str, Any], suggestion: str) -> str | None:
        claim_text = str(issue.get("claim_text") or "").strip()
        detected_text = str(issue.get("detected_text") or "").strip()
        targets = [claim_text, detected_text]
        targets = [target for target in targets if target]
        for idx, target in enumerate(targets):
            rects = page.search_for(target)
            if not rects:
                continue
            rect = rects[0]
            safe_rect = fitz.Rect(rect.x0 - 1, rect.y0 - 1, rect.x1 + 1, rect.y1 + 1)
            page.add_redact_annot(safe_rect, fill=(1, 1, 1))
            page.apply_redactions()
            inserted = page.insert_textbox(
                safe_rect,
                suggestion,
                fontsize=9,
                fontname="helv",
                color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_LEFT,
            )
            if inserted >= 0:
                return "direct_replace" if idx == 0 else "overlay_replace"
        return None

    def _add_annotation(self, page: fitz.Page, issue: dict[str, Any], suggestion: str) -> None:
        claim_text = str(issue.get("claim_text") or "").strip()
        message = "Review suggestion:\n"
        if claim_text:
            message += f"Claim: {claim_text}\n"
        if suggestion:
            message += f"Replace with: {suggestion}\n"
        message += f"Issue: {issue.get('issue_type')}"
        annots_iter = page.annots()
        annot_count = sum(1 for _ in annots_iter) if annots_iter is not None else 0
        point = fitz.Point(48, 48 + 18 * annot_count)
        page.add_text_annot(point, message)

    def _build_output_path(self, course_id: str, document_id: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return settings.data_dir / "review" / "pdf_versions" / course_id / document_id / f"{document_id}.reviewed.{stamp}.pdf"

    def _is_locally_applicable(self, issue: dict[str, Any], suggestion: str) -> bool:
        if not suggestion:
            return False
        issue_type = str(issue.get("issue_type") or "")
        if issue_type not in LOCAL_APPLY_ISSUE_TYPES:
            return False
        claim_text = str(issue.get("claim_text") or "")
        if len(claim_text) > 320 or len(suggestion) > 320:
            return False
        span = issue.get("claim_span") or []
        if len(span) == 2:
            try:
                if int(span[1]) - int(span[0]) > 340:
                    return False
            except Exception:
                return False
        return True

    def _fallback_only(self, course_id: str, issue_id: str, issue: dict[str, Any], message: str) -> ApplyResult:
        result = ApplyResult(
            apply_id=str(uuid.uuid4()),
            course_id=course_id,
            issue_id=issue_id,
            status="partial",
            mode_used="annotation_only",
            fallback_used=True,
            message=message,
            updated_pdf_path=None,
            source_pdf_path=None,
            page_number=None,
            fragment_id=str(issue.get("fragment_id") or ""),
            created_at=_utc_now_iso(),
        )
        self.storage.save_apply_result(course_id, result.to_payload())
        self.storage.update_issue_status(course_id, issue_id, "review", result.to_payload())
        return result

    def _apply_text_revision_to_page(
        self,
        course_id: str,
        document_id: str,
        page_number: int,
        claim_text: str,
        replacement: str,
    ) -> None:
        if not claim_text or not replacement:
            return
        with SessionLocal() as db:
            page = (
                db.query(PageDB)
                .filter(PageDB.course_id == course_id, PageDB.document_id == document_id, PageDB.page_number == page_number)
                .first()
            )
            if page is None:
                return
            merged_text = page.merged_text or ""
            if claim_text in merged_text:
                merged_text = merged_text.replace(claim_text, replacement, 1)
            elif claim_text in (page.ocr_text_clean or ""):
                merged_text = (page.ocr_text_clean or "").replace(claim_text, replacement, 1)
            else:
                return
            page.merged_text = merged_text
            page.ocr_text_clean = merged_text
            db.commit()

    def _create_material_revision(
        self,
        course_id: str,
        issue_id: str,
        document_id: str,
        document_version_id: str,
        decision_id: str | None,
        suggestion: str,
        mode: str,
        fallback_used: bool,
        message: str,
        updated_pdf_path: str | None,
        teacher_id: str | None,
        status: str,
    ) -> None:
        with SessionLocal() as db:
            issue = db.get(ReviewIssueDB, issue_id)
            if issue is None:
                return
            db_doc = db.get(DocumentDB, document_id)
            if db_doc is not None:
                # Active document path points to latest reviewed derivative for downstream consumers.
                db_doc.source_pdf_path = updated_pdf_path or db_doc.source_pdf_path
            db.add(
                MaterialRevisionDB(
                    id=str(uuid.uuid4()),
                    course_id=course_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    source_issue_id=issue_id,
                    decision_id=decision_id,
                    revision_type="pdf_overlay" if mode in {"direct_replace", "overlay_replace"} else "pdf_annotation",
                    apply_mode=mode,
                    original_text=issue.claim_text,
                    applied_text=suggestion or issue.suggestion_text,
                    location_json={
                        "fragment_id": issue.fragment_id,
                        "page_number": issue.page_number,
                        "claim_span": issue.claim_span_json,
                    },
                    fallback_used=fallback_used,
                    message=message,
                    applied_by_teacher_id=teacher_id,
                    status=status,
                )
            )
            db.commit()

    def _reindex_document(self, course_id: str, document_id: str, document_version_id: str) -> None:
        baseline_id = self.storage.get_baseline_db_id()
        job_id = self.storage.create_index_job(
            course_id=course_id,
            reason="review_apply",
            document_id=document_id,
            document_version_id=document_version_id,
            baseline_id=baseline_id,
        )
        try:
            self.storage.update_index_job(job_id, "running")
            result = self.index_manager.index_document(course_id=course_id, document_id=document_id)
            self.storage.update_index_job(job_id, "done", stats_json=result)
        except Exception as exc:
            self.storage.update_index_job(job_id, "failed", error_text=str(exc))


def _parse_fragment_id(fragment_id: str) -> tuple[str, int] | None:
    match = re.match(r"^(?P<doc>.+)_p(?P<page>\d+)$", fragment_id)
    if not match:
        return None
    return match.group("doc"), int(match.group("page"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
