from __future__ import annotations

import uuid

import pytest

from app.chunking.chunker import TextChunker
from app.indexing.bm25.index import BM25Hit
from app.indexing.dense.index import DenseHit
from app.indexing.index_manager import IndexManager
from app.indexing.store import ArtifactStore
from app.pipeline.rag_pipeline import RAGPipeline
from app.retrieval.hybrid import HybridRetriever
from app.schemas.models import AskRequest, ChunkRecord, DocumentRecord, PageRecord


def _course(store: ArtifactStore, suffix: str = "") -> tuple[str, str]:
    teacher = store.create_teacher(f"Teacher{suffix}-{uuid.uuid4()}")
    course = store.create_course(
        teacher_id=teacher.teacher_id,
        title=f"Course{suffix}-{uuid.uuid4()}",
        year_label="2025/2026",
        semester="autumn",
    )
    return teacher.teacher_id, course.course_id


def test_create_teacher_and_course() -> None:
    store = ArtifactStore()
    teacher_id, course_id = _course(store, suffix="a")
    assert teacher_id
    assert store.get_course(course_id) is not None


def test_year_label_validation() -> None:
    with pytest.raises(Exception):
        store = ArtifactStore()
        teacher = store.create_teacher("Bad Year Teacher")
        store.create_course(teacher_id=teacher.teacher_id, title="Bad", year_label="2025/2027")


def test_page_chunk_persistence_with_course_id() -> None:
    store = ArtifactStore()
    _, course_id = _course(store, suffix="b")
    doc = DocumentRecord(
        document_id=str(uuid.uuid4()),
        course_id=course_id,
        document_title="Doc",
        source_pdf="/tmp/doc.pdf",
        page_count=1,
    )
    store.create_document(doc, source_filename="doc.pdf", checksum_sha256=str(uuid.uuid4()))
    page = PageRecord(
        course_id=course_id,
        document_id=doc.document_id,
        document_title=doc.document_title,
        page_id=f"{doc.document_id}_p1",
        page_number=1,
        image_path="/tmp/p1.png",
        pdf_text_raw="RAM",
        ocr_text_raw="",
        ocr_text_clean="",
        merged_text="RAM machine architecture with ALU and control unit. " * 8,
        text_source="pdf",
        pdf_text_quality=0.9,
        ocr_text_quality=0.0,
        language="en",
        has_diagram=True,
        has_table=False,
        has_code_like_text=False,
        has_large_image=False,
    )
    store.create_pages([page])
    chunks = TextChunker().chunk_pages([page])
    store.upsert_chunks_for_document(course_id=course_id, document_id=doc.document_id, chunks=chunks)
    assert len(store.list_pages(course_id=course_id, document_id=doc.document_id)) == 1
    assert len(store.list_chunks(course_id=course_id, document_id=doc.document_id)) >= 1


def test_retrieval_isolation_by_course_id() -> None:
    store = ArtifactStore()
    _, c1 = _course(store, suffix="c1")
    _, c2 = _course(store, suffix="c2")

    doc1 = DocumentRecord(document_id=str(uuid.uuid4()), course_id=c1, document_title="D1", source_pdf="/tmp/1.pdf", page_count=1)
    doc2 = DocumentRecord(document_id=str(uuid.uuid4()), course_id=c2, document_title="D2", source_pdf="/tmp/2.pdf", page_count=1)
    store.create_document(doc1, source_filename="1.pdf", checksum_sha256=str(uuid.uuid4()))
    store.create_document(doc2, source_filename="2.pdf", checksum_sha256=str(uuid.uuid4()))
    p1 = PageRecord(
        course_id=c1,
        document_id=doc1.document_id,
        document_title="D1",
        page_id=f"{doc1.document_id}_p1",
        page_number=1,
        image_path="/tmp/a.png",
        pdf_text_raw="stack",
        ocr_text_raw="",
        ocr_text_clean="",
        merged_text="stack stores primitive values",
        text_source="pdf",
        pdf_text_quality=0.9,
        ocr_text_quality=0.0,
        language="en",
        has_diagram=False,
        has_table=False,
        has_code_like_text=False,
        has_large_image=False,
    )
    p2 = p1.model_copy(update={"course_id": c2, "document_id": doc2.document_id, "document_title": "D2", "page_id": f"{doc2.document_id}_p1"})
    store.create_pages([p1, p2])
    ch1 = ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        course_id=c1,
        document_id=doc1.document_id,
        document_title="D1",
        page_id=p1.page_id,
        page_number=1,
        chunk_order=0,
        text="stack stores primitive values",
        cleaned_text="stack stores primitive values",
        normalized_text="stack store primitiv valu",
        metadata={},
        image_path="/tmp/a.png",
    )
    ch2 = ch1.model_copy(
        update={
            "chunk_id": str(uuid.uuid4()),
            "course_id": c2,
            "document_id": doc2.document_id,
            "document_title": "D2",
            "page_id": p2.page_id,
            "text": "heap stores reference values",
            "cleaned_text": "heap stores reference values",
            "normalized_text": "heap store refer valu",
        }
    )
    store.upsert_chunks_for_document(c1, doc1.document_id, [ch1])
    store.upsert_chunks_for_document(c2, doc2.document_id, [ch2])

    class _BM25:
        def set_course_scope(self, course_id: str) -> None:
            return

        def search(self, query: str, top_k: int = 8):
            return [BM25Hit(chunk_id=ch1.chunk_id, score=1.0), BM25Hit(chunk_id=ch2.chunk_id, score=0.99)]

    class _Dense:
        def set_course_scope(self, course_id: str) -> None:
            return

        def search(self, query: str, top_k: int = 8):
            return [DenseHit(chunk_id=ch2.chunk_id, score=0.9)]

    class _Visual:
        def set_course_scope(self, course_id: str) -> None:
            return

        def search(self, query: str, top_k: int = 6):
            return []

    retriever = HybridRetriever(store=store, bm25=_BM25(), dense=_Dense(), visual=_Visual())  # type: ignore[arg-type]
    out, _ = retriever.retrieve(query="stack", course_id=c1, mode="text", top_k=5, query_forms=["stack"])
    assert out
    assert all(c.document_id == doc1.document_id for c in out)


