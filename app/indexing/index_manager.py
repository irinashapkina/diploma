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

    def _persist_index_metadata(self, course_id: str, chunks_count: int, pages_count: int) -> None:
        self.store.upsert_index_metadata(
            course_id=course_id,
            index_type="bm25",
            backend="bm25",
            path=str(self.bm25.path),
            vector_dim=None,
            objects_count=chunks_count,
            model_name=None,
            status="ready",
        )
        self.store.upsert_index_metadata(
            course_id=course_id,
            index_type="dense",
            backend=self.dense.backend,
            path=str(self.dense.path_embeddings if self.dense.backend == "numpy" else self.dense.path_index),
            vector_dim=None,
            objects_count=chunks_count,
            model_name=self.dense.model_name,
            status="ready",
        )
        if settings.enable_visual_index:
            self.store.upsert_index_metadata(
                course_id=course_id,
                index_type="visual",
                backend=self.visual.backend_info(),
                path=str(self.visual.path_embeddings),
                vector_dim=self.visual.embedding_dim,
                objects_count=pages_count,
                model_name=settings.clip_model_name if self.visual.backend_info() == "clip" else settings.colqwen2_model_name,
                status="ready",
            )
        else:
            self.store.upsert_index_metadata(
                course_id=course_id,
                index_type="visual",
                backend="disabled",
                path=str(self.visual.path_embeddings),
                vector_dim=None,
                objects_count=0,
                model_name=None,
                status="ready",
            )

    def index_document(self, course_id: str, document_id: str) -> dict:
        self.bm25.set_course_scope(course_id)
        self.dense.set_course_scope(course_id)
        self.visual.set_course_scope(course_id)
        pages = self.store.list_pages(course_id=course_id, document_id=document_id)
        if not pages:
            raise ValueError(f"No pages found for document_id={document_id}")
        chunks = self.chunker.chunk_pages(pages)
        self.store.upsert_chunks_for_document(course_id, document_id, chunks)
        all_chunks = self.store.list_chunks(course_id=course_id)
        all_pages = self.store.list_pages(course_id=course_id)

        self.bm25.build(all_chunks)
        self.dense.build(all_chunks)
        if settings.enable_visual_index:
            self.visual.build(all_pages)
        self._persist_index_metadata(course_id=course_id, chunks_count=len(all_chunks), pages_count=len(all_pages))
        self.store.update_document_status(document_id, status="indexed")
        logger.info("Indexed document %s", document_id)
        return {
            "course_id": course_id,
            "document_id": document_id,
            "pages_indexed": len(pages),
            "chunks_created": len(chunks),
            "visual_backend": self.visual.backend_info() if settings.enable_visual_index else "disabled",
            "total_chunks": len(all_chunks),
            "total_pages": len(all_pages),
        }

    def index_course(self, course_id: str) -> dict:
        self.bm25.set_course_scope(course_id)
        self.dense.set_course_scope(course_id)
        self.visual.set_course_scope(course_id)
        pages = self.store.list_pages(course_id=course_id)
        chunks = self.chunker.chunk_pages(pages)
        by_doc: dict[str, list] = {}
        for c in chunks:
            by_doc.setdefault(c.document_id, []).append(c)
        for doc_id, doc_chunks in by_doc.items():
            self.store.upsert_chunks_for_document(course_id, doc_id, doc_chunks)

        all_chunks = self.store.list_chunks(course_id=course_id)
        self.bm25.build(all_chunks)
        self.dense.build(all_chunks)
        if settings.enable_visual_index:
            self.visual.build(pages)
        self._persist_index_metadata(course_id=course_id, chunks_count=len(all_chunks), pages_count=len(pages))
        for doc in self.store.list_documents(course_id=course_id):
            self.store.update_document_status(doc.document_id, status="indexed")
        return {
            "course_id": course_id,
            "documents": len(self.store.list_documents(course_id=course_id)),
            "pages": len(pages),
            "chunks": len(all_chunks),
            "visual_backend": self.visual.backend_info() if settings.enable_visual_index else "disabled",
        }
