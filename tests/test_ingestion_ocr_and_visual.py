from __future__ import annotations

import uuid
import zipfile

import numpy as np

from app.ingestion.pdf_ingestor import PDFIngestor
from app.indexing.visual.index import VisualPageIndex
from app.ocr.ocr_engine import infer_page_flags, repair_split_words
from app.schemas.models import PageRecord


def _make_page() -> PageRecord:
    return PageRecord(
        course_id="course1",
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


def test_extract_docx_page_texts_preserves_page_breaks(tmp_path) -> None:  # noqa: ANN001
    docx_path = tmp_path / "sample.docx"
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>Page one line</w:t></w:r></w:p>"
        '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
        "<w:p><w:r><w:t>Page two line</w:t></w:r></w:p>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr("word/document.xml", xml)
    pages = PDFIngestor.extract_docx_page_texts(docx_path)
    assert len(pages) == 2
    assert "Page one line" in pages[0]
    assert "Page two line" in pages[1]


def test_extract_pptx_slide_texts_returns_slides_as_pages(tmp_path) -> None:  # noqa: ANN001
    pptx_path = tmp_path / "sample.pptx"
    slide1 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Slide 1 title</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>"
        "</p:sld>"
    )
    slide2 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Slide 2 text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>"
        "</p:sld>"
    )
    with zipfile.ZipFile(pptx_path, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide1)
        zf.writestr("ppt/slides/slide2.xml", slide2)
    slides = PDFIngestor.extract_pptx_slide_texts(pptx_path)
    assert len(slides) == 2
    assert "Slide 1 title" in slides[0]
    assert "Slide 2 text" in slides[1]


def test_ingest_docx_uses_paginated_rendered_pdf(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    ingestor = PDFIngestor()
    source = tmp_path / "sample.docx"
    source.write_bytes(b"fake-docx")
    doc_id = str(uuid.uuid4())

    monkeypatch.setattr(ingestor, "copy_source", lambda source_path, course_id, suffix: (doc_id, source))
    monkeypatch.setattr(ingestor, "_render_docx_to_pdf", lambda docx_path, rendered_pdf_path: None)
    sample_page = PageRecord(
        course_id="c1",
        document_id=doc_id,
        document_title="Doc",
        page_id=f"{doc_id}_p1",
        page_number=1,
        image_path="/tmp/p1.png",
        pdf_text_raw="txt",
        ocr_text_raw="",
        ocr_text_clean="",
        merged_text="txt",
        text_source="docx",
        pdf_text_quality=0.9,
        ocr_text_quality=0.0,
        language="en",
        has_diagram=False,
        has_table=False,
        has_code_like_text=False,
        has_large_image=False,
    )
    monkeypatch.setattr(
        ingestor,
        "_extract_pages_from_pdf",
        lambda **kwargs: [sample_page],  # noqa: ARG005
    )
    monkeypatch.setattr(ingestor.store, "create_document", lambda *args, **kwargs: None)  # noqa: ARG005
    monkeypatch.setattr(ingestor.store, "create_pages", lambda *args, **kwargs: None)  # noqa: ARG005
    monkeypatch.setattr(ingestor.store, "upsert_chunks_for_document", lambda *args, **kwargs: None)  # noqa: ARG005
    monkeypatch.setattr(ingestor.store, "update_document_status", lambda *args, **kwargs: None)  # noqa: ARG005
    monkeypatch.setattr(ingestor.chunker, "chunk_pages", lambda pages: [])  # noqa: ARG005

    doc = ingestor.ingest_docx(source_path=source, course_id="c1", title="Doc")
    assert doc.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert doc.page_count == 1


def test_ingest_docx_without_renderer_raises_when_fallback_disabled(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    ingestor = PDFIngestor()
    source = tmp_path / "sample.docx"
    source.write_bytes(b"fake-docx")
    doc_id = str(uuid.uuid4())
    monkeypatch.setattr(ingestor, "copy_source", lambda source_path, course_id, suffix: (doc_id, source))
    monkeypatch.setattr(
        ingestor,
        "_render_docx_to_pdf",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no renderer")),
    )
    monkeypatch.setattr("app.ingestion.pdf_ingestor.settings.docx_allow_fallback_pseudopagination", False)

    try:
        ingestor.ingest_docx(source_path=source, course_id="c1", title="Doc")
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "DOCX pagination requires a render backend" in str(exc)
