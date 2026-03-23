from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from app.config.settings import settings
from app.schemas.models import PageRecord
from app.utils.io import read_json, write_json

logger = logging.getLogger(__name__)


@dataclass
class VisualHit:
    page_id: str
    score: float


class VisualPageIndex:
    def __init__(self, backend: str | None = None) -> None:
        self.backend = (backend or settings.visual_backend).lower()
        self.active_backend = self.backend
        self.path_meta = settings.indices_dir / "visual_meta.json"
        self.path_embeddings = settings.indices_dir / "visual_embeddings.npy"
        self.page_ids: list[str] = []
        self.image_paths: list[str] = []
        self.embeddings: np.ndarray | None = None
        self._clip_model: CLIPModel | None = None
        self._clip_processor: CLIPProcessor | None = None
        self._colqwen2 = None
        self.embedding_dim: int | None = None
        logger.info(
            "Visual index configured: requested_backend=%s clip_model=%s colqwen2_model=%s",
            self.backend,
            settings.clip_model_name,
            settings.colqwen2_model_name,
        )

    def _load_clip(self) -> tuple[CLIPProcessor, CLIPModel]:
        if self._clip_processor is None or self._clip_model is None:
            self._clip_processor = CLIPProcessor.from_pretrained(settings.clip_model_name)
            self._clip_model = CLIPModel.from_pretrained(settings.clip_model_name)
            self._clip_model.eval()
        return self._clip_processor, self._clip_model

    def _load_colqwen2(self) -> None:
        if self._colqwen2 is not None:
            return
        try:
            from colpali_engine.models import ColQwen2, ColQwen2Processor  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("ColQwen2 backend unavailable. Install colpali-engine package.") from exc
        model = ColQwen2.from_pretrained(settings.colqwen2_model_name, torch_dtype=torch.float16, device_map="auto")
        processor = ColQwen2Processor.from_pretrained(settings.colqwen2_model_name)
        self._colqwen2 = (processor, model)

    def build(self, pages: list[PageRecord]) -> None:
        self.page_ids = [p.page_id for p in pages]
        self.image_paths = [p.image_path for p in pages]
        if not self.image_paths:
            return

        requested = self.backend
        if requested == "colqwen2":
            try:
                self.embeddings = self._build_colqwen2_embeddings(self.image_paths)
                self.active_backend = "colqwen2"
            except Exception as exc:
                logger.warning("ColQwen2 build failed (%s); fallback to CLIP backend", exc)
                self.active_backend = "clip"
                self.embeddings = self._build_clip_embeddings(self.image_paths)
        else:
            self.active_backend = "clip"
            self.embeddings = self._build_clip_embeddings(self.image_paths)

        np.save(self.path_embeddings, self.embeddings)
        self.embedding_dim = int(self.embeddings.shape[1]) if self.embeddings.ndim == 2 else None
        write_json(
            self.path_meta,
            {
                "page_ids": self.page_ids,
                "image_paths": self.image_paths,
                "backend": self.active_backend,
                "requested_backend": requested,
                "embedding_dim": self.embedding_dim,
            },
        )
        logger.info(
            "Visual index built: pages=%s requested_backend=%s active_backend=%s",
            len(self.page_ids),
            requested,
            self.active_backend,
        )

    def _build_clip_embeddings(self, image_paths: list[str]) -> np.ndarray:
        processor, model = self._load_clip()
        vectors: list[np.ndarray] = []
        with torch.no_grad():
            for path in image_paths:
                img = Image.open(path).convert("RGB")
                inputs = processor(images=img, return_tensors="pt")
                image_features = model.get_image_features(**inputs)
                vec = image_features[0].detach().cpu().numpy().astype(np.float32)
                vec /= np.linalg.norm(vec) + 1e-9
                vectors.append(vec)
        return np.stack(vectors)

    def _build_colqwen2_embeddings(self, image_paths: list[str]) -> np.ndarray:
        self._load_colqwen2()
        processor, model = self._colqwen2
        vectors: list[np.ndarray] = []
        with torch.no_grad():
            for path in image_paths:
                img = Image.open(path).convert("RGB")
                batch = processor.process_images([img]).to(model.device)
                emb = model(**batch)
                pooled = emb.mean(dim=1)[0].detach().float().cpu().numpy().astype(np.float32)
                pooled /= np.linalg.norm(pooled) + 1e-9
                vectors.append(pooled)
        return np.stack(vectors)

    def load(self) -> None:
        if self.path_meta.exists():
            meta = read_json(self.path_meta)
            self.page_ids = meta.get("page_ids", [])
            self.image_paths = meta.get("image_paths", [])
            self.active_backend = meta.get("backend", self.backend)
            self.backend = meta.get("requested_backend", self.backend)
            self.embedding_dim = meta.get("embedding_dim")
        if self.path_embeddings.exists():
            self.embeddings = np.load(self.path_embeddings)
            if self.embeddings.ndim == 2:
                self.embedding_dim = int(self.embeddings.shape[1])

    def _encode_text_clip(self, query: str) -> np.ndarray:
        processor, model = self._load_clip()
        with torch.no_grad():
            inputs = processor(text=[query], return_tensors="pt", padding=True)
            text_features = model.get_text_features(**inputs)
        vec = text_features[0].detach().cpu().numpy().astype(np.float32)
        vec /= np.linalg.norm(vec) + 1e-9
        return vec

    def _encode_text_colqwen2(self, query: str) -> np.ndarray:
        self._load_colqwen2()
        processor, model = self._colqwen2
        with torch.no_grad():
            batch = processor.process_queries([query]).to(model.device)
            emb = model(**batch)
        pooled = emb.mean(dim=1)[0].detach().float().cpu().numpy().astype(np.float32)
        pooled /= np.linalg.norm(pooled) + 1e-9
        return pooled

    def search(self, query: str, top_k: int = 6) -> list[VisualHit]:
        if self.embeddings is None:
            self.load()
        if self.embeddings is None or self.embeddings.size == 0:
            return []

        runtime_backend = self.active_backend or self.backend
        if runtime_backend == "colqwen2":
            try:
                q = self._encode_text_colqwen2(query)
            except Exception as exc:
                logger.warning("ColQwen2 query encoding failed (%s); fallback to CLIP", exc)
                self.active_backend = "clip"
                q = self._encode_text_clip(query)
        else:
            q = self._encode_text_clip(query)

        if self.embeddings.ndim != 2 or self.embeddings.shape[1] != q.shape[0]:
            logger.warning(
                "Visual embedding dimension mismatch: embeddings_shape=%s query_dim=%s backend=%s. "
                "Trying to rebuild visual embeddings.",
                getattr(self.embeddings, "shape", None),
                q.shape[0],
                runtime_backend,
            )
            if not self._rebuild_after_dim_mismatch(expected_dim=q.shape[0]):
                logger.warning("Visual retrieval disabled for this request due to incompatible index state.")
                return []

        scores = self.embeddings @ q
        idxs = np.argsort(scores)[::-1][:top_k]
        return [VisualHit(page_id=self.page_ids[i], score=float(scores[i])) for i in idxs if scores[i] > 0]

    def backend_info(self) -> str:
        return self.active_backend or self.backend

    def _rebuild_after_dim_mismatch(self, expected_dim: int) -> bool:
        if not self.image_paths:
            return False
        try:
            self.active_backend = "clip"
            rebuilt = self._build_clip_embeddings(self.image_paths)
            if rebuilt.ndim != 2 or rebuilt.shape[1] != expected_dim:
                return False
            self.embeddings = rebuilt
            self.embedding_dim = int(rebuilt.shape[1])
            np.save(self.path_embeddings, self.embeddings)
            write_json(
                self.path_meta,
                {
                    "page_ids": self.page_ids,
                    "image_paths": self.image_paths,
                    "backend": self.active_backend,
                    "requested_backend": self.backend,
                    "embedding_dim": self.embedding_dim,
                },
            )
            logger.info("Visual embeddings rebuilt with dim=%s", self.embedding_dim)
            return True
        except Exception as exc:  # pragma: no cover - runtime/deps dependent
            logger.warning("Failed to rebuild visual embeddings after dim mismatch: %s", exc)
            return False
