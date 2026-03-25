from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config.settings import settings
from app.indexing.index_manager import IndexManager
from app.indexing.store import ArtifactStore
from app.ingestion.pdf_ingestor import PDFIngestor
from app.pipeline.rag_pipeline import RAGPipeline
from app.schemas.models import AskRequest, AskResponse, CourseRecord, TeacherRecord
from app.services.java_material_review_service import JavaMaterialReviewService
from app.services.json_review_storage import JsonReviewStorage
from app.services.reference_sync_service import ReferenceSyncService
from app.utils.logging import setup_logging

setup_logging(logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = ArtifactStore()
ingestor = PDFIngestor()
index_manager = IndexManager()
pipeline = RAGPipeline()
review_storage = JsonReviewStorage()
reference_sync_service = ReferenceSyncService(storage=review_storage)
java_review_service = JavaMaterialReviewService(store=store, storage=review_storage)
project_root = Path(__file__).resolve().parents[2]
frontend_dir = project_root / "frontend"
frontend_dist_dir = frontend_dir / "dist"
frontend_assets_dir = frontend_dist_dir / "assets"
if frontend_assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_assets_dir)), name="ui_assets")
if settings.data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(settings.data_dir.resolve())), name="data")


class IndexRequest(BaseModel):
    document_id: str | None = None


class TeacherCreateRequest(BaseModel):
    full_name: str


class CourseCreateRequest(BaseModel):
    teacher_id: str
    title: str
    year_label: str
    semester: str | None = None
    description: str | None = None


class ReferenceSyncRequest(BaseModel):
    include_concepts: bool = True


class CourseScanRequest(BaseModel):
    use_current_baseline: bool = True


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def ui_index() -> FileResponse:
    index_path = frontend_dist_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI is not available.")
    return FileResponse(index_path)


@app.post("/teachers", response_model=TeacherRecord)
def create_teacher(req: TeacherCreateRequest) -> TeacherRecord:
    return store.create_teacher(full_name=req.full_name)


@app.get("/teachers/{teacher_id}", response_model=TeacherRecord)
def get_teacher(teacher_id: str) -> TeacherRecord:
    teacher = store.get_teacher(teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail=f"Teacher not found: {teacher_id}")
    return teacher


@app.post("/courses", response_model=CourseRecord)
def create_course(req: CourseCreateRequest) -> CourseRecord:
    try:
        return store.create_course(
            teacher_id=req.teacher_id,
            title=req.title,
            year_label=req.year_label,
            semester=req.semester,
            description=req.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/courses")
def list_courses(teacher_id: str | None = None) -> dict[str, Any]:
    courses = [c.model_dump() for c in store.list_courses(teacher_id=teacher_id)]
    return {"courses": courses}


@app.post("/courses/{course_id}/documents/upload")
async def upload_document(course_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        doc = ingestor.ingest_pdf(
            tmp_path,
            course_id=course_id,
            title=Path(file.filename).stem,
            source_filename=file.filename,
        )
    except TypeError:
        # Backward-compatible fallback for patched/mocked ingestors
        doc = ingestor.ingest_pdf(tmp_path, course_id=course_id, title=Path(file.filename).stem)
    tmp_path.unlink(missing_ok=True)
    return {"status": "uploaded", "document": doc.model_dump()}


@app.post("/courses/{course_id}/index")
def index_course(course_id: str, req: IndexRequest) -> dict[str, Any]:
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    try:
        if req.document_id:
            document = store.get_document(req.document_id)
            if not document or document.course_id != course_id:
                raise HTTPException(status_code=404, detail="Document not found in this course.")
            result = index_manager.index_document(course_id=course_id, document_id=req.document_id)
        else:
            result = index_manager.index_course(course_id=course_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "indexed", "result": result}


@app.get("/courses/{course_id}/documents")
def list_documents(course_id: str) -> dict[str, Any]:
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    docs = [d.model_dump() for d in store.list_documents(course_id=course_id)]
    return {"documents": docs}


@app.get("/courses/{course_id}/pages")
def list_course_pages(course_id: str, document_id: str | None = None) -> dict[str, Any]:
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    if document_id:
        document = store.get_document(document_id)
        if not document or document.course_id != course_id:
            raise HTTPException(status_code=404, detail="Document not found in this course.")
    pages = [p.model_dump() for p in store.list_pages(course_id=course_id, document_id=document_id)]
    return {"course_id": course_id, "document_id": document_id, "pages": pages}


@app.get("/courses/{course_id}/documents/{document_id}/pages")
def list_document_pages(course_id: str, document_id: str) -> dict[str, Any]:
    document = store.get_document(document_id)
    if not document or document.course_id != course_id:
        raise HTTPException(status_code=404, detail="Document not found in this course.")
    pages = [p.model_dump() for p in store.list_pages(course_id=course_id, document_id=document_id)]
    if not pages:
        raise HTTPException(status_code=404, detail="Document not found or has no pages.")
    return {"course_id": course_id, "document_id": document_id, "pages": pages}


@app.post("/courses/{course_id}/ask", response_model=AskResponse)
def ask(course_id: str, req: AskRequest) -> AskResponse:
    if req.course_id != course_id:
        raise HTTPException(status_code=400, detail="course_id in path and body must match.")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Empty question.")
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    return pipeline.ask(question=req.question, course_id=course_id, top_k=req.top_k, debug=req.debug)


@app.post("/review/reference/sync")
def sync_reference(req: ReferenceSyncRequest) -> dict[str, Any]:
    summary = reference_sync_service.sync(include_concepts=req.include_concepts)
    return {"status": "ok", "summary": summary}


@app.get("/review/reference/baseline")
def get_reference_baseline(run_id: str | None = None) -> dict[str, Any]:
    payload = review_storage.get_reference_snapshot(run_id) if run_id else review_storage.get_reference_baseline()
    if not payload:
        raise HTTPException(status_code=404, detail="Reference baseline not found. Run /review/reference/sync first.")
    return payload


@app.post("/review/courses/{course_id}/scan")
def scan_course_materials(course_id: str, req: CourseScanRequest) -> dict[str, Any]:
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    baseline_payload = review_storage.get_reference_baseline() if req.use_current_baseline else {}
    baseline = baseline_payload.get("baseline", {})
    try:
        summary = java_review_service.scan_course(course_id=course_id, baseline=baseline)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "summary": summary}


@app.get("/review/courses/{course_id}/issues")
def get_course_issues(course_id: str) -> dict[str, Any]:
    if store.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    issues = review_storage.get_scan_issues(course_id)
    latest_scan = review_storage.get_scan_latest(course_id)
    return {"course_id": course_id, "scan": latest_scan, "issues": issues}
