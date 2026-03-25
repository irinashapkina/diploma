from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any
import uuid

from sqlalchemy import select

from app.config.settings import settings
from app.db.init_db import init_db
from app.db.models import (
    ApplyOperationDB,
    DocumentVersionDB,
    IndexJobDB,
    ReferenceBaselineRunDB,
    ReviewDecisionDB,
    ReviewIssueDB,
    ReviewRunDB,
)
from app.db.session import SessionLocal


class JsonReviewStorage:
    """DB-backed storage with compatibility methods kept for existing review services."""

    def __init__(self, root_dir: Path | None = None) -> None:
        init_db()
        self.root = root_dir or (settings.data_dir / "review")
        self.reference_raw_dir = self.root / "reference" / "raw"
        self.reference_normalized_dir = self.root / "reference" / "normalized"
        self.reference_baseline_dir = self.root / "reference" / "baseline"
        self.reference_snapshots_dir = self.root / "reference" / "snapshots"
        for path in (
            self.reference_raw_dir,
            self.reference_normalized_dir,
            self.reference_baseline_dir,
            self.reference_snapshots_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # Reference baseline
    def save_reference_run(
        self,
        run_id: str,
        raw_facts: list[dict[str, Any]],
        normalized_facts: list[dict[str, Any]],
        baseline: dict[str, Any],
    ) -> None:
        raw_path = self.reference_raw_dir / f"{run_id}.json"
        norm_path = self.reference_normalized_dir / f"{run_id}.json"
        snap_path = self.reference_snapshots_dir / f"{run_id}.json"
        baseline_path = self.reference_baseline_dir / "current.json"

        self._atomic_write_json(raw_path, {"run_id": run_id, "facts": raw_facts})
        self._atomic_write_json(norm_path, {"run_id": run_id, "facts": normalized_facts})
        snapshot = {"run_id": run_id, "updated_at": _utc_now_iso(), "baseline": baseline}
        self._atomic_write_json(snap_path, snapshot)
        self._atomic_write_json(baseline_path, snapshot)

        with SessionLocal() as db:
            db.query(ReferenceBaselineRunDB).update({"is_active": False})
            db.add(
                ReferenceBaselineRunDB(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    technology="java",
                    is_active=True,
                    summary_json={
                        "raw_count": len(raw_facts),
                        "normalized_count": len(normalized_facts),
                        "baseline_items": len(baseline),
                    },
                    baseline_json=baseline,
                    raw_facts_path=str(raw_path.as_posix()),
                    normalized_facts_path=str(norm_path.as_posix()),
                    baseline_path=str(snap_path.as_posix()),
                )
            )
            db.commit()

    def list_baselines(self) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.execute(select(ReferenceBaselineRunDB).order_by(ReferenceBaselineRunDB.created_at.desc())).scalars().all()
        return [self._baseline_row_to_payload(row) for row in rows]

    def get_active_baseline(self) -> dict[str, Any]:
        with SessionLocal() as db:
            row = db.execute(select(ReferenceBaselineRunDB).where(ReferenceBaselineRunDB.is_active.is_(True))).scalar_one_or_none()
        return self._baseline_row_to_payload(row) if row else {}

    def get_reference_baseline(self) -> dict[str, Any]:
        active = self.get_active_baseline()
        if active:
            return {"run_id": active["run_id"], "updated_at": active["created_at"], "baseline": active["baseline"]}
        return self._read_json_or_default(self.reference_baseline_dir / "current.json", {})

    def get_reference_snapshot(self, run_id: str) -> dict[str, Any]:
        with SessionLocal() as db:
            row = db.execute(select(ReferenceBaselineRunDB).where(ReferenceBaselineRunDB.run_id == run_id)).scalar_one_or_none()
        if row:
            return {"run_id": row.run_id, "updated_at": _dt_iso(row.created_at), "baseline": row.baseline_json or {}}
        return self._read_json_or_default(self.reference_snapshots_dir / f"{run_id}.json", {})

    def get_baseline_db_id(self, run_id: str | None = None) -> str | None:
        with SessionLocal() as db:
            stmt = (
                select(ReferenceBaselineRunDB).where(ReferenceBaselineRunDB.run_id == run_id)
                if run_id
                else select(ReferenceBaselineRunDB).where(ReferenceBaselineRunDB.is_active.is_(True))
            )
            row = db.execute(stmt).scalar_one_or_none()
        return row.id if row else None

    def _ensure_system_baseline(self) -> str:
        with SessionLocal() as db:
            row = db.execute(select(ReferenceBaselineRunDB).where(ReferenceBaselineRunDB.is_active.is_(True))).scalar_one_or_none()
            if row:
                return row.id
            new_row = ReferenceBaselineRunDB(
                id=str(uuid.uuid4()),
                run_id=f"system-{uuid.uuid4()}",
                technology="java",
                is_active=True,
                summary_json={"source": "system-fallback"},
                baseline_json={},
            )
            db.add(new_row)
            db.commit()
            db.refresh(new_row)
            return new_row.id

    # Review scan runs/issues
    def save_scan_run(
        self,
        course_id: str,
        scan_id: str,
        scan_summary: dict[str, Any],
        issues: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
    ) -> None:
        baseline_id = self.get_baseline_db_id()
        if baseline_id is None:
            baseline_id = self._ensure_system_baseline()
        started_at = _parse_iso(scan_summary.get("started_at")) or datetime.now(timezone.utc)
        with SessionLocal() as db:
            run = ReviewRunDB(
                id=scan_id,
                course_id=course_id,
                baseline_id=baseline_id,
                status="completed",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                stats_json=scan_summary,
            )
            db.add(run)
            # Ensure parent review_run exists before inserting child review_issues.
            db.flush()
            for issue in issues:
                mapping = _parse_fragment_id(str(issue.get("fragment_id") or ""))
                document_id, page_number = (mapping if mapping else ("", None))
                db.add(
                    ReviewIssueDB(
                        id=str(issue.get("issue_id") or str(uuid.uuid4())),
                        review_run_id=scan_id,
                        baseline_id=baseline_id,
                        course_id=course_id,
                        document_id=document_id,
                        page_number=page_number,
                        fragment_id=str(issue.get("fragment_id") or ""),
                        issue_type=str(issue.get("issue_type") or "UNKNOWN"),
                        severity=str(issue.get("severity") or "low"),
                        claim_role=issue.get("claim_role"),
                        confidence=float(issue.get("claim_confidence") or issue.get("strength") or 0.0) or None,
                        claim_text=issue.get("claim_text"),
                        claim_span_json=issue.get("claim_span"),
                        detected_text=issue.get("detected_text"),
                        normalized_text=issue.get("normalized_text"),
                        evidence_user=issue.get("evidence"),
                        evidence_debug_json=(issue.get("debug") or {}),
                        suggestion_text=issue.get("suggestion"),
                        suggestion_debug_json={"slot_updates": issue.get("slot_updates") or []},
                        source_refs_json=issue.get("source_refs") or [],
                        status=str(issue.get("status") or "open"),
                    )
                )
            db.commit()

    def list_review_runs(self, course_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.execute(select(ReviewRunDB).where(ReviewRunDB.course_id == course_id).order_by(ReviewRunDB.started_at.desc()))
                .scalars()
                .all()
            )
        return [
            {
                "review_run_id": row.id,
                "course_id": row.course_id,
                "baseline_id": row.baseline_id,
                "status": row.status,
                "started_at": _dt_iso(row.started_at),
                "finished_at": _dt_iso(row.finished_at),
                "stats": row.stats_json or {},
            }
            for row in rows
        ]

    def list_review_issues(
        self,
        course_id: str,
        document_id: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        issue_type: str | None = None,
        review_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            stmt = select(ReviewIssueDB).where(ReviewIssueDB.course_id == course_id)
            if document_id:
                stmt = stmt.where(ReviewIssueDB.document_id == document_id)
            if status:
                stmt = stmt.where(ReviewIssueDB.status == status)
            if severity:
                stmt = stmt.where(ReviewIssueDB.severity == severity)
            if issue_type:
                stmt = stmt.where(ReviewIssueDB.issue_type == issue_type)
            if review_run_id:
                stmt = stmt.where(ReviewIssueDB.review_run_id == review_run_id)
            rows = db.execute(stmt.order_by(ReviewIssueDB.created_at.desc())).scalars().all()
        return [self._issue_row_to_payload(row) for row in rows]

    def get_review_issue(self, issue_id: str) -> dict[str, Any]:
        with SessionLocal() as db:
            row = db.get(ReviewIssueDB, issue_id)
        return self._issue_row_to_payload(row) if row else {}

    def get_scan_issues(self, course_id: str) -> list[dict[str, Any]]:
        return self.list_review_issues(course_id)

    def get_scan_issues_payload(self, course_id: str) -> dict[str, Any]:
        runs = self.list_review_runs(course_id)
        latest = runs[0]["review_run_id"] if runs else None
        issues = self.list_review_issues(course_id, review_run_id=latest) if latest else []
        return {"scan_id": latest, "items": issues}

    def save_scan_issues_payload(self, course_id: str, payload: dict[str, Any]) -> None:
        items = payload.get("items", [])
        with SessionLocal() as db:
            for item in items:
                row = db.get(ReviewIssueDB, item.get("issue_id"))
                if row is None or row.course_id != course_id:
                    continue
                row.status = str(item.get("status") or row.status)
                if "apply_result" in item:
                    row.suggestion_debug_json = {**(row.suggestion_debug_json or {}), "apply_result": item.get("apply_result")}
            db.commit()

    def update_issue_status(
        self,
        course_id: str,
        issue_id: str,
        status: str,
        apply_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with SessionLocal() as db:
            row = db.get(ReviewIssueDB, issue_id)
            if row is None or row.course_id != course_id:
                return None
            row.status = status
            if apply_meta:
                row.suggestion_debug_json = {**(row.suggestion_debug_json or {}), "apply_result": apply_meta}
            db.commit()
            db.refresh(row)
            return self._issue_row_to_payload(row)

    def get_scan_latest(self, course_id: str) -> dict[str, Any]:
        runs = self.list_review_runs(course_id)
        if not runs:
            return {}
        run = runs[0]
        return {
            "scan_id": run["review_run_id"],
            "course_id": run["course_id"],
            "created_at": run["started_at"],
            "summary": run["stats"],
        }

    # Decisions / apply / index
    def create_review_decision(
        self,
        issue_id: str,
        teacher_id: str,
        decision_type: str,
        edited_text: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        decision_id = str(uuid.uuid4())
        with SessionLocal() as db:
            db.add(
                ReviewDecisionDB(
                    id=decision_id,
                    issue_id=issue_id,
                    teacher_id=teacher_id,
                    decision_type=decision_type,
                    edited_text=edited_text,
                    comment=comment,
                )
            )
            db.commit()
        return {
            "decision_id": decision_id,
            "issue_id": issue_id,
            "teacher_id": teacher_id,
            "decision_type": decision_type,
            "edited_text": edited_text,
            "comment": comment,
            "created_at": _utc_now_iso(),
        }

    def save_apply_result(self, course_id: str, apply_result: dict[str, Any]) -> None:
        issue_id = str(apply_result.get("issue_id") or "")
        with SessionLocal() as db:
            issue = db.get(ReviewIssueDB, issue_id)
            if issue is None:
                return
            db.add(
                ApplyOperationDB(
                    id=str(apply_result.get("apply_id") or str(uuid.uuid4())),
                    course_id=course_id,
                    issue_id=issue_id,
                    document_id=issue.document_id,
                    page_number=apply_result.get("page_number"),
                    mode_used=str(apply_result.get("mode_used") or "annotation_only"),
                    fallback_used=bool(apply_result.get("fallback_used")),
                    status=str(apply_result.get("status") or "partial"),
                    updated_pdf_path=apply_result.get("updated_pdf_path"),
                    source_pdf_path=apply_result.get("source_pdf_path"),
                    message=apply_result.get("message"),
                    payload_json=apply_result,
                )
            )
            db.commit()

    def get_apply_results(self, course_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.execute(select(ApplyOperationDB).where(ApplyOperationDB.course_id == course_id).order_by(ApplyOperationDB.created_at.desc()))
                .scalars()
                .all()
            )
        return [row.payload_json | {"created_at": _dt_iso(row.created_at)} for row in rows]

    def create_document_version(
        self,
        document_id: str,
        storage_path: str,
        created_from_issue_id: str | None,
        created_by_teacher_id: str | None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        version_id = str(uuid.uuid4())
        with SessionLocal() as db:
            versions = db.execute(select(DocumentVersionDB).where(DocumentVersionDB.document_id == document_id)).scalars().all()
            next_no = 1 + max((v.version_no for v in versions), default=0)
            current_active = next((v for v in versions if v.is_active), None)
            if current_active:
                current_active.is_active = False
            row = DocumentVersionDB(
                id=version_id,
                document_id=document_id,
                version_no=next_no,
                is_active=True,
                parent_version_id=current_active.id if current_active else None,
                created_from_issue_id=created_from_issue_id,
                storage_path=storage_path,
                meta_json=meta or {},
                created_by_teacher_id=created_by_teacher_id,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._document_version_payload(row)

    def list_document_versions(self, document_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.execute(select(DocumentVersionDB).where(DocumentVersionDB.document_id == document_id).order_by(DocumentVersionDB.version_no.desc()))
                .scalars()
                .all()
            )
        return [self._document_version_payload(row) for row in rows]

    def create_index_job(
        self,
        course_id: str,
        reason: str,
        document_id: str | None = None,
        document_version_id: str | None = None,
        baseline_id: str | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        with SessionLocal() as db:
            db.add(
                IndexJobDB(
                    id=job_id,
                    course_id=course_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    baseline_id=baseline_id,
                    reason=reason,
                    status="queued",
                )
            )
            db.commit()
        return job_id

    def update_index_job(self, job_id: str, status: str, error_text: str | None = None, stats_json: dict[str, Any] | None = None) -> None:
        with SessionLocal() as db:
            row = db.get(IndexJobDB, job_id)
            if row is None:
                return
            row.status = status
            if status == "running":
                row.started_at = datetime.now(timezone.utc)
            if status in {"done", "failed"}:
                row.finished_at = datetime.now(timezone.utc)
            row.error_text = error_text
            if stats_json is not None:
                row.stats_json = stats_json
            db.commit()

    def list_index_jobs(self, course_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.execute(select(IndexJobDB).where(IndexJobDB.course_id == course_id).order_by(IndexJobDB.queued_at.desc()))
                .scalars()
                .all()
            )
        return [
            {
                "index_job_id": row.id,
                "course_id": row.course_id,
                "document_id": row.document_id,
                "document_version_id": row.document_version_id,
                "baseline_id": row.baseline_id,
                "reason": row.reason,
                "status": row.status,
                "queued_at": _dt_iso(row.queued_at),
                "started_at": _dt_iso(row.started_at),
                "finished_at": _dt_iso(row.finished_at),
                "error_text": row.error_text,
                "stats_json": row.stats_json or {},
            }
            for row in rows
        ]

    def get_index_job(self, job_id: str) -> dict[str, Any]:
        with SessionLocal() as db:
            row = db.get(IndexJobDB, job_id)
        if row is None:
            return {}
        return {
            "index_job_id": row.id,
            "course_id": row.course_id,
            "document_id": row.document_id,
            "document_version_id": row.document_version_id,
            "baseline_id": row.baseline_id,
            "reason": row.reason,
            "status": row.status,
            "queued_at": _dt_iso(row.queued_at),
            "started_at": _dt_iso(row.started_at),
            "finished_at": _dt_iso(row.finished_at),
            "error_text": row.error_text,
            "stats_json": row.stats_json or {},
        }

    # Helpers
    def _issue_row_to_payload(self, row: ReviewIssueDB | None) -> dict[str, Any]:
        if row is None:
            return {}
        payload: dict[str, Any] = {
            "issue_id": row.id,
            "review_run_id": row.review_run_id,
            "baseline_id": row.baseline_id,
            "course_id": row.course_id,
            "document_id": row.document_id,
            "document_version_id": row.document_version_id,
            "page_number": row.page_number,
            "fragment_id": row.fragment_id,
            "issue_type": row.issue_type,
            "severity": row.severity,
            "claim_role": row.claim_role,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "claim_text": row.claim_text,
            "claim_span": row.claim_span_json,
            "detected_text": row.detected_text,
            "normalized_text": row.normalized_text,
            "evidence": row.evidence_user,
            "suggestion": row.suggestion_text,
            "source_refs": row.source_refs_json or [],
            "status": row.status,
            "created_at": _dt_iso(row.created_at),
            "updated_at": _dt_iso(row.updated_at),
            "debug": row.evidence_debug_json or {},
            "apply_result": (row.suggestion_debug_json or {}).get("apply_result"),
        }
        return payload

    @staticmethod
    def _baseline_row_to_payload(row: ReferenceBaselineRunDB) -> dict[str, Any]:
        return {
            "id": row.id,
            "run_id": row.run_id,
            "technology": row.technology,
            "is_active": row.is_active,
            "created_at": _dt_iso(row.created_at),
            "summary": row.summary_json or {},
            "baseline": row.baseline_json or {},
            "raw_facts_path": row.raw_facts_path,
            "normalized_facts_path": row.normalized_facts_path,
            "baseline_path": row.baseline_path,
            "checksum": row.checksum,
        }

    @staticmethod
    def _document_version_payload(row: DocumentVersionDB) -> dict[str, Any]:
        return {
            "document_version_id": row.id,
            "document_id": row.document_id,
            "version_no": row.version_no,
            "is_active": row.is_active,
            "parent_version_id": row.parent_version_id,
            "created_from_issue_id": row.created_from_issue_id,
            "storage_path": row.storage_path,
            "content_hash": row.content_hash,
            "meta_json": row.meta_json or {},
            "created_by_teacher_id": row.created_by_teacher_id,
            "created_at": _dt_iso(row.created_at),
        }

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_name = tmp.name
        os.replace(temp_name, path)

    @staticmethod
    def _read_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


def _parse_fragment_id(fragment_id: str) -> tuple[str, int] | None:
    match = re.match(r"^(?P<doc>.+)_p(?P<page>\d+)$", fragment_id)
    if not match:
        return None
    return match.group("doc"), int(match.group("page"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
