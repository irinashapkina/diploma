from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
import re


_year_label_re = re.compile(r"^\d{4}(/\d{4})?$")
_semester_values = {"1", "2", "spring", "autumn"}


class TeacherRecord(BaseModel):
    teacher_id: str
    full_name: str


class CourseRecord(BaseModel):
    course_id: str
    teacher_id: str
    title: str
    year_label: str
    semester: str | None = None
    description: str | None = None
    is_active: bool = True

    @field_validator("year_label")
    @classmethod
    def validate_year_label(cls, value: str) -> str:
        if not _year_label_re.match(value):
            raise ValueError("year_label must be yyyy or yyyy/yyyy")
        if "/" in value:
            start, end = value.split("/")
            if int(end) != int(start) + 1:
                raise ValueError("year_label yyyy/yyyy must have end=start+1")
        return value

    @field_validator("semester")
    @classmethod
    def validate_semester(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in _semester_values:
            raise ValueError("semester must be one of: 1, 2, spring, autumn")
        return value


class DocumentRecord(BaseModel):
    document_id: str
    course_id: str
    document_title: str
    source_pdf: str
    page_count: int


class PageRecord(BaseModel):
    course_id: str
    document_id: str
    document_title: str
    page_id: str
    page_number: int
    image_path: str
    pdf_text_raw: str = ""
    ocr_text_raw: str
    ocr_text_clean: str
    merged_text: str = ""
    text_source: Literal["pdf", "ocr", "pdf+ocr"] = "ocr"
    pdf_text_quality: float = 0.0
    ocr_text_quality: float = 0.0
    language: Literal["ru", "en", "mixed", "unknown"]
    has_diagram: bool
    has_table: bool
    has_code_like_text: bool
    has_large_image: bool = False


class ChunkRecord(BaseModel):
    chunk_id: str
    course_id: str
    document_id: str
    document_title: str
    page_id: str
    page_number: int
    chunk_order: int = 0
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
    course_id: str = Field(..., min_length=1)
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
