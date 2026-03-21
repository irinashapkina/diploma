from __future__ import annotations

from pathlib import Path
import platform

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Multimodal RAG MVP"
    debug: bool = True

    data_dir: Path = Field(default=Path("data"))
    documents_dir: Path = Field(default=Path("data/documents"))
    pages_dir: Path = Field(default=Path("data/pages"))
    indices_dir: Path = Field(default=Path("data/indices"))
    artifacts_dir: Path = Field(default=Path("data/artifacts"))

    tesseract_langs: str = "rus+eng"
    ocr_dpi: int = 220
    min_text_chunk_chars: int = 120
    max_text_chunk_chars: int = 750

    embedding_model_name: str = "intfloat/multilingual-e5-base"
    dense_backend: str = "numpy" if platform.system() == "Darwin" else "faiss"
    visual_backend: str = "clip"  # clip|colqwen2
    enable_visual_index: bool = True
    clip_model_name: str = "openai/clip-vit-base-patch32"
    colqwen2_model_name: str = "vidore/colqwen2-v0.1"

    bm25_top_k: int = 8
    dense_top_k: int = 8
    visual_top_k: int = 6
    rerank_top_k: int = 8

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5vl:7b"
    answer_max_tokens: int = 500
    answer_temperature: float = 0.1

    def ensure_dirs(self) -> None:
        for p in [self.data_dir, self.documents_dir, self.pages_dir, self.indices_dir, self.artifacts_dir]:
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
