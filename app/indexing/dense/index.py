from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config.settings import settings
from app.schemas.models import ChunkRecord
from app.utils.io import read_json, write_json

try:
    import faiss
except Exception:
    faiss = None

logger = logging.getLogger(__name__)


@dataclass
class DenseHit:
    chunk_id: str
    score: float


class DenseTextIndex:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model_name
        self.backend = settings.dense_backend.lower()
        self.model: SentenceTransformer | None = None
        self.path_index = settings.indices_dir / "dense_faiss.index"
        self.path_embeddings = settings.indices_dir / "dense_embeddings.npy"
        self.path_meta = settings.indices_dir / "dense_meta.json"
        self.chunk_ids: list[str] = []
        self.index = None
        self.embeddings: np.ndarray | None = None

    def _get_model(self) -> SentenceTransformer:
        if self.model is None:
            self.model = SentenceTransformer(self.model_name)
        return self.model

    def _format_passages(self, texts: list[str]) -> list[str]:
        if "e5" in self.model_name.lower():
            return [f"passage: {t}" for t in texts]
        return texts

    def _format_query(self, query: str) -> str:
        if "e5" in self.model_name.lower():
            return f"query: {query}"
        return query

    def build(self, chunks: list[ChunkRecord]) -> None:
        model = self._get_model()
        self.chunk_ids = [c.chunk_id for c in chunks]
        texts = [c.cleaned_text for c in chunks]
        if not texts:
            return
        emb = model.encode(
            self._format_passages(texts),
            normalize_embeddings=True,
            show_progress_bar=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        dim = emb.shape[1]
        active_backend = self.backend
        if active_backend == "faiss" and faiss is not None:
            self.index = faiss.IndexFlatIP(dim)
            self.index.add(emb)
            faiss.write_index(self.index, str(self.path_index))
            self.embeddings = None
            if self.path_embeddings.exists():
                self.path_embeddings.unlink()
        else:
            self.embeddings = emb
            np.save(self.path_embeddings, self.embeddings)
            self.index = None
            active_backend = "numpy"
            if self.path_index.exists():
                self.path_index.unlink()

        write_json(
            self.path_meta,
            {"chunk_ids": self.chunk_ids, "model_name": self.model_name, "backend": active_backend},
        )
        logger.info("Dense index built: %s chunks, dim=%s, backend=%s", len(self.chunk_ids), dim, active_backend)

    def load(self) -> None:
        if self.path_meta.exists():
            meta = read_json(self.path_meta)
            self.chunk_ids = meta.get("chunk_ids", [])
            self.backend = meta.get("backend", self.backend)
        if self.backend == "faiss" and self.path_index.exists() and faiss is not None:
            self.index = faiss.read_index(str(self.path_index))
        if self.backend == "numpy" and self.path_embeddings.exists():
            self.embeddings = np.load(self.path_embeddings)

    def search(self, query: str, top_k: int = 8) -> list[DenseHit]:
        if self.index is None and self.embeddings is None:
            self.load()
        if self.index is None and self.embeddings is None:
            return []
        model = self._get_model()
        q = model.encode(
            [self._format_query(query)],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)
        if self.index is not None:
            scores, idxs = self.index.search(q, top_k)
        else:
            sims = (self.embeddings @ q[0]).astype(np.float32)
            idxs_vec = np.argsort(sims)[::-1][:top_k]
            scores = np.array([sims[idxs_vec]], dtype=np.float32)
            idxs = np.array([idxs_vec], dtype=np.int64)
        hits: list[DenseHit] = []
        for i, s in zip(idxs[0], scores[0]):
            if i < 0 or i >= len(self.chunk_ids):
                continue
            hits.append(DenseHit(chunk_id=self.chunk_ids[i], score=float(s)))
        return hits
