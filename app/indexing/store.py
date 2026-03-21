from __future__ import annotations

from pathlib import Path

from app.config.settings import settings
from app.schemas.models import ChunkRecord, DocumentRecord, PageRecord
from app.utils.io import read_jsonl, write_jsonl


class ArtifactStore:
    def __init__(self) -> None:
        self.documents_path = settings.artifacts_dir / "documents.jsonl"
        self.pages_path = settings.artifacts_dir / "pages.jsonl"
        self.chunks_path = settings.artifacts_dir / "chunks.jsonl"

    def list_documents(self) -> list[DocumentRecord]:
        return [DocumentRecord(**x) for x in read_jsonl(self.documents_path)]

    def list_pages(self, document_id: str | None = None) -> list[PageRecord]:
        pages = [PageRecord(**x) for x in read_jsonl(self.pages_path)]
        if document_id:
            pages = [p for p in pages if p.document_id == document_id]
        return pages

    def list_chunks(self, document_id: str | None = None) -> list[ChunkRecord]:
        chunks = [ChunkRecord(**x) for x in read_jsonl(self.chunks_path)]
        if document_id:
            chunks = [c for c in chunks if c.document_id == document_id]
        return chunks

    def upsert_chunks_for_document(self, document_id: str, chunks: list[ChunkRecord]) -> None:
        existing = self.list_chunks()
        kept = [c for c in existing if c.document_id != document_id]
        kept.extend(chunks)
        write_jsonl(self.chunks_path, [c.model_dump() for c in kept])

    def ensure_artifact_files(self) -> None:
        for p in [self.documents_path, self.pages_path, self.chunks_path]:
            p.parent.mkdir(parents=True, exist_ok=True)
            if not Path(p).exists():
                write_jsonl(p, [])

