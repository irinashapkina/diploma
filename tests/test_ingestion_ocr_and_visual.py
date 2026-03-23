from __future__ import annotations

import numpy as np

from app.ingestion.pdf_ingestor import PDFIngestor
from app.indexing.visual.index import VisualPageIndex
from app.ocr.ocr_engine import infer_page_flags, repair_split_words
from app.schemas.models import PageRecord


def _make_page() -> PageRecord:
    return PageRecord(
        document_id="doc1",
        document_title="Doc",
        page_id="doc1_p1",
        page_number=1,
        image_path="/tmp/fake.png",
        pdf_text_raw="Architecture of RAM machine",
        ocr_text_raw="",
        ocr_text_clean="",
        merged_text="Architecture of RAM machine",
        text_source="pdf",
        pdf_text_quality=0.9,
        ocr_text_quality=0.0,
        language="en",
        has_diagram=True,
        has_table=False,
        has_code_like_text=False,
        has_large_image=True,
    )


def test_pdf_text_preferred_over_ocr() -> None:
    merged, source = PDFIngestor.merge_pdf_and_ocr_text(
        pdf_text_raw="Java RAM architecture",
        ocr_text_raw="gava ay oe",
        ocr_text_clean="gava ay oe",
    )
    assert source == "pdf+ocr"
    assert "Java RAM architecture" in merged
    assert "gava ay oe" not in merged


def test_merge_repairs_split_words() -> None:
    assert "Архитектура" in repair_split_words("Архитекту ра фон Неймана")


def test_has_diagram_detects_architecture_slide() -> None:
    flags = infer_page_flags(
        "Architecture diagram memory ALU stack heap",
        layout_blocks=[{"text": "CPU"}, {"text": "ALU"}, {"text": "RAM"}, {"text": "I/O"}] * 4,
        drawings_count=10,
        images_count=1,
        page_area=1000.0,
        image_area=300.0,
    )
    assert flags["has_diagram"] is True


def test_visual_backend_clip(monkeypatch) -> None:
    v = VisualPageIndex(backend="clip")
    monkeypatch.setattr(v, "_build_clip_embeddings", lambda image_paths: np.zeros((len(image_paths), 8), dtype=np.float32))
    v.build([_make_page()])
    assert v.backend_info() == "clip"


def test_visual_backend_colqwen2_fallback(monkeypatch) -> None:
    v = VisualPageIndex(backend="colqwen2")

    def _raise(_: list[str]) -> np.ndarray:
        raise RuntimeError("colqwen2 unavailable")

    monkeypatch.setattr(v, "_build_colqwen2_embeddings", _raise)
    monkeypatch.setattr(v, "_build_clip_embeddings", lambda image_paths: np.ones((len(image_paths), 8), dtype=np.float32))
    v.build([_make_page()])
    assert v.backend_info() == "clip"


def test_visual_search_dim_mismatch_does_not_crash(monkeypatch) -> None:
    v = VisualPageIndex(backend="clip")
    v.page_ids = ["doc1_p1"]
    v.image_paths = ["/tmp/fake.png"]
    v.embeddings = np.ones((1, 8), dtype=np.float32)
    monkeypatch.setattr(v, "_encode_text_clip", lambda query: np.ones((512,), dtype=np.float32))
    monkeypatch.setattr(v, "_rebuild_after_dim_mismatch", lambda expected_dim: False)
    hits = v.search("what is on diagram", top_k=3)
    assert hits == []
