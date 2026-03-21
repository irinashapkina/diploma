from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class DocumentRecord(BaseModel):
    document_id: str
    document_title: str
    source_pdf: str
    page_count: int


class PageRecord(BaseModel):
    document_id: str
    document_title: str
    page_id: str
    page_number: int
    image_path: str
    ocr_text_raw: str
    ocr_text_clean: str
    language: Literal["ru", "en", "mixed", "unknown"]
    has_diagram: bool
    has_table: bool
    has_code_like_text: bool


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page_id: str
    page_number: int
    text: str
    cleaned_text: str
    normalized_text: str
    metadata: dict[str, Any]
    image_path: str


@dataclass
class RetrievalCandidate:
    candidate_id: str
    source_type: Literal["text", "visual"]
    score: float
    document_id: str
    document_title: str
    page_id: str
    page_number: int
    text: str = ""
    image_path: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


class AskRequest(BaseModel):
    question: str
    top_k: int = 6
    debug: bool = False


class SourceItem(BaseModel):
    document_title: str
    page: int
    snippet: str
    score: float
    type: Literal["text", "visual"]


class AskResponse(BaseModel):
    answer: str
    confidence: float
    mode: Literal["text", "visual", "hybrid"]
    sources: list[SourceItem]
    debug: dict[str, Any] | None = None


def path_to_str(path: Path) -> str:
    return str(path.as_posix())

