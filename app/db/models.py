from __future__ import annotations

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TeacherDB(Base):
    __tablename__ = "teachers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)


class CourseDB(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    year_label: Mapped[str] = mapped_column(Text, nullable=False)
    semester: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("teacher_id", "title", "year_label", "semester", name="uq_course_identity"),
    )


class DocumentDB(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    uploader_teacher_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, default="application/pdf")
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("course_id", "checksum_sha256", name="uq_document_checksum_by_course"),
    )


class PageDB(Base):
    __tablename__ = "pages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_text_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ocr_text_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ocr_text_clean: Mapped[str] = mapped_column(Text, nullable=False, default="")
    merged_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_source: Mapped[str] = mapped_column(String(16), nullable=False, default="ocr")
    pdf_text_quality: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    ocr_text_quality: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    has_diagram: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_table: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_code_like_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_large_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_page_per_document"),
    )


class ChunkDB(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_id: Mapped[str] = mapped_column(String(64), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("page_id", "chunk_order", name="uq_chunk_order_per_page"),
    )


class IndexDB(Base):
    __tablename__ = "indices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    index_type: Mapped[str] = mapped_column(String(32), nullable=False)
    backend: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    vector_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    objects_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    checksum: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("course_id", "index_type", name="uq_course_index_type"),
    )


class AskMessageDB(Base):
    __tablename__ = "ask_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    question_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entities_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_sense_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_answer_shape: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence_breakdown_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    debug_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnswerSourceDB(Base):
    __tablename__ = "answer_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("ask_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    used_in_final_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReferenceBaselineRunDB(Base):
    __tablename__ = "reference_baseline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    technology: Mapped[str] = mapped_column(String(32), nullable=False, default="java")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    baseline_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_facts_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_facts_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ReviewRunDB(Base):
    __tablename__ = "review_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    baseline_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reference_baseline_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    triggered_by_teacher_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReviewIssueDB(Base):
    __tablename__ = "review_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    baseline_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reference_baseline_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fragment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    claim_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_span_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    detected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_debug_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    suggestion_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion_debug_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    superseded_by_issue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("review_issues.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ReviewDecisionDB(Base):
    __tablename__ = "review_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_issues.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False, index=True)
    decision_type: Mapped[str] = mapped_column(String(16), nullable=False)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DocumentVersionDB(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    parent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_from_issue_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_teacher_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_version_no"),
    )


class MaterialRevisionDB(Base):
    __tablename__ = "material_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_issue_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_issues.id", ondelete="CASCADE"), nullable=False, index=True)
    decision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("review_decisions.id", ondelete="SET NULL"), nullable=True)
    revision_type: Mapped[str] = mapped_column(String(24), nullable=False)
    apply_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_by_teacher_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=True
    )
    applied_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="applied")


class IndexJobDB(Base):
    __tablename__ = "index_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    document_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    baseline_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("reference_baseline_runs.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    queued_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ApplyOperationDB(Base):
    __tablename__ = "apply_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    issue_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_issues.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode_used: Mapped[str] = mapped_column(String(24), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
