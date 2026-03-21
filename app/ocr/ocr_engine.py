from __future__ import annotations

import logging
import re
from collections.abc import Sequence

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
            raw_primary = pytesseract.image_to_string(pre, lang=self.languages, config="--oem 1 --psm 6")
            raw_sparse = pytesseract.image_to_string(pre, lang=self.languages, config="--oem 1 --psm 11")
            raw = merge_lines_preserving_structure(raw_primary, raw_sparse)
            clean = postprocess_ocr_text(raw)
            return raw, clean
        except Exception as exc:  # pragma: no cover - external dependency failures
            logger.exception("OCR failed: %s", exc)
            return "", ""


def repair_split_words(text: str) -> str:
    if not text:
        return ""
    repaired = text
    repaired = re.sub(r"([A-Za-zА-Яа-я]{4,})\s+([A-Za-zА-Яа-я]{2,})", _maybe_join_pair, repaired)
    repaired = re.sub(r"([A-Za-zА-Яа-я]{2,})-\s*\n\s*([A-Za-zА-Яа-я]{2,})", r"\1\2", repaired)
    return repaired


def _maybe_join_pair(match: re.Match[str]) -> str:
    left, right = match.group(1), match.group(2)
    # conservative merge for common broken OCR words
    candidates = {
        ("архитекту", "ра"): "архитектура",
        ("random", "access"): "random access",
        ("read", "only"): "read-only",
        ("write", "only"): "write-only",
    }
    key = (left.lower(), right.lower())
    if key in candidates:
        fixed = candidates[key]
        if left[0].isupper():
            return fixed.capitalize()
        return fixed
    if len(right) <= 2 and left.lower().endswith(("у", "т", "к", "с", "r")):
        return f"{left}{right}"
    return f"{left} {right}"


def correct_domain_ocr_errors(text: str) -> str:
    if not text:
        return ""
    replacements = [
        (r"\bgava\b", "java"),
        (r"\bjav\b", "java"),
        (r"\bread[\s\-]?on\b", "read-only"),
        (r"\bwrite[\s\-]?on\b", "write-only"),
        (r"\bneima[n]?\b", "neumann"),
        (r"\bneiman\b", "neumann"),
        (r"\bнеима[н]?\b", "неиман"),
    ]
    out = text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return out


def filter_ocr_noise(text: str) -> str:
    if not text:
        return ""
    allowed_short = {"ram", "cpu", "alu", "io", "и/о"}
    lines: list[str] = []
    for line in text.splitlines():
        tokens = line.split()
        kept: list[str] = []
        for tok in tokens:
            raw = tok.strip(".,:;!?()[]{}")
            low = raw.lower()
            if len(raw) <= 2 and low not in allowed_short and not raw.isdigit():
                if re.search(r"[A-Za-zА-Яа-я]", raw):
                    continue
            if re.fullmatch(r"[\|\]\[\\/]+", raw):
                continue
            kept.append(tok)
        if kept:
            lines.append(" ".join(kept))
    return "\n".join(lines)


def merge_lines_preserving_structure(primary: str, secondary: str) -> str:
    base = clean_ocr_text(primary)
    extra = clean_ocr_text(secondary)
    if not base:
        return extra
    if not extra:
        return base
    out = list(base.splitlines())
    seen = {ln.strip().lower() for ln in out if ln.strip()}
    for ln in extra.splitlines():
        key = ln.strip().lower()
        if not key or key in seen:
            continue
        if len(key) < 3:
            continue
        seen.add(key)
        out.append(ln.strip())
    return "\n".join(out)


def postprocess_ocr_text(text: str) -> str:
    text = clean_ocr_text(text)
    text = repair_split_words(text)
    text = correct_domain_ocr_errors(text)
    text = filter_ocr_noise(text)
    return clean_ocr_text(text)


def estimate_text_quality(text: str) -> float:
    cleaned = clean_ocr_text(text)
    if not cleaned:
        return 0.0
    tokens = re.findall(r"[A-Za-zА-Яа-я0-9\-]{2,}", cleaned)
    if not tokens:
        return 0.0
    alpha_ratio = sum(ch.isalpha() for ch in cleaned) / max(1, len(cleaned))
    long_tokens_ratio = sum(len(t) >= 3 for t in tokens) / max(1, len(tokens))
    noise_tokens_ratio = sum(bool(re.fullmatch(r"[\|\]\[\\/]+", t)) for t in tokens) / max(1, len(tokens))
    score = 0.6 * alpha_ratio + 0.45 * long_tokens_ratio - 0.6 * noise_tokens_ratio
    return max(0.0, min(1.0, score))


def infer_page_flags(
    text: str,
    *,
    layout_blocks: Sequence[dict] | None = None,
    drawings_count: int = 0,
    images_count: int = 0,
    page_area: float | None = None,
    image_area: float | None = None,
) -> dict[str, bool]:
    txt = text.lower()
    lines = [ln for ln in txt.splitlines() if ln.strip()]

    has_table = False
    if len(lines) >= 3:
        pipe_lines = sum(1 for ln in lines if "|" in ln or "\t" in ln)
        numeric_lines = sum(1 for ln in lines if len(re.findall(r"\d", ln)) >= 3)
        repeated_gap_lines = sum(1 for ln in lines if re.search(r"\S+\s{2,}\S+", ln))
        has_table = pipe_lines >= 2 or numeric_lines >= max(3, len(lines) // 3) or repeated_gap_lines >= 2

    diagram_keywords = [
        "diagram",
        "schema",
        "scheme",
        "flow",
        "architecture",
        "layout",
        "memory",
        "processor",
        "process",
        "control unit",
        "alu",
        "stack",
        "heap",
        "machine",
        "рисунок",
        "схема",
        "архитектура",
        "устройство",
        "память",
        "процессор",
        "ввод",
        "вывод",
        "блок",
        "стрелк",
    ]
    text_diagram_score = sum(1 for k in diagram_keywords if k in txt)

    block_count = len(layout_blocks or [])
    short_block_count = 0
    for block in layout_blocks or []:
        if isinstance(block, dict):
            raw_block_text = str(block.get("text", ""))
        elif isinstance(block, tuple) and len(block) >= 5:
            raw_block_text = str(block[4] or "")
        else:
            raw_block_text = str(block)
        btxt = clean_ocr_text(raw_block_text)
        if 0 < len(btxt) <= 28:
            short_block_count += 1
    layout_diagram_score = 0
    if block_count >= 12 and short_block_count >= max(4, block_count // 3):
        layout_diagram_score += 1
    if drawings_count >= 8:
        layout_diagram_score += 1
    if images_count >= 1:
        layout_diagram_score += 1
    if page_area and image_area and image_area / max(page_area, 1.0) >= 0.20:
        layout_diagram_score += 1

    has_diagram = (text_diagram_score >= 1 and layout_diagram_score >= 1) or layout_diagram_score >= 2

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