def test_ask_without_course_id_forbidden() -> None:
    with pytest.raises(Exception):
        AskRequest(question="hello", top_k=2, debug=False)  # course_id is required
    with pytest.raises(ValueError):
        RAGPipeline().ask(question="hello", course_id="")


def test_indices_metadata_is_written_on_index_course() -> None:
    class _Store:
        def __init__(self) -> None:
            self.index_updates: list[dict] = []
            self._pages = [
                PageRecord(
                    course_id="c1",
                    document_id="d1",
                    document_title="Doc",
                    page_id="d1_p1",
                    page_number=1,
                    image_path="/tmp/p1.png",
                    pdf_text_raw="",
                    ocr_text_raw="",
                    ocr_text_clean="",
                    merged_text="A long enough chunk text. " * 10,
                    text_source="pdf",
                    pdf_text_quality=0.9,
                    ocr_text_quality=0.0,
                    language="en",
                    has_diagram=False,
                    has_table=False,
                    has_code_like_text=False,
                    has_large_image=False,
                )
            ]
            self._chunks: list[ChunkRecord] = []

        def ensure_artifact_files(self) -> None:
            return

        def list_pages(self, course_id: str, document_id: str | None = None):
            return self._pages

        def upsert_chunks_for_document(self, course_id: str, document_id: str, chunks: list[ChunkRecord]) -> None:
            self._chunks = chunks

        def list_chunks(self, course_id: str):
            return self._chunks

        def list_documents(self, course_id: str):
            return [DocumentRecord(document_id="d1", course_id=course_id, document_title="Doc", source_pdf="/tmp/doc.pdf", page_count=1)]

        def upsert_index_metadata(self, **kwargs):
            self.index_updates.append(kwargs)

    class _BM25:
        def __init__(self):
            self.path = "/tmp/bm25.json"

        def set_course_scope(self, course_id: str) -> None:
            return

        def build(self, chunks):  # noqa: ANN001
            return

    class _Dense:
        def __init__(self):
            self.backend = "numpy"
            self.path_embeddings = "/tmp/dense.npy"
            self.path_index = "/tmp/dense.index"
            self.model_name = "dummy"

        def set_course_scope(self, course_id: str) -> None:
            return

        def build(self, chunks):  # noqa: ANN001
            return

    class _Visual:
        def __init__(self):
            self.path_embeddings = "/tmp/visual.npy"
            self.embedding_dim = 512

        def set_course_scope(self, course_id: str) -> None:
            return

        def build(self, pages):  # noqa: ANN001
            return

        def backend_info(self) -> str:
            return "clip"

    store = _Store()
    manager = IndexManager(store=store, bm25=_BM25(), dense=_Dense(), visual=_Visual())  # type: ignore[arg-type]
    manager.index_course("c1")
    index_types = {row["index_type"] for row in store.index_updates}
    assert {"bm25", "dense", "visual"} <= index_types
