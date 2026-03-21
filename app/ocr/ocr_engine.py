from __future__ import annotations

import logging
import re

import pytesseract
from PIL import Image

from app.ocr.preprocess import preprocess_for_ocr
from app.utils.text import clean_ocr_text

logger = logging.getLogger(__name__)


class OCREngine:
    def __init__(self, languages: str = "rus+eng") -> None:
        self.languages = languages
        logger.info("OCR engine initialized: backend=tesseract, languages=%s", self.languages)

    def run(self, image: Image.Image) -> tuple[str, str]:
        try:
            pre = preprocess_for_ocr(image)
            raw = pytesseract.image_to_string(pre, lang=self.languages, config="--psm 6")
            clean = clean_ocr_text(raw)
            return raw, clean
        except Exception as exc:  # pragma: no cover - external dependency failures
            logger.exception("OCR failed: %s", exc)
            return "", ""


def infer_page_flags(ocr_text_clean: str) -> dict[str, bool]:
    txt = ocr_text_clean.lower()
    lines = [ln for ln in txt.splitlines() if ln.strip()]

    has_table = False
    if len(lines) >= 3:
        pipe_lines = sum(1 for ln in lines if "|" in ln or "\t" in ln)
        numeric_lines = sum(1 for ln in lines if len(re.findall(r"\d", ln)) >= 3)
        has_table = pipe_lines >= 2 or numeric_lines >= max(3, len(lines) // 3)

    diagram_keywords = [
        "diagram",
        "schema",
        "flow",
        "architecture",
        "рисунок",
        "схема",
        "архитектура",
        "блок",
        "стрелк",
    ]
    has_diagram = any(k in txt for k in diagram_keywords)

    code_markers = [
        "def ",
        "class ",
        "for(",
        "while(",
        "if(",
        "{",
        "}",
        "=>",
        "::",
        "public ",
        "private ",
        "return ",
        "int ",
        "void ",
    ]
    code_like_lines = sum(
        1
        for ln in lines
        if any(m in ln for m in code_markers) or re.search(r"[;{}()<>\[\]]", ln) is not None
    )
    has_code_like_text = code_like_lines >= 2

    return {
        "has_diagram": has_diagram,
        "has_table": has_table,
        "has_code_like_text": has_code_like_text,
    }
