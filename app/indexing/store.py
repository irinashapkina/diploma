from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.schemas.models import ChunkRecord, CourseRecord, DocumentRecord, PageRecord, TeacherRecord
from app.utils.io import read_jsonl, write_jsonl

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import delete, select

    from app.db.init_db import init_db
    from app.db.models import AnswerSourceDB, AskMessageDB, ChunkDB, CourseDB, DocumentDB, IndexDB, PageDB, TeacherDB
    from app.db.session import SessionLocal

    _SQLALCHEMY_AVAILABLE = True
except Exception:
    _SQLALCHEMY_AVAILABLE = False


class ArtifactStore:
    def __init__(self) -> None:
        self._legacy = not _SQLALCHEMY_AVAILABLE
        if self._legacy:
            logger.warning("SQLAlchemy is unavailable. Running in legacy JSONL mode.")
            self.documents_path = settings.artifacts_dir / "documents.jsonl"
            self.pages_path = settings.artifacts_dir / "pages.jsonl"
            self.chunks_path = settings.artifacts_dir / "chunks.jsonl"
            self._teachers: dict[str, TeacherRecord] = {}
            self._courses: dict[str, CourseRecord] = {}
            self.ensure_artifact_files()
            return
        try:
            with SessionLocal() as db:
                db.execute(select(1))
        except Exception as exc:
            logger.warning("DB connection check failed (%s). Falling back to legacy JSONL mode.", exc)
            self._legacy = True
            self.documents_path = settings.artifacts_dir / "documents.jsonl"
            self.pages_path = settings.artifacts_dir / "pages.jsonl"
            self.chunks_path = settings.artifacts_dir / "chunks.jsonl"
            self._teachers: dict[str, TeacherRecord] = {}
            self._courses: dict[str, CourseRecord] = {}
            self.ensure_artifact_files()
            return
        try:
            if settings.db_auto_init:
                init_db()
        except Exception as exc:
            logger.warning("DB init failed (%s). Falling back to legacy JSONL mode.", exc)
            self._legacy = True
            self.documents_path = settings.artifacts_dir / "documents.jsonl"
            self.pages_path = settings.artifacts_dir / "pages.jsonl"
            self.chunks_path = settings.artifacts_dir / "chunks.jsonl"
            self._teachers: dict[str, TeacherRecord] = {}
            self._courses: dict[str, CourseRecord] = {}
            self.ensure_artifact_files()
            return

    def ensure_artifact_files(self) -> None:
        if not self._legacy:
            return
        for p in [self.documents_path, self.pages_path, self.chunks_path]:
            p.parent.mkdir(parents=True, exist_ok=True)
            if not Path(p).exists():
                write_jsonl(p, [])

    # Teachers / Courses
    def create_teacher(self, full_name: str) -> TeacherRecord:
        teacher = TeacherRecord(teacher_id=str(uuid.uuid4()), full_name=full_name)
        if self._legacy:
            self._teachers[teacher.teacher_id] = teacher
            return teacher
        with SessionLocal() as db:
            db.add(TeacherDB(id=teacher.teacher_id, full_name=teacher.full_name))
            db.commit()
        return teacher

    def get_teacher(self, teacher_id: str) -> TeacherRecord | None:
        if self._legacy:
            return self._teachers.get(teacher_id)
        with SessionLocal() as db:
            row = db.get(TeacherDB, teacher_id)
        if row is None:
            return None
        return TeacherRecord(teacher_id=row.id, full_name=row.full_name)

    def create_course(
        self,
        teacher_id: str,
        title: str,
        year_label: str,
        semester: str | None = None,
        description: str | None = None,
    ) -> CourseRecord:
        course = CourseRecord(
            course_id=str(uuid.uuid4()),
            teacher_id=teacher_id,
            title=title,
            year_label=year_label,
            semester=semester,
            description=description,
            is_active=True,
        )
        if self._legacy:
            if teacher_id not in self._teachers:
                raise ValueError(f"Teacher not found: {teacher_id}")
            self._courses[course.course_id] = course
            return course
        with SessionLocal() as db:
            if db.get(TeacherDB, teacher_id) is None:
                raise ValueError(f"Teacher not found: {teacher_id}")
            db.add(
                CourseDB(
                    id=course.course_id,
                    teacher_id=course.teacher_id,
                    title=course.title,
                    year_label=course.year_label,
                    semester=course.semester,
                    description=course.description,
                    is_active=course.is_active,
                )
            )
            db.commit()
        return course

    def list_courses(self, teacher_id: str | None = None) -> list[CourseRecord]:
        if self._legacy:
            courses = list(self._courses.values())
            if teacher_id:
                courses = [c for c in courses if c.teacher_id == teacher_id]
            return courses
        with SessionLocal() as db:
            stmt = select(CourseDB)
            if teacher_id:
                stmt = stmt.where(CourseDB.teacher_id == teacher_id)
            rows = db.execute(stmt).scalars().all()
        return [
            CourseRecord(
                course_id=r.id,
                teacher_id=r.teacher_id,
                title=r.title,
                year_label=r.year_label,
                semester=r.semester,
                description=r.description,
                is_active=r.is_active,
            )
            for r in rows
        ]

    def get_course(self, course_id: str) -> CourseRecord | None:
        if self._legacy:
            return self._courses.get(course_id)
        with SessionLocal() as db:
            row = db.get(CourseDB, course_id)
        if row is None:
            return None
        return CourseRecord(
            course_id=row.id,
            teacher_id=row.teacher_id,
            title=row.title,
            year_label=row.year_label,
            semester=row.semester,
            description=row.description,
            is_active=row.is_active,
        )

    # Documents / Pages / Chunks
    def create_document(
        self,
        document: DocumentRecord,
        uploader_teacher_id: str | None = None,
        source_filename: str = "",
        checksum_sha256: str | None = None,
    ) -> None:
        if self._legacy:
            docs = self.list_documents(course_id=document.course_id)
            docs.append(document)
            all_docs: list[DocumentRecord] = []
            for raw in read_jsonl(self.documents_path):
                if raw.get("course_id") == document.course_id:
                    continue
                try:
                    all_docs.append(DocumentRecord(**raw))
                except Exception:
                    continue
            all_docs.extend(docs)
            write_jsonl(self.documents_path, [d.model_dump() for d in all_docs])
            return
        with SessionLocal() as db:
            if db.get(CourseDB, document.course_id) is None:
                raise ValueError(f"Course not found: {document.course_id}")
            db.add(
                DocumentDB(
                    id=document.document_id,
                    course_id=document.course_id,
                    uploader_teacher_id=uploader_teacher_id,
                    title=document.document_title,
                    source_filename=source_filename or document.source_filename or document.document_title,
                    source_pdf_path=document.source_pdf,
                    checksum_sha256=checksum_sha256 or document.document_id,
                    mime_type=document.mime_type or "application/pdf",
                    size_bytes=None,
                    page_count=document.page_count,
                    status="uploaded",
                    error_message=None,
                )
            )
            db.commit()

    def update_document_status(self, document_id: str, status: str, error_message: str | None = None) -> None:
        if self._legacy:
            return
        with SessionLocal() as db:
            row = db.get(DocumentDB, document_id)
            if row is None:
                raise ValueError(f"Document not found: {document_id}")
            row.status = status
            row.error_message = error_message
            db.commit()

    def list_documents(self, course_id: str | None = None) -> list[DocumentRecord]:
        if self._legacy:
            docs: list[DocumentRecord] = []
            for raw in read_jsonl(self.documents_path):
                try:
                    docs.append(DocumentRecord(**raw))
                except Exception:
                    continue
            if course_id:
                docs = [d for d in docs if d.course_id == course_id]
            return docs
        with SessionLocal() as db:
            stmt = select(DocumentDB)
            if course_id:
                stmt = stmt.where(DocumentDB.course_id == course_id)
            rows = db.execute(stmt).scalars().all()
        return [
            DocumentRecord(
                document_id=r.id,
                course_id=r.course_id,
                document_title=r.title,
                source_pdf=r.source_pdf_path,
                page_count=r.page_count,
                mime_type=r.mime_type or "application/pdf",
                source_filename=r.source_filename or "",
            )
            for r in rows
        ]

    def get_document(self, document_id: str) -> DocumentRecord | None:
        docs = self.list_documents()
        for doc in docs:
            if doc.document_id == document_id:
                return doc
        return None

    def get_document_mime_type(self, document_id: str) -> str | None:
        if self._legacy:
            doc = self.get_document(document_id)
            return doc.mime_type if doc else None
        with SessionLocal() as db:
            row = db.get(DocumentDB, document_id)
        if row is None:
            return None
        return row.mime_type or "application/pdf"

    def create_pages(self, pages: list[PageRecord]) -> None:
        if not pages:
            return
        if self._legacy:
            existing: list[PageRecord] = []
            for raw in read_jsonl(self.pages_path):
                try:
                    existing.append(PageRecord(**raw))
                except Exception:
                    continue
            existing.extend(pages)
            write_jsonl(self.pages_path, [p.model_dump() for p in existing])
            return
        with SessionLocal() as db:
            for p in pages:
                db.add(
                    PageDB(
                        id=p.page_id,
                        course_id=p.course_id,
                        document_id=p.document_id,
                        page_number=p.page_number,
                        image_path=p.image_path,
                        pdf_text_raw=p.pdf_text_raw,
                        ocr_text_raw=p.ocr_text_raw,
                        ocr_text_clean=p.ocr_text_clean,
                        merged_text=p.merged_text,
                        text_source=p.text_source,
                        pdf_text_quality=p.pdf_text_quality,
                        ocr_text_quality=p.ocr_text_quality,
                        language=p.language,
                        has_diagram=p.has_diagram,
                        has_table=p.has_table,
                        has_code_like_text=p.has_code_like_text,
                        has_large_image=p.has_large_image,
                    )
                )
            db.commit()

    def replace_pages_for_document(self, course_id: str, document_id: str, pages: list[PageRecord]) -> None:
        if self._legacy:
            existing_pages: list[PageRecord] = []
            for raw in read_jsonl(self.pages_path):
                try:
                    page = PageRecord(**raw)
                except Exception:
                    continue
                if page.course_id == course_id and page.document_id == document_id:
                    continue
                existing_pages.append(page)
            existing_pages.extend(pages)
            write_jsonl(self.pages_path, [p.model_dump() for p in existing_pages])

            existing_chunks = self.list_chunks(course_id=course_id)
            kept_chunks = [c for c in existing_chunks if c.document_id != document_id]
            all_chunks: list[ChunkRecord] = []
            for raw in read_jsonl(self.chunks_path):
                if raw.get("course_id") == course_id:
                    continue
                try:
                    all_chunks.append(ChunkRecord(**raw))
                except Exception:
                    continue
            all_chunks.extend(kept_chunks)
            write_jsonl(self.chunks_path, [c.model_dump() for c in all_chunks])
            return

        with SessionLocal() as db:
            db.execute(delete(PageDB).where(PageDB.course_id == course_id, PageDB.document_id == document_id))
            for p in pages:
                db.add(
                    PageDB(
                        id=p.page_id,
                        course_id=p.course_id,
                        document_id=p.document_id,
                        page_number=p.page_number,
                        image_path=p.image_path,
                        pdf_text_raw=p.pdf_text_raw,
                        ocr_text_raw=p.ocr_text_raw,
                        ocr_text_clean=p.ocr_text_clean,
                        merged_text=p.merged_text,
                        text_source=p.text_source,
                        pdf_text_quality=p.pdf_text_quality,
                        ocr_text_quality=p.ocr_text_quality,
                        language=p.language,
                        has_diagram=p.has_diagram,
                        has_table=p.has_table,
                        has_code_like_text=p.has_code_like_text,
                        has_large_image=p.has_large_image,
                    )
                )
            db.commit()

    def update_document_source_and_page_count(self, document_id: str, source_path: str, page_count: int) -> None:
        if self._legacy:
            docs = self.list_documents()
            for idx, doc in enumerate(docs):
                if doc.document_id != document_id:
                    continue
                docs[idx] = doc.model_copy(update={"source_pdf": source_path, "page_count": page_count})
                break
            write_jsonl(self.documents_path, [d.model_dump() for d in docs])
            return
        with SessionLocal() as db:
            row = db.get(DocumentDB, document_id)
            if row is None:
                raise ValueError(f"Document not found: {document_id}")
            row.source_pdf_path = source_path
            row.page_count = page_count
            db.commit()

    def list_pages(self, course_id: str | None = None, document_id: str | None = None) -> list[PageRecord]:
        if not course_id and not document_id:
            raise ValueError("course_id is required for page listing")
        if self._legacy:
            pages: list[PageRecord] = []
            for raw in read_jsonl(self.pages_path):
                try:
                    pages.append(PageRecord(**raw))
                except Exception:
                    continue
            if course_id:
                pages = [p for p in pages if p.course_id == course_id]
            if document_id:
                pages = [p for p in pages if p.document_id == document_id]
            return pages
        with SessionLocal() as db:
            stmt = select(PageDB)
            if course_id:
                stmt = stmt.where(PageDB.course_id == course_id)
            if document_id:
                stmt = stmt.where(PageDB.document_id == document_id)
            rows = db.execute(stmt.order_by(PageDB.document_id, PageDB.page_number)).scalars().all()
            doc_titles = {
                d.id: d.title
                for d in db.execute(select(DocumentDB).where(DocumentDB.id.in_([r.document_id for r in rows]))).scalars().all()
            }
        return [
            PageRecord(
                course_id=r.course_id,
                document_id=r.document_id,
                document_title=doc_titles.get(r.document_id, ""),
                page_id=r.id,
                page_number=r.page_number,
                image_path=r.image_path,
                pdf_text_raw=r.pdf_text_raw,
                ocr_text_raw=r.ocr_text_raw,
                ocr_text_clean=r.ocr_text_clean,
                merged_text=r.merged_text,
                text_source=r.text_source,
                pdf_text_quality=float(r.pdf_text_quality),
                ocr_text_quality=float(r.ocr_text_quality),
                language=r.language,  # type: ignore[arg-type]
                has_diagram=r.has_diagram,
                has_table=r.has_table,
                has_code_like_text=r.has_code_like_text,
                has_large_image=r.has_large_image,
            )
            for r in rows
        ]

    def list_chunks(self, course_id: str | None = None, document_id: str | None = None) -> list[ChunkRecord]:
        if not course_id and not document_id:
            raise ValueError("course_id is required for chunk listing")
        if self._legacy:
            chunks: list[ChunkRecord] = []
            for raw in read_jsonl(self.chunks_path):
                try:
                    chunks.append(ChunkRecord(**raw))
                except Exception:
                    continue
            if course_id:
                chunks = [c for c in chunks if c.course_id == course_id]
            if document_id:
                chunks = [c for c in chunks if c.document_id == document_id]
            return chunks
        with SessionLocal() as db:
            stmt = select(ChunkDB)
            if course_id:
                stmt = stmt.where(ChunkDB.course_id == course_id)
            if document_id:
                stmt = stmt.where(ChunkDB.document_id == document_id)
            rows = db.execute(stmt.order_by(ChunkDB.document_id, ChunkDB.page_id, ChunkDB.chunk_order)).scalars().all()
            doc_titles = {
                d.id: d.title
                for d in db.execute(select(DocumentDB).where(DocumentDB.id.in_([r.document_id for r in rows]))).scalars().all()
            }
            page_map = {
                p.id: p.page_number
                for p in db.execute(select(PageDB).where(PageDB.id.in_([r.page_id for r in rows]))).scalars().all()
            }
        return [
            ChunkRecord(
                chunk_id=r.id,
                course_id=r.course_id,
                document_id=r.document_id,
                document_title=doc_titles.get(r.document_id, ""),
                page_id=r.page_id,
                page_number=page_map.get(r.page_id, 0),
                chunk_order=r.chunk_order,
                text=r.text,
                cleaned_text=r.cleaned_text,
                normalized_text=r.normalized_text,
                metadata=r.metadata_json or {},
                image_path=r.image_path or "",
            )
            for r in rows
        ]

    def upsert_chunks_for_document(self, course_id: str, document_id: str, chunks: list[ChunkRecord]) -> None:
        if self._legacy:
            existing = self.list_chunks(course_id=course_id)
            kept = [c for c in existing if c.document_id != document_id]
            kept.extend(chunks)
            all_chunks: list[ChunkRecord] = []
            for raw in read_jsonl(self.chunks_path):
                if raw.get("course_id") == course_id:
                    continue
                try:
                    all_chunks.append(ChunkRecord(**raw))
                except Exception:
                    continue
            all_chunks.extend(kept)
            write_jsonl(self.chunks_path, [c.model_dump() for c in all_chunks])
            return
        with SessionLocal() as db:
            db.execute(delete(ChunkDB).where(ChunkDB.document_id == document_id, ChunkDB.course_id == course_id))
            for c in chunks:
                db.add(
                    ChunkDB(
                        id=c.chunk_id,
                        course_id=c.course_id,
                        document_id=c.document_id,
                        page_id=c.page_id,
                        chunk_order=c.chunk_order,
                        text=c.text,
                        cleaned_text=c.cleaned_text,
                        normalized_text=c.normalized_text,
                        image_path=c.image_path,
                        metadata_json=c.metadata,
                    )
                )
            db.commit()

    # Index metadata (no-op in legacy)
    def upsert_index_metadata(
        self,
        course_id: str,
        index_type: str,
        backend: str,
        path: str,
        vector_dim: int | None,
        objects_count: int,
        model_name: str | None,
        status: str = "ready",
        checksum: str | None = None,
    ) -> None:
        if self._legacy:
            return
        with SessionLocal() as db:
            row = db.execute(select(IndexDB).where(IndexDB.course_id == course_id, IndexDB.index_type == index_type)).scalar_one_or_none()
            if row is None:
                db.add(
                    IndexDB(
                        id=str(uuid.uuid4()),
                        course_id=course_id,
                        index_type=index_type,
                        backend=backend,
                        path=path,
                        vector_dim=vector_dim,
                        objects_count=objects_count,
                        model_name=model_name,
                        status=status,
                        checksum=checksum,
                    )
                )
            else:
                row.backend = backend
                row.path = path
                row.vector_dim = vector_dim
                row.objects_count = objects_count
                row.model_name = model_name
                row.status = status
                row.checksum = checksum
            db.commit()

    def create_ask_message(
        self,
        course_id: str,
        question: str,
        answer: str,
        answer_mode: str,
        confidence: float,
        question_intent: str,
        entities: list[str],
        selected_sense: dict[str, str],
        expected_answer_shape: str,
        support: dict[str, Any],
        validation: dict[str, Any],
        confidence_breakdown: dict[str, Any],
        debug_payload: dict[str, Any] | None,
    ) -> str:
        message_id = str(uuid.uuid4())
        if self._legacy:
            return message_id
        with SessionLocal() as db:
            db.add(
                AskMessageDB(
                    id=message_id,
                    course_id=course_id,
                    question=question,
                    answer=answer,
                    answer_mode=answer_mode,
                    confidence=confidence,
                    question_intent=question_intent,
                    entities_json=entities,
                    selected_sense_json=selected_sense,
                    expected_answer_shape=expected_answer_shape,
                    support_json=support,
                    validation_json=validation,
                    confidence_breakdown_json=confidence_breakdown,
                    debug_json=debug_payload or {},
                )
            )
            db.commit()
        return message_id

    def create_answer_sources(self, message_id: str, course_id: str, sources: list[dict[str, Any]]) -> None:
        if self._legacy:
            return
        with SessionLocal() as db:
            docs_rows = db.execute(select(DocumentDB).where(DocumentDB.course_id == course_id)).scalars().all()
            docs_by_id = {d.id: d for d in docs_rows}
            docs_by_title = {d.title: d for d in docs_rows}
            pages_rows = db.execute(select(PageDB).where(PageDB.course_id == course_id)).scalars().all()
            for src in sources:
                page_num = int(src.get("page", 0))
                src_title = str(src.get("document_title", "")).strip()
                matched_doc = docs_by_title.get(src_title)
                if matched_doc is None:
                    matched_doc = next(iter(docs_by_id.values()), None)
                if matched_doc is None:
                    continue
                matched_page = next(
                    (p for p in pages_rows if p.document_id == matched_doc.id and p.page_number == page_num),
                    None,
                )
                if matched_page is None:
                    continue
                db.add(
                    AnswerSourceDB(
                        id=str(uuid.uuid4()),
                        message_id=message_id,
                        course_id=course_id,
                        document_id=matched_doc.id,
                        page_id=matched_page.id,
                        chunk_id=None,
                        source_type=src.get("type", "text"),
                        score=float(src.get("score", 0.0)),
                        snippet=str(src.get("snippet", "")),
                        used_in_final_answer=True,
                    )
                )
            db.commit()
