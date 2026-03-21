from __future__ import annotations

import logging
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.config.settings import settings
from app.schemas.models import ChunkRecord
from app.utils.io import read_json, write_json
from app.utils.text import tokenize_mixed

logger = logging.getLogger(__name__)


@dataclass
class BM25Hit:
    chunk_id: str
    score: float


class BM25Index:
    def __init__(self) -> None:
        self.path = settings.indices_dir / "bm25_index.json"
        self.chunk_ids: list[str] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None

    def build(self, chunks: list[ChunkRecord]) -> None:
        self.chunk_ids = [c.chunk_id for c in chunks]
        self.tokenized_corpus = [tokenize_mixed(c.normalized_text or c.cleaned_text) for c in chunks]
        if not self.tokenized_corpus:
            self.bm25 = None
            return
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        write_json(
            self.path,
            {
                "chunk_ids": self.chunk_ids,
                "tokenized_corpus": self.tokenized_corpus,
            },
        )
        logger.info("BM25 index built: %s chunks", len(self.chunk_ids))

    def load(self) -> None:
        if not self.path.exists():
            return
        payload = read_json(self.path)
        self.chunk_ids = payload.get("chunk_ids", [])
        self.tokenized_corpus = payload.get("tokenized_corpus", [])
        if self.tokenized_corpus:
            self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, top_k: int = 8) -> list[BM25Hit]:
        if self.bm25 is None:
            self.load()
        if self.bm25 is None:
            return []
        q_tokens = tokenize_mixed(query)
        if not q_tokens:
            return []
        scores = self.bm25.get_scores(q_tokens)
        pairs = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [BM25Hit(chunk_id=self.chunk_ids[i], score=float(s)) for i, s in pairs if s > 0.0]

