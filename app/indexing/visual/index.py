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
        self.path_meta = settings.indices_dir / "visual_meta.json"
        self.path_embeddings = settings.indices_dir / "visual_embeddings.npy"
        self.page_ids: list[str] = []
        self.image_paths: list[str] = []
        self.embeddings: np.ndarray | None = None
        self._clip_model: CLIPModel | None = None
        self._clip_processor: CLIPProcessor | None = None
        self._colqwen2 = None

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

        if self.backend == "colqwen2":
            try:
                self.embeddings = self._build_colqwen2_embeddings(self.image_paths)
            except Exception as exc:
                logger.warning("ColQwen2 failed (%s), fallback to CLIP backend", exc)
                self.backend = "clip"
                self.embeddings = self._build_clip_embeddings(self.image_paths)
        else:
            self.embeddings = self._build_clip_embeddings(self.image_paths)

        np.save(self.path_embeddings, self.embeddings)
        write_json(
            self.path_meta,
            {
                "page_ids": self.page_ids,
                "image_paths": self.image_paths,
                "backend": self.backend,
            },
        )
        logger.info("Visual index built: %s pages with backend=%s", len(self.page_ids), self.backend)

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
            self.backend = meta.get("backend", self.backend)
        if self.path_embeddings.exists():
            self.embeddings = np.load(self.path_embeddings)

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

        if self.backend == "colqwen2":
            try:
                q = self._encode_text_colqwen2(query)
            except Exception as exc:
                logger.warning("ColQwen2 query encoding failed (%s), fallback to CLIP", exc)
                self.backend = "clip"
                q = self._encode_text_clip(query)
        else:
            q = self._encode_text_clip(query)

        scores = self.embeddings @ q
        idxs = np.argsort(scores)[::-1][:top_k]
        return [VisualHit(page_id=self.page_ids[i], score=float(scores[i])) for i in idxs if scores[i] > 0]

    def backend_info(self) -> str:
        return self.backend

