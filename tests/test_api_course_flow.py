from __future__ import annotations

import asyncio
import io
import uuid

from starlette.datastructures import UploadFile

from app.api.main import (
    CourseCreateRequest,
    IndexRequest,
    TeacherCreateRequest,
    ask,
    create_course,
    create_teacher,
    index_manager,
    index_course,
    ingestor,
    list_course_pages,
    list_courses,
    list_documents,
    pipeline,
    store,
    upload_document,
)
from app.schemas.models import AskRequest, AskResponse, ChunkRecord, DocumentRecord, PageRecord, SourceItem


def _create_teacher_and_course() -> tuple[str, str]:
    teacher = create_teacher(TeacherCreateRequest(full_name=f"Teacher-{uuid.uuid4()}"))
    course = create_course(
        CourseCreateRequest(
            teacher_id=teacher.teacher_id,
            title=f"Course-{uuid.uuid4()}",
            year_label="2025/2026",
            semester="autumn",
        )
    )
    return teacher.teacher_id, course.course_id


def test_courses_api_flow() -> None:
    teacher_id, course_id = _create_teacher_and_course()
    courses = list_courses(teacher_id=teacher_id)["courses"]
    assert any(c["course_id"] == course_id for c in courses)


def test_course_scoped_upload_index_ask_flow(monkeypatch) -> None:
    _, course_id = _create_teacher_and_course()

    def _fake_ingest(tmp_path, course_id: str, title: str | None = None, uploader_teacher_id=None):  # noqa: ANN001
        doc_id = str(uuid.uuid4())
        doc = DocumentRecord(
            document_id=doc_id,
            course_id=course_id,
            document_title=title or "Doc",
            source_pdf=f"/tmp/{doc_id}.pdf",
            page_count=1,
        )
        store.create_document(doc, source_filename="fake.pdf", checksum_sha256=str(uuid.uuid4()))
        page = PageRecord(
            course_id=course_id,
            document_id=doc_id,
            document_title=doc.document_title,
            page_id=f"{doc_id}_p1",
            page_number=1,
            image_path=f"/tmp/{doc_id}_p1.png",
            pdf_text_raw="",
            ocr_text_raw="",
            ocr_text_clean="",
            merged_text="stack and heap",
            text_source="pdf",
            pdf_text_quality=0.9,
            ocr_text_quality=0.0,
            language="en",
            has_diagram=False,
            has_table=False,
            has_code_like_text=False,
            has_large_image=False,
        )
        store.create_pages([page])
        chunk = ChunkRecord(
            chunk_id=str(uuid.uuid4()),
            course_id=course_id,
            document_id=doc_id,
            document_title=doc.document_title,
            page_id=page.page_id,
            page_number=1,
            chunk_order=0,
            text="stack and heap",
            cleaned_text="stack and heap",
            normalized_text="stack heap",
            metadata={},
            image_path=page.image_path,
        )
        store.upsert_chunks_for_document(course_id=course_id, document_id=doc_id, chunks=[chunk])
        return doc

    monkeypatch.setattr(ingestor, "ingest_pdf", _fake_ingest)
    monkeypatch.setattr(index_manager, "index_document", lambda course_id, document_id: {"course_id": course_id, "document_id": document_id, "chunks": 1})
    monkeypatch.setattr(
        pipeline,
        "ask",
        lambda question, course_id, top_k, debug: AskResponse(
            answer="По материалам: stack и heap различаются.",
            confidence=0.8,
            mode="text",
            sources=[SourceItem(document_title="Doc", page=1, snippet="stack and heap", score=0.7, type="text")],
            debug={"course_id": course_id},
        ),
    )

    upload = UploadFile(filename="slides.pdf", file=io.BytesIO(b"%PDF-1.4 fake"))
    uploaded = asyncio.run(upload_document(course_id=course_id, file=upload))
    assert uploaded["status"] == "uploaded"
    document_id = uploaded["document"]["document_id"]

    docs = list_documents(course_id=course_id)["documents"]
    assert any(d["document_id"] == document_id for d in docs)

    pages = list_course_pages(course_id=course_id)["pages"]
    assert isinstance(pages, list)

    idx = index_course(course_id=course_id, req=IndexRequest(document_id=document_id))
    assert idx["status"] == "indexed"
    assert idx["result"]["course_id"] == course_id

    response = ask(
        course_id=course_id,
        req=AskRequest(course_id=course_id, question="чем стек отличается от кучи", top_k=4, debug=True),
    )
    assert response.answer is not None


def test_non_existing_course_errors() -> None:
    missing = str(uuid.uuid4())
    upload = UploadFile(filename="slides.pdf", file=io.BytesIO(b"%PDF-1.4 fake"))
    try:
        asyncio.run(upload_document(course_id=missing, file=upload))
        raise AssertionError("Expected exception for missing course")
    except Exception:
        pass


def test_upload_docx_uses_docx_ingestor(monkeypatch) -> None:
    _, course_id = _create_teacher_and_course()

    def _fake_ingest_docx(tmp_path, course_id: str, title: str | None = None, uploader_teacher_id=None, source_filename=None):  # noqa: ANN001
        return DocumentRecord(
            document_id=str(uuid.uuid4()),
            course_id=course_id,
            document_title=title or "Docx",
            source_pdf=f"/tmp/{uuid.uuid4()}.docx",
            page_count=2,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            source_filename=source_filename or "material.docx",
        )

    monkeypatch.setattr(ingestor, "ingest_docx", _fake_ingest_docx)
    upload = UploadFile(filename="material.docx", file=io.BytesIO(b"PK\x03\x04fake-docx"))
    result = asyncio.run(upload_document(course_id=course_id, file=upload))

    assert result["status"] == "uploaded"
    assert result["document"]["mime_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_upload_pptx_uses_pptx_ingestor(monkeypatch) -> None:
    _, course_id = _create_teacher_and_course()

    def _fake_ingest_pptx(tmp_path, course_id: str, title: str | None = None, uploader_teacher_id=None, source_filename=None):  # noqa: ANN001
        return DocumentRecord(
            document_id=str(uuid.uuid4()),
            course_id=course_id,
            document_title=title or "Slides",
            source_pdf=f"/tmp/{uuid.uuid4()}.pptx",
            page_count=3,
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            source_filename=source_filename or "slides.pptx",
        )

    monkeypatch.setattr(ingestor, "ingest_pptx", _fake_ingest_pptx)
    upload = UploadFile(filename="slides.pptx", file=io.BytesIO(b"PK\x03\x04fake-pptx"))
    result = asyncio.run(upload_document(course_id=course_id, file=upload))

    assert result["status"] == "uploaded"
    assert result["document"]["mime_type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
