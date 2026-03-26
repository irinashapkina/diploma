from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.config.settings import settings
from app.schemas.models import ChunkRecord, PageRecord
from app.utils.media import parse_video_locator
from app.utils.text import clean_ocr_text, normalize_for_retrieval

_heading_pattern = re.compile(r"^([A-ZА-Я0-9][A-ZА-Я0-9\-\s]{3,}|#+\s+\S+)")


@dataclass
class ChunkingConfig:
    min_chars: int = settings.min_text_chunk_chars
    max_chars: int = settings.max_text_chunk_chars


class TextChunker:
    def __init__(self, cfg: ChunkingConfig | None = None) -> None:
        self.cfg = cfg or ChunkingConfig()

    def chunk_pages(self, pages: list[PageRecord]) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for page in pages:
            page_chunks = self.chunk_page(page)
            chunks.extend(page_chunks)
        return chunks

    def chunk_page(self, page: PageRecord) -> list[ChunkRecord]:
        text = (page.merged_text or page.pdf_text_raw or page.ocr_text_clean or "").strip()
        blocks = self._split_into_blocks(text)
        merged_blocks = self._merge_small_blocks(blocks)
        page_title = self._extract_page_title(text)
        video_locator = parse_video_locator(page.image_path)
        out: list[ChunkRecord] = []
        for idx, block in enumerate(merged_blocks):
            cleaned = clean_ocr_text(block)
            if len(cleaned) < 30:
                continue
            chunk = ChunkRecord(
                chunk_id=str(uuid.uuid4()),
                course_id=page.course_id,
                document_id=page.document_id,
                document_title=page.document_title,
                page_id=page.page_id,
                page_number=page.page_number,
                chunk_order=idx,
                text=block,
                cleaned_text=cleaned,
                normalized_text=normalize_for_retrieval(cleaned),
                metadata={
                    "chunk_index_on_page": idx,
                    "language": page.language,
                    "has_diagram": page.has_diagram,
                    "has_table": page.has_table,
                    "has_code_like_text": page.has_code_like_text,
                    "has_large_image": page.has_large_image,
                    "text_source": page.text_source,
                    "pdf_text_quality": page.pdf_text_quality,
                    "ocr_text_quality": page.ocr_text_quality,
                    "page_title": page_title,
                    "page_has_diagram": page.has_diagram,
                    "page_has_table": page.has_table,
                    "page_has_code_like_text": page.has_code_like_text,
                    "page_has_large_image": page.has_large_image,
                    "maybe_visual_priority": bool(page.has_diagram or page.has_large_image),
                    "material_type": "video" if video_locator else "document",
                    "time_start_sec": video_locator.get("start_sec") if video_locator else None,
                    "time_end_sec": video_locator.get("end_sec") if video_locator else None,
                    "time_label": video_locator.get("label") if video_locator else None,
                },
                image_path=page.image_path,
            )
            out.append(chunk)
        return out

    def _split_into_blocks(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            return []
        blocks: list[str] = []
        current = ""
        for para in paragraphs:
            is_heading = bool(_heading_pattern.match(para))
            if is_heading and current.strip():
                blocks.append(current.strip())
                current = para
                continue
            if len(current) + len(para) + 1 <= self.cfg.max_chars:
                current = f"{current}\n{para}".strip()
            else:
                if current:
                    blocks.append(current.strip())
                current = para
        if current:
            blocks.append(current.strip())
        return blocks

    def _merge_small_blocks(self, blocks: list[str]) -> list[str]:
        if not blocks:
            return blocks
        out: list[str] = []
        pending = ""
        for block in blocks:
            if len(block) < self.cfg.min_chars:
                pending = f"{pending}\n{block}".strip()
                continue
            if pending:
                combined = f"{pending}\n{block}".strip()
                if len(combined) <= self.cfg.max_chars:
                    out.append(combined)
                    pending = ""
                    continue
                out.append(pending)
                pending = ""
            out.append(block)
        if pending:
            out.append(pending)
        return out

    @staticmethod
    def _extract_page_title(text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if len(line) < 4:
                continue
            if len(line) <= 120:
                return line
        return ""
