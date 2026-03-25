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

    def apply_issue_to_pdf(self, course_id: str, issue_id: str) -> ApplyResult:
        issues_payload = self.storage.get_scan_issues_payload(course_id)
        issue = next((item for item in issues_payload.get("items", []) if item.get("issue_id") == issue_id), None)
        if issue is None:
            raise ValueError(f"Issue not found: {issue_id}")

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

        suggestion = str(issue.get("suggestion") or "").strip()
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
        self.storage.save_apply_result(course_id, result.to_payload())
        self.storage.update_issue_status(course_id, issue_id, "applied" if not fallback_used else "review", result.to_payload())
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


def _parse_fragment_id(fragment_id: str) -> tuple[str, int] | None:
    match = re.match(r"^(?P<doc>.+)_p(?P<page>\d+)$", fragment_id)
    if not match:
        return None
    return match.group("doc"), int(match.group("page"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
