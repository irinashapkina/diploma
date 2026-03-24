from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path
import hashlib

import fitz
from PIL import Image

from app.config.settings import settings
from app.indexing.store import ArtifactStore
from app.ocr.ocr_engine import OCREngine, estimate_text_quality, infer_page_flags
from app.schemas.models import DocumentRecord, PageRecord, path_to_str
from app.utils.io import write_json
from app.utils.text import detect_language, normalize_for_retrieval

logger = logging.getLogger(__name__)


class PDFIngestor:
    def __init__(self, ocr_engine: OCREngine | None = None) -> None:
        self.ocr_engine = ocr_engine or OCREngine(settings.tesseract_langs)
        self.store = ArtifactStore()

    def copy_pdf(self, source_path: Path, course_id: str) -> tuple[str, Path]:
        document_id = str(uuid.uuid4())
        target = settings.documents_dir / course_id / f"{document_id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        return document_id, target

    def ingest_pdf(
        self,
        source_path: Path,
        course_id: str,
        title: str | None = None,
        uploader_teacher_id: str | None = None,
    ) -> DocumentRecord:
        document_id, copied_pdf = self.copy_pdf(source_path, course_id=course_id)
        doc_title = title or source_path.stem
        page_dir = settings.pages_dir / course_id / document_id
        page_dir.mkdir(parents=True, exist_ok=True)

        pdf = fitz.open(copied_pdf)
        page_records: list[PageRecord] = []
        for idx in range(len(pdf)):
            page = pdf[idx]
            pdf_text_blocks = self.extract_pdf_text_blocks(page)
            pdf_text_raw = clean_join_blocks(pdf_text_blocks)
            pdf_quality = self.estimate_pdf_text_quality(pdf_text_raw, pdf_text_blocks)
            images_count, image_area = self._estimate_images(page)
            drawings_count = len(page.get_drawings())
            page_area = float(page.rect.width * page.rect.height)
            has_large_image = bool(page_area and image_area / max(page_area, 1.0) >= 0.20)

            pix = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
            image_path = page_dir / f"page_{idx + 1:04d}.png"
            pix.save(image_path)

            ocr_raw, ocr_clean = "", ""
            if self.should_run_ocr(
                pdf_text_raw=pdf_text_raw,
                pdf_quality=pdf_quality,
                has_large_image=has_large_image,
                drawings_count=drawings_count,
                images_count=images_count,
            ):
                pil_img = Image.open(image_path)
                ocr_raw, ocr_clean = self.ocr_engine.run(pil_img)

            merged_text, text_source = self.merge_pdf_and_ocr_text(
                pdf_text_raw=pdf_text_raw,
                ocr_text_raw=ocr_raw,
                ocr_text_clean=ocr_clean,
            )
            ocr_quality = estimate_text_quality(ocr_clean)
            flags = infer_page_flags(
                merged_text,
                layout_blocks=page.get_text("blocks"),
                drawings_count=drawings_count,
                images_count=images_count,
                page_area=page_area,
                image_area=image_area,
            )
            language = detect_language(merged_text)

            page_record = PageRecord(
                course_id=course_id,
                document_id=document_id,
                document_title=doc_title,
                page_id=f"{document_id}_p{idx + 1}",
                page_number=idx + 1,
                image_path=path_to_str(image_path.resolve()),
                pdf_text_raw=pdf_text_raw,
                ocr_text_raw=ocr_raw,
                ocr_text_clean=ocr_clean,
                merged_text=merged_text,
                text_source=text_source,
                pdf_text_quality=pdf_quality,
                ocr_text_quality=ocr_quality,
                language=language,
                has_diagram=flags["has_diagram"],
                has_table=flags["has_table"],
                has_code_like_text=flags["has_code_like_text"],
                has_large_image=has_large_image,
            )
            page_records.append(page_record)

        document = DocumentRecord(
            document_id=document_id,
            course_id=course_id,
            document_title=doc_title,
            source_pdf=path_to_str(copied_pdf.resolve()),
            page_count=len(page_records),
        )
        checksum = hashlib.sha256(copied_pdf.read_bytes()).hexdigest()
        self.store.create_document(
            document,
            uploader_teacher_id=uploader_teacher_id,
            source_filename=source_path.name,
            checksum_sha256=checksum,
        )
        self.store.update_document_status(document.document_id, status="ingested")
        self.store.create_pages(page_records)
        write_json(settings.artifacts_dir / "last_ingest.json", document.model_dump())
        logger.info("Ingested %s pages for %s", len(page_records), doc_title)
        return document

    @staticmethod
    def extract_pdf_text_blocks(page: fitz.Page) -> list[str]:
        blocks: list[str] = []
        raw = page.get_text("dict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            line_texts: list[str] = []
            for line in lines:
                spans = line.get("spans", [])
                txt = "".join(str(sp.get("text", "")) for sp in spans).strip()
                if txt:
                    line_texts.append(txt)
            block_text = "\n".join(line_texts).strip()
            if block_text:
                blocks.append(block_text)
        return blocks

    @staticmethod
    def estimate_pdf_text_quality(pdf_text_raw: str, pdf_text_blocks: list[str]) -> float:
        base_quality = estimate_text_quality(pdf_text_raw)
        blocks_bonus = min(0.2, 0.02 * len(pdf_text_blocks))
        text_len = len(pdf_text_raw)
        length_bonus = 0.2 if text_len >= 200 else (0.1 if text_len >= 80 else 0.0)
        return max(0.0, min(1.0, base_quality + blocks_bonus + length_bonus))

    @staticmethod
    def should_run_ocr(
        *,
        pdf_text_raw: str,
        pdf_quality: float,
        has_large_image: bool,
        drawings_count: int,
        images_count: int,
    ) -> bool:
        if not pdf_text_raw.strip():
            return True
        if len(pdf_text_raw.strip()) < 60:
            return True
        if pdf_quality < 0.45:
            return True
        if has_large_image or images_count >= 1 or drawings_count >= 10:
            return True
        return False

    @staticmethod
    def merge_pdf_and_ocr_text(
        *,
        pdf_text_raw: str,
        ocr_text_raw: str,
        ocr_text_clean: str,
    ) -> tuple[str, str]:
        pdf_text = clean_join_blocks([pdf_text_raw]) if pdf_text_raw else ""
        ocr_text = ocr_text_clean or ocr_text_raw or ""
        ocr_text = clean_join_blocks([ocr_text])
        if pdf_text and not ocr_text:
            return pdf_text, "pdf"
        if ocr_text and not pdf_text:
            return ocr_text, "ocr"
        if not pdf_text and not ocr_text:
            return "", "ocr"

        merged_lines = [ln.strip() for ln in pdf_text.splitlines() if ln.strip()]
        seen_norm = {normalize_for_retrieval(ln) for ln in merged_lines if ln.strip()}
        for line in (ln.strip() for ln in ocr_text.splitlines() if ln.strip()):
            if len(line) < 6:
                continue
            norm = normalize_for_retrieval(line)
            if not norm:
                continue
            if norm in seen_norm:
                continue
            if _overlaps_existing(norm, seen_norm):
                continue
            merged_lines.append(line)
            seen_norm.add(norm)
        return "\n".join(merged_lines).strip(), "pdf+ocr"

    @staticmethod
    def _estimate_images(page: fitz.Page) -> tuple[int, float]:
        image_rects: list[fitz.Rect] = []
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                image_rects.append(fitz.Rect(bbox))
        area = float(sum(max(0.0, rect.width * rect.height) for rect in image_rects))
        return len(image_rects), area

def clean_join_blocks(blocks: list[str]) -> str:
    lines: list[str] = []
    for block in blocks:
        for line in str(block).splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                lines.append(line)
    return "\n".join(lines).strip()


def _overlaps_existing(candidate_norm: str, seen_norm: set[str]) -> bool:
    cand_terms = set(candidate_norm.split())
    if not cand_terms:
        return True
    for existing in seen_norm:
        ext_terms = set(existing.split())
        overlap = len(cand_terms & ext_terms) / max(1, len(cand_terms))
        if overlap >= 0.75:
            return True
    return False
