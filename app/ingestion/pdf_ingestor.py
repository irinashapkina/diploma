from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

import fitz
from PIL import Image

from app.config.settings import settings
from app.ocr.ocr_engine import OCREngine, infer_page_flags
from app.schemas.models import DocumentRecord, PageRecord, path_to_str
from app.utils.io import read_jsonl, write_json, write_jsonl
from app.utils.text import detect_language

logger = logging.getLogger(__name__)


class PDFIngestor:
    def __init__(self, ocr_engine: OCREngine | None = None) -> None:
        self.ocr_engine = ocr_engine or OCREngine(settings.tesseract_langs)
        self.documents_registry = settings.artifacts_dir / "documents.jsonl"
        self.pages_registry = settings.artifacts_dir / "pages.jsonl"

    def copy_pdf(self, source_path: Path) -> tuple[str, Path]:
        document_id = str(uuid.uuid4())
        target = settings.documents_dir / f"{document_id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        return document_id, target

    def ingest_pdf(self, source_path: Path, title: str | None = None) -> DocumentRecord:
        document_id, copied_pdf = self.copy_pdf(source_path)
        doc_title = title or source_path.stem
        page_dir = settings.pages_dir / document_id
        page_dir.mkdir(parents=True, exist_ok=True)

        pdf = fitz.open(copied_pdf)
        page_records: list[PageRecord] = []
        for idx in range(len(pdf)):
            page = pdf[idx]
            pix = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
            image_path = page_dir / f"page_{idx + 1:04d}.png"
            pix.save(image_path)

            pil_img = Image.open(image_path)
            raw_text, clean_text = self.ocr_engine.run(pil_img)
            flags = infer_page_flags(clean_text)
            language = detect_language(clean_text)

            page_record = PageRecord(
                document_id=document_id,
                document_title=doc_title,
                page_id=f"{document_id}_p{idx + 1}",
                page_number=idx + 1,
                image_path=path_to_str(image_path.resolve()),
                ocr_text_raw=raw_text,
                ocr_text_clean=clean_text,
                language=language,
                has_diagram=flags["has_diagram"],
                has_table=flags["has_table"],
                has_code_like_text=flags["has_code_like_text"],
            )
            page_records.append(page_record)

        document = DocumentRecord(
            document_id=document_id,
            document_title=doc_title,
            source_pdf=path_to_str(copied_pdf.resolve()),
            page_count=len(page_records),
        )
        self._append_document(document)
        self._append_pages(page_records)
        write_json(settings.artifacts_dir / "last_ingest.json", document.model_dump())
        logger.info("Ingested %s pages for %s", len(page_records), doc_title)
        return document

    def _append_document(self, doc: DocumentRecord) -> None:
        existing = read_jsonl(self.documents_registry)
        existing.append(doc.model_dump())
        write_jsonl(self.documents_registry, existing)

    def _append_pages(self, pages: list[PageRecord]) -> None:
        existing = read_jsonl(self.pages_registry)
        existing.extend(p.model_dump() for p in pages)
        write_jsonl(self.pages_registry, existing)
