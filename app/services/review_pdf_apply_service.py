from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import shutil
import uuid
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

import fitz

from app.config.settings import settings
from app.db.models import DocumentDB, MaterialRevisionDB, ReviewIssueDB
from app.db.session import SessionLocal
from app.indexing.index_manager import IndexManager
from app.indexing.store import ArtifactStore
from app.ingestion.pdf_ingestor import PDFIngestor
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


@dataclass(slots=True)
class FileApplyOutcome:
    updated_path: Path
    mode: str
    fallback_used: bool
    message: str


class ReviewPdfApplyService:
    def __init__(self, store: ArtifactStore, storage: JsonReviewStorage) -> None:
        self.store = store
        self.storage = storage
        self.index_manager = IndexManager(store=store)
        self.ingestor = PDFIngestor()

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
        mime_type = (self.store.get_document_mime_type(document_id) or "application/pdf").lower()
        source_file = self._resolve_active_source_path(document_id=document_id, fallback=Path(document.source_pdf))
        if not source_file.exists():
            return self._fallback_only(course_id, issue_id, issue, "Исходный файл документа не найден на диске.")

        suggestion = str(applied_text_override or issue.get("suggestion") or "").strip()
        if not suggestion:
            return self._fallback_only(course_id, issue_id, issue, "Для apply отсутствует suggestion/edited_text.")

        try:
            outcome = self._apply_file_by_mime(
                mime_type=mime_type,
                source_path=source_file,
                course_id=course_id,
                document_id=document_id,
                page_number=page_number,
                issue=issue,
                suggestion=suggestion,
            )
        except Exception as exc:
            logger.warning("Apply failed for issue %s: %s", issue_id, exc)
            return self._fallback_only(course_id, issue_id, issue, f"Apply failed: {exc}")

        if not outcome.updated_path.exists():
            return self._fallback_only(course_id, issue_id, issue, "Updated file was not created.")

        try:
            refreshed_pages = self._refresh_pages_from_file(
                course_id=course_id,
                document_id=document_id,
                document_title=document.document_title,
                file_path=outcome.updated_path,
                mime_type=mime_type,
            )
            self.store.replace_pages_for_document(course_id=course_id, document_id=document_id, pages=refreshed_pages)
            self.store.update_document_source_and_page_count(
                document_id=document_id,
                source_path=str(outcome.updated_path.as_posix()),
                page_count=len(refreshed_pages),
            )
        except Exception as exc:
            logger.warning("Page refresh from updated file failed for issue %s: %s", issue_id, exc)
            return self._fallback_only(course_id, issue_id, issue, f"Apply created file but refresh failed: {exc}")

        version = self.storage.create_document_version(
            document_id=document_id,
            storage_path=str(outcome.updated_path.as_posix()),
            created_from_issue_id=issue_id,
            created_by_teacher_id=teacher_id,
            meta={"mode": outcome.mode, "fallback_used": outcome.fallback_used, "mime_type": mime_type},
        )

        result = ApplyResult(
            apply_id=str(uuid.uuid4()),
            course_id=course_id,
            issue_id=issue_id,
            status="applied" if not outcome.fallback_used else "partial",
            mode_used=outcome.mode,
            fallback_used=outcome.fallback_used,
            message=outcome.message,
            updated_pdf_path=str(outcome.updated_path.as_posix()),
            source_pdf_path=str(source_file.as_posix()),
            page_number=page_number,
            fragment_id=fragment_id,
            created_at=_utc_now_iso(),
        )
        result_payload = result.to_payload() | {"document_version_id": version["document_version_id"]}
        self.storage.save_apply_result(course_id, result_payload)
        self.storage.update_issue_status(course_id, issue_id, "applied" if not outcome.fallback_used else "review", result_payload)
        self._create_material_revision(
            course_id=course_id,
            issue_id=issue_id,
            document_id=document_id,
            document_version_id=version["document_version_id"],
            decision_id=decision_id,
            suggestion=suggestion,
            mode=outcome.mode,
            fallback_used=outcome.fallback_used,
            message=outcome.message,
            updated_pdf_path=result.updated_pdf_path,
            teacher_id=teacher_id,
            status="applied" if not outcome.fallback_used else "partial",
        )
        self._reindex_document(course_id=course_id, document_id=document_id, document_version_id=version["document_version_id"])
        return result

    def _resolve_active_source_path(self, document_id: str, fallback: Path) -> Path:
        versions = self.storage.list_document_versions(document_id)
        active = next((item for item in versions if bool(item.get("is_active"))), None)
        if not active:
            return fallback
        storage_path = str(active.get("storage_path") or "").strip()
        if not storage_path:
            return fallback
        return Path(storage_path)

    def _apply_file_by_mime(
        self,
        *,
        mime_type: str,
        source_path: Path,
        course_id: str,
        document_id: str,
        page_number: int,
        issue: dict[str, Any],
        suggestion: str,
    ) -> FileApplyOutcome:
        if mime_type == "application/pdf":
            return self._apply_to_pdf_file(
                source_path=source_path,
                course_id=course_id,
                document_id=document_id,
                page_number=page_number,
                issue=issue,
                suggestion=suggestion,
            )
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._apply_to_docx_file(
                source_path=source_path,
                course_id=course_id,
                document_id=document_id,
                issue=issue,
                suggestion=suggestion,
            )
        if mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            return self._apply_to_pptx_file(
                source_path=source_path,
                course_id=course_id,
                document_id=document_id,
                page_number=page_number,
                issue=issue,
                suggestion=suggestion,
            )
        raise ValueError(f"Unsupported mime_type for apply: {mime_type}")

    def _apply_to_pdf_file(
        self,
        *,
        source_path: Path,
        course_id: str,
        document_id: str,
        page_number: int,
        issue: dict[str, Any],
        suggestion: str,
    ) -> FileApplyOutcome:
        applicability = self._is_locally_applicable(issue, suggestion)
        mode = "annotation_only"
        fallback_used = True
        message = "Применен fallback annotation mode."
        output = self._build_output_path(course_id, document_id, extension="pdf")
        output.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(source_path) as pdf:
            page_index = max(0, page_number - 1)
            if page_index >= len(pdf):
                raise ValueError("Page number out of range.")
            page = pdf[page_index]
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
            pdf.save(output, garbage=4, deflate=True)
        return FileApplyOutcome(updated_path=output, mode=mode, fallback_used=fallback_used, message=message)

    def _apply_to_docx_file(
        self,
        *,
        source_path: Path,
        course_id: str,
        document_id: str,
        issue: dict[str, Any],
        suggestion: str,
    ) -> FileApplyOutcome:
        output = self._build_output_path(course_id, document_id, extension="docx")
        targets = self._replacement_targets(issue)
        replaced = _rewrite_zip_xml_text(
            source_zip=source_path,
            output_zip=output,
            entry_name="word/document.xml",
            targets=targets,
            replacement=suggestion,
        )
        if replaced:
            return FileApplyOutcome(
                updated_path=output,
                mode="docx_local_replace",
                fallback_used=False,
                message="Локальная замена в DOCX выполнена.",
            )
        return FileApplyOutcome(
            updated_path=output,
            mode="docx_fallback_copy",
            fallback_used=True,
            message="DOCX версия создана, но точный target не найден для локальной замены.",
        )

    def _apply_to_pptx_file(
        self,
        *,
        source_path: Path,
        course_id: str,
        document_id: str,
        page_number: int,
        issue: dict[str, Any],
        suggestion: str,
    ) -> FileApplyOutcome:
        output = self._build_output_path(course_id, document_id, extension="pptx")
        targets = self._replacement_targets(issue)
        primary_slide = f"ppt/slides/slide{max(1, page_number)}.xml"
        replaced = _rewrite_zip_xml_text(
            source_zip=source_path,
            output_zip=output,
            entry_name=primary_slide,
            targets=targets,
            replacement=suggestion,
        )
        if not replaced:
            replaced = _rewrite_zip_xml_text_any(
                source_zip=output,
                output_zip=output,
                entry_pattern=r"^ppt/slides/slide\d+\.xml$",
                targets=targets,
                replacement=suggestion,
            )
        if replaced:
            return FileApplyOutcome(
                updated_path=output,
                mode="pptx_local_replace",
                fallback_used=False,
                message="Локальная замена в PPTX выполнена.",
            )
        return FileApplyOutcome(
            updated_path=output,
            mode="pptx_fallback_copy",
            fallback_used=True,
            message="PPTX версия создана, но точный target не найден для локальной замены.",
        )

    def _refresh_pages_from_file(
        self,
        *,
        course_id: str,
        document_id: str,
        document_title: str,
        file_path: Path,
        mime_type: str,
    ) -> list:
        if mime_type == "application/pdf":
            return self.ingestor._extract_pages_from_pdf(  # noqa: SLF001
                pdf_path=file_path,
                course_id=course_id,
                document_id=document_id,
                document_title=document_title,
                force_text_source=None,
            )
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            rendered_pdf = file_path.with_suffix(".rendered.pdf")
            self.ingestor._render_docx_to_pdf(docx_path=file_path, rendered_pdf_path=rendered_pdf)  # noqa: SLF001
            return self.ingestor._extract_pages_from_pdf(  # noqa: SLF001
                pdf_path=rendered_pdf,
                course_id=course_id,
                document_id=document_id,
                document_title=document_title,
                force_text_source="docx",
            )
        if mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            page_texts = self.ingestor.extract_pptx_slide_texts(file_path)
            return self.ingestor._build_text_pages(  # noqa: SLF001
                page_texts=page_texts,
                course_id=course_id,
                document_id=document_id,
                title=document_title,
                text_source="pptx",
            )
        raise ValueError(f"Unsupported mime_type for refresh: {mime_type}")

    def _replacement_targets(self, issue: dict[str, Any]) -> list[str]:
        targets = [
            str(issue.get("claim_text") or "").strip(),
            str(issue.get("detected_text") or "").strip(),
        ]
        return [item for item in targets if item]

    def _try_replace_on_page(self, page: fitz.Page, issue: dict[str, Any], suggestion: str) -> str | None:
        targets = self._replacement_targets(issue)
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

    def _build_output_path(self, course_id: str, document_id: str, extension: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return (
            settings.data_dir
            / "review"
            / f"{extension}_versions"
            / course_id
            / document_id
            / f"{document_id}.reviewed.{stamp}.{extension}"
        )

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
            if db_doc is not None and updated_pdf_path:
                db_doc.source_pdf_path = updated_pdf_path

            if mode.startswith("pdf_") or mode in {"direct_replace", "overlay_replace", "annotation_only"}:
                revision_type = "pdf_overlay" if mode in {"direct_replace", "overlay_replace"} else "pdf_annotation"
            elif mode.startswith("docx_"):
                revision_type = "docx_patch"
            elif mode.startswith("pptx_"):
                revision_type = "pptx_patch"
            else:
                revision_type = "text_patch"

            db.add(
                MaterialRevisionDB(
                    id=str(uuid.uuid4()),
                    course_id=course_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    source_issue_id=issue_id,
                    decision_id=decision_id,
                    revision_type=revision_type,
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


def _rewrite_zip_xml_text(
    *,
    source_zip: Path,
    output_zip: Path,
    entry_name: str,
    targets: list[str],
    replacement: str,
) -> bool:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    replaced_any = False
    with zipfile.ZipFile(source_zip, "r") as zin, zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == entry_name:
                updated, replaced = _replace_text_in_xml_bytes(data, targets=targets, replacement=replacement)
                data = updated
                replaced_any = replaced_any or replaced
            zout.writestr(info, data)
    return replaced_any


def _rewrite_zip_xml_text_any(
    *,
    source_zip: Path,
    output_zip: Path,
    entry_pattern: str,
    targets: list[str],
    replacement: str,
) -> bool:
    pattern = re.compile(entry_pattern)
    temp_output = output_zip.with_suffix(f"{output_zip.suffix}.tmp")
    replaced_any = False
    with zipfile.ZipFile(source_zip, "r") as zin, zipfile.ZipFile(temp_output, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if pattern.match(info.filename):
                updated, replaced = _replace_text_in_xml_bytes(data, targets=targets, replacement=replacement)
                data = updated
                replaced_any = replaced_any or replaced
            zout.writestr(info, data)
    shutil.move(str(temp_output), str(output_zip))
    return replaced_any


def _replace_text_in_xml_bytes(xml_bytes: bytes, *, targets: list[str], replacement: str) -> tuple[bytes, bool]:
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return xml_bytes, False

    text_nodes = [node for node in root.iter() if node.tag.endswith("}t")]
    if not text_nodes:
        return xml_bytes, False
    texts = [node.text or "" for node in text_nodes]
    full_text = "".join(texts)
    target = next((item for item in targets if item and item in full_text), "")
    if not target:
        return xml_bytes, False

    new_text = full_text.replace(target, replacement, 1)
    cursor = 0
    for idx, node in enumerate(text_nodes):
        old_len = len(texts[idx])
        slice_value = new_text[cursor : cursor + old_len]
        node.text = slice_value
        cursor += old_len
    if cursor < len(new_text):
        tail = new_text[cursor:]
        text_nodes[-1].text = f"{text_nodes[-1].text or ''}{tail}"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), True


def _parse_fragment_id(fragment_id: str) -> tuple[str, int] | None:
    match = re.match(r"^(?P<doc>.+)_p(?P<page>\d+)$", fragment_id)
    if not match:
        return None
    return match.group("doc"), int(match.group("page"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
