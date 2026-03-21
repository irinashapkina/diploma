from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.indexing.index_manager import IndexManager
from app.indexing.store import ArtifactStore
from app.ingestion.pdf_ingestor import PDFIngestor
from app.pipeline.rag_pipeline import RAGPipeline
from app.schemas.models import AskRequest, AskResponse
from app.utils.logging import setup_logging

setup_logging(logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")
store = ArtifactStore()
ingestor = PDFIngestor()
index_manager = IndexManager()
pipeline = RAGPipeline()


class IndexRequest(BaseModel):
    document_id: str | None = None
    rebuild_all: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    doc = ingestor.ingest_pdf(tmp_path, title=Path(file.filename).stem)
    tmp_path.unlink(missing_ok=True)
    return {"status": "uploaded", "document": doc.model_dump()}


@app.post("/documents/index")
def index_document(req: IndexRequest) -> dict[str, Any]:
    try:
        if req.rebuild_all:
            result = index_manager.rebuild_all()
        elif req.document_id:
            result = index_manager.index_document(req.document_id)
        else:
            raise HTTPException(status_code=400, detail="Provide document_id or rebuild_all=true.")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "indexed", "result": result}


@app.get("/documents")
def list_documents() -> dict[str, Any]:
    docs = [d.model_dump() for d in store.list_documents()]
    return {"documents": docs}


@app.get("/documents/{document_id}/pages")
def list_document_pages(document_id: str) -> dict[str, Any]:
    pages = [p.model_dump() for p in store.list_pages(document_id=document_id)]
    if not pages:
        raise HTTPException(status_code=404, detail="Document not found or has no pages.")
    return {"document_id": document_id, "pages": pages}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Empty question.")
    return pipeline.ask(question=req.question, top_k=req.top_k, debug=req.debug)

