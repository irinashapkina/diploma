from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz
from PIL import Image, ImageDraw

from app.chunking.chunker import TextChunker
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
        self.chunker = TextChunker()

    def copy_source(self, source_path: Path, course_id: str, suffix: str) -> tuple[str, Path]:
        document_id = str(uuid.uuid4())
        target = settings.documents_dir / course_id / f"{document_id}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        return document_id, target

    def copy_pdf(self, source_path: Path, course_id: str) -> tuple[str, Path]:
        return self.copy_source(source_path=source_path, course_id=course_id, suffix=".pdf")

    def ingest_pdf(
        self,
        source_path: Path,
        course_id: str,
        title: str | None = None,
        uploader_teacher_id: str | None = None,
        source_filename: str | None = None,
    ) -> DocumentRecord:
        document_id, copied_pdf = self.copy_pdf(source_path, course_id=course_id)
        doc_title = title or source_path.stem
        page_records = self._extract_pages_from_pdf(
            pdf_path=copied_pdf,
            course_id=course_id,
            document_id=document_id,
            document_title=doc_title,
            force_text_source=None,
        )

        return self._finalize_ingestion(
            document_id=document_id,
            copied_file=copied_pdf,
            page_records=page_records,
            course_id=course_id,
            title=doc_title,
            mime_type="application/pdf",
            uploader_teacher_id=uploader_teacher_id,
            source_filename=source_filename or source_path.name,
        )

    def ingest_docx(
        self,
        source_path: Path,
        course_id: str,
        title: str | None = None,
        uploader_teacher_id: str | None = None,
        source_filename: str | None = None,
    ) -> DocumentRecord:
        document_id, copied_docx = self.copy_source(source_path=source_path, course_id=course_id, suffix=".docx")
        rendered_pdf = settings.documents_dir / course_id / f"{document_id}.rendered.pdf"
        doc_title = title or source_path.stem
        try:
            self._render_docx_to_pdf(docx_path=copied_docx, rendered_pdf_path=rendered_pdf)
            page_records = self._extract_pages_from_pdf(
                pdf_path=rendered_pdf,
                course_id=course_id,
                document_id=document_id,
                document_title=doc_title,
                force_text_source="docx",
            )
        except Exception as exc:
            if not settings.docx_allow_fallback_pseudopagination:
                raise RuntimeError(
                    "DOCX pagination requires a render backend (LibreOffice `soffice` or `docx2pdf`). "
                    "Install one of them or explicitly enable fallback pseudo-pagination."
                ) from exc
            logger.warning("DOCX render pagination failed, fallback pseudo-pagination is used: %s", exc)
            page_texts = self.extract_docx_page_texts(copied_docx)
            page_records = self._build_text_pages(
                page_texts=page_texts,
                course_id=course_id,
                document_id=document_id,
                title=doc_title,
                text_source="docx",
            )
        return self._finalize_ingestion(
            document_id=document_id,
            copied_file=copied_docx,
            page_records=page_records,
            course_id=course_id,
            title=doc_title,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            uploader_teacher_id=uploader_teacher_id,
            source_filename=source_filename or source_path.name,
        )

    def ingest_pptx(
        self,
        source_path: Path,
        course_id: str,
        title: str | None = None,
        uploader_teacher_id: str | None = None,
        source_filename: str | None = None,
    ) -> DocumentRecord:
        document_id, copied_pptx = self.copy_source(source_path=source_path, course_id=course_id, suffix=".pptx")
        page_texts = self.extract_pptx_slide_texts(copied_pptx)
        page_records = self._build_text_pages(
            page_texts=page_texts,
            course_id=course_id,
            document_id=document_id,
            title=title or source_path.stem,
            text_source="pptx",
        )
        return self._finalize_ingestion(
            document_id=document_id,
            copied_file=copied_pptx,
            page_records=page_records,
            course_id=course_id,
            title=title or source_path.stem,
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            uploader_teacher_id=uploader_teacher_id,
            source_filename=source_filename or source_path.name,
        )

    def _finalize_ingestion(
        self,
        *,
        document_id: str,
        copied_file: Path,
        page_records: list[PageRecord],
        course_id: str,
        title: str,
        mime_type: str,
        uploader_teacher_id: str | None,
        source_filename: str,
    ) -> DocumentRecord:
        document = DocumentRecord(
            document_id=document_id,
            course_id=course_id,
            document_title=title,
            source_pdf=path_to_str(copied_file.resolve()),
            page_count=len(page_records),
            mime_type=mime_type,
            source_filename=source_filename,
        )
        checksum = hashlib.sha256(copied_file.read_bytes()).hexdigest()
        self.store.create_document(
            document,
            uploader_teacher_id=uploader_teacher_id,
            source_filename=source_filename,
            checksum_sha256=checksum,
        )
        self.store.create_pages(page_records)
        chunks = self.chunker.chunk_pages(page_records)
        self.store.upsert_chunks_for_document(course_id=course_id, document_id=document.document_id, chunks=chunks)
        self.store.update_document_status(document.document_id, status="ingested")
        write_json(settings.artifacts_dir / "last_ingest.json", document.model_dump())
        logger.info("Ingested %s pages for %s (%s)", len(page_records), title, mime_type)
        return document

    def _extract_pages_from_pdf(
        self,
        *,
        pdf_path: Path,
        course_id: str,
        document_id: str,
        document_title: str,
        force_text_source: str | None,
    ) -> list[PageRecord]:
        page_dir = settings.pages_dir / course_id / document_id
        page_dir.mkdir(parents=True, exist_ok=True)

        with fitz.open(pdf_path) as pdf:
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
                page_records.append(
                    PageRecord(
                        course_id=course_id,
                        document_id=document_id,
                        document_title=document_title,
                        page_id=f"{document_id}_p{idx + 1}",
                        page_number=idx + 1,
                        image_path=path_to_str(image_path.resolve()),
                        pdf_text_raw=pdf_text_raw,
                        ocr_text_raw=ocr_raw,
                        ocr_text_clean=ocr_clean,
                        merged_text=merged_text,
                        text_source=(force_text_source or text_source),  # type: ignore[arg-type]
                        pdf_text_quality=pdf_quality,
                        ocr_text_quality=ocr_quality,
                        language=language,
                        has_diagram=flags["has_diagram"],
                        has_table=flags["has_table"],
                        has_code_like_text=flags["has_code_like_text"],
                        has_large_image=has_large_image,
                    )
                )
        return page_records

    def _render_docx_to_pdf(self, *, docx_path: Path, rendered_pdf_path: Path) -> None:
        backend = (settings.docx_pagination_backend or "auto").lower().strip()
        rendered_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        rendered_pdf_path.unlink(missing_ok=True)

        if backend in {"auto", "soffice"}:
            if self._render_docx_with_soffice(docx_path=docx_path, rendered_pdf_path=rendered_pdf_path):
                return
            if backend == "soffice":
                raise RuntimeError("Failed to render DOCX with soffice.")
        if backend in {"auto", "docx2pdf"}:
            if self._render_docx_with_docx2pdf(docx_path=docx_path, rendered_pdf_path=rendered_pdf_path):
                return
            if backend == "docx2pdf":
                raise RuntimeError("Failed to render DOCX with docx2pdf.")
        raise RuntimeError("No DOCX render backend succeeded.")

    @staticmethod
    def _render_docx_with_soffice(*, docx_path: Path, rendered_pdf_path: Path) -> bool:
        soffice_cmd = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice_cmd:
            return False
        output_dir = rendered_pdf_path.parent
        expected_default_output = output_dir / f"{docx_path.stem}.pdf"
        expected_default_output.unlink(missing_ok=True)
        cmd = [
            soffice_cmd,
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(output_dir),
            str(docx_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            logger.warning("soffice DOCX render failed: %s", (proc.stderr or proc.stdout or "").strip()[:400])
            return False
        if not expected_default_output.exists():
            logger.warning("soffice finished without output PDF for %s", docx_path)
            return False
        if expected_default_output.resolve() != rendered_pdf_path.resolve():
            shutil.move(str(expected_default_output), str(rendered_pdf_path))
        return rendered_pdf_path.exists()

    @staticmethod
    def _render_docx_with_docx2pdf(*, docx_path: Path, rendered_pdf_path: Path) -> bool:
        try:
            from docx2pdf import convert as docx2pdf_convert  # type: ignore
        except Exception:
            return False
        try:
            docx2pdf_convert(str(docx_path), str(rendered_pdf_path))
        except Exception as exc:
            logger.warning("docx2pdf render failed: %s", str(exc)[:400])
            return False
        return rendered_pdf_path.exists()

    def _build_text_pages(
        self,
        *,
        page_texts: list[str],
        course_id: str,
        document_id: str,
        title: str,
        text_source: str,
    ) -> list[PageRecord]:
        page_dir = settings.pages_dir / course_id / document_id
        page_dir.mkdir(parents=True, exist_ok=True)
        out: list[PageRecord] = []
        for idx, text in enumerate(page_texts, start=1):
            image_path = page_dir / f"page_{idx:04d}.png"
            self._create_placeholder_page_image(
                image_path=image_path,
                title=title,
                page_number=idx,
                text_preview=text,
            )
            clean_text = clean_join_blocks([text])
            quality = estimate_text_quality(clean_text)
            flags = infer_page_flags(
                clean_text,
                layout_blocks=[],
                drawings_count=0,
                images_count=0,
                page_area=1.0,
                image_area=0.0,
            )
            out.append(
                PageRecord(
                    course_id=course_id,
                    document_id=document_id,
                    document_title=title,
                    page_id=f"{document_id}_p{idx}",
                    page_number=idx,
                    image_path=path_to_str(image_path.resolve()),
                    pdf_text_raw=clean_text,
                    ocr_text_raw="",
                    ocr_text_clean="",
                    merged_text=clean_text,
                    text_source=text_source,  # type: ignore[arg-type]
                    pdf_text_quality=quality,
                    ocr_text_quality=0.0,
                    language=detect_language(clean_text),
                    has_diagram=flags["has_diagram"],
                    has_table=flags["has_table"],
                    has_code_like_text=flags["has_code_like_text"],
                    has_large_image=False,
                )
            )
        return out

    @staticmethod
    def extract_docx_page_texts(docx_path: Path) -> list[str]:
        w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        try:
            with zipfile.ZipFile(docx_path) as zf:
                xml_bytes = zf.read("word/document.xml")
        except Exception:
            return [""]

        root = ET.fromstring(xml_bytes)
        body = root.find(f"{w_ns}body")
        if body is None:
            return [""]

        pages: list[str] = []
        current_lines: list[str] = []

        for child in body:
            if child.tag == f"{w_ns}p":
                paragraph = _extract_word_paragraph_with_page_breaks(child)
                if not paragraph:
                    continue
                segments = [seg.strip() for seg in paragraph.split("\f")]
                for idx, seg in enumerate(segments):
                    if seg:
                        current_lines.append(seg)
                    if idx < len(segments) - 1:
                        page_text = "\n".join(current_lines).strip()
                        pages.append(page_text)
                        current_lines = []
            elif child.tag == f"{w_ns}tbl":
                table_text = _extract_word_table_text(child)
                if table_text:
                    current_lines.append(table_text)
            elif child.tag == f"{w_ns}sectPr":
                page_text = "\n".join(current_lines).strip()
                if page_text:
                    pages.append(page_text)
                    current_lines = []

        tail = "\n".join(current_lines).strip()
        if tail:
            pages.append(tail)
        if not pages:
            return [""]
        if len(pages) == 1:
            return _paginate_docx_fallback(pages[0])
        return pages

    @staticmethod
    def extract_pptx_slide_texts(pptx_path: Path) -> list[str]:
        slide_pattern = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
        try:
            with zipfile.ZipFile(pptx_path) as zf:
                slide_names = sorted(
                    (name for name in zf.namelist() if slide_pattern.match(name)),
                    key=lambda item: int(slide_pattern.match(item).group(1)),  # type: ignore[union-attr]
                )
                if not slide_names:
                    return [""]
                out: list[str] = []
                for name in slide_names:
                    xml_bytes = zf.read(name)
                    out.append(_extract_slide_text(xml_bytes))
                return out
        except Exception:
            return [""]

    @staticmethod
    def _create_placeholder_page_image(image_path: Path, title: str, page_number: int, text_preview: str) -> None:
        image = Image.new("RGB", (1280, 720), color=(250, 250, 250))
        draw = ImageDraw.Draw(image)
        header = f"{title} - page {page_number}"
        body = (text_preview or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = f"{body[:277]}..."
        draw.text((40, 28), header, fill=(30, 30, 30))
        draw.text((40, 86), body, fill=(55, 55, 55))
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(image_path)

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


def _extract_word_paragraph_with_page_breaks(paragraph: ET.Element) -> str:
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{w_ns}t" and node.text:
            out.append(node.text)
        elif node.tag == f"{w_ns}tab":
            out.append("\t")
        elif node.tag == f"{w_ns}br" and node.get(f"{w_ns}type") == "page":
            out.append("\f")
        elif node.tag == f"{w_ns}lastRenderedPageBreak":
            out.append("\f")
    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\f+", "\f", text)
    return text.strip(" \t\r\n")


def _extract_word_table_text(table: ET.Element) -> str:
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    rows: list[str] = []
    for tr in table.findall(f".//{w_ns}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{w_ns}tc"):
            cell_parts: list[str] = []
            for p in tc.findall(f".//{w_ns}p"):
                part = _extract_word_paragraph_with_page_breaks(p).replace("\f", " ").strip()
                if part:
                    cell_parts.append(part)
            cell_text = " ".join(cell_parts).strip()
            cells.append(cell_text)
        row_text = " | ".join(cell for cell in cells if cell).strip()
        if row_text:
            rows.append(row_text)
    return "\n".join(rows).strip()


def _paginate_docx_fallback(text: str, target_chars: int = 2400) -> list[str]:
    if not text.strip():
        return [""]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    pages: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        para_len = len(para) + 1
        if current and current_len + para_len > target_chars:
            pages.append("\n".join(current).strip())
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len
    if current:
        pages.append("\n".join(current).strip())
    return pages or [text.strip()]


def _extract_slide_text(xml_bytes: bytes) -> str:
    namespaces = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    root = ET.fromstring(xml_bytes)
    lines = [node.text.strip() for node in root.findall(".//a:t", namespaces) if node.text and node.text.strip()]
    if not lines:
        return ""
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
