from __future__ import annotations

import logging

from app.config.settings import settings
from app.chunking.chunker import TextChunker
from app.indexing.bm25.index import BM25Index
from app.indexing.dense.index import DenseTextIndex
from app.indexing.store import ArtifactStore
from app.indexing.visual.index import VisualPageIndex

logger = logging.getLogger(__name__)


class IndexManager:
    def __init__(
        self,
        store: ArtifactStore | None = None,
        bm25: BM25Index | None = None,
        dense: DenseTextIndex | None = None,
        visual: VisualPageIndex | None = None,
    ) -> None:
        self.store = store or ArtifactStore()
        self.bm25 = bm25 or BM25Index()
        self.dense = dense or DenseTextIndex()
        self.visual = visual or VisualPageIndex()
        self.chunker = TextChunker()
        self.store.ensure_artifact_files()

    def index_document(self, document_id: str) -> dict:
        pages = self.store.list_pages(document_id=document_id)
        if not pages:
            raise ValueError(f"No pages found for document_id={document_id}")
        chunks = self.chunker.chunk_pages(pages)
        self.store.upsert_chunks_for_document(document_id, chunks)
        all_chunks = self.store.list_chunks()
        all_pages = self.store.list_pages()

        self.bm25.build(all_chunks)
        self.dense.build(all_chunks)
        if settings.enable_visual_index:
            self.visual.build(all_pages)
        logger.info("Indexed document %s", document_id)
        return {
            "document_id": document_id,
            "pages_indexed": len(pages),
            "chunks_created": len(chunks),
            "visual_backend": self.visual.backend_info() if settings.enable_visual_index else "disabled",
            "total_chunks": len(all_chunks),
            "total_pages": len(all_pages),
        }

    def rebuild_all(self) -> dict:
        pages = self.store.list_pages()
        chunks = self.chunker.chunk_pages(pages)
        by_doc: dict[str, list] = {}
        for c in chunks:
            by_doc.setdefault(c.document_id, []).append(c)
        for doc_id, doc_chunks in by_doc.items():
            self.store.upsert_chunks_for_document(doc_id, doc_chunks)

        all_chunks = self.store.list_chunks()
        self.bm25.build(all_chunks)
        self.dense.build(all_chunks)
        if settings.enable_visual_index:
            self.visual.build(pages)
        return {
            "documents": len(self.store.list_documents()),
            "pages": len(pages),
            "chunks": len(all_chunks),
            "visual_backend": self.visual.backend_info() if settings.enable_visual_index else "disabled",
        }
