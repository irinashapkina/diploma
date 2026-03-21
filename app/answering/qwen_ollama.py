from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests

from app.config.settings import settings

logger = logging.getLogger(__name__)


class QwenVLAnswerer:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    @staticmethod
    def _encode_images(image_paths: list[str]) -> list[str]:
        encoded: list[str] = []
        for p in image_paths:
            path = Path(p)
            if not path.exists():
                continue
            encoded.append(base64.b64encode(path.read_bytes()).decode("utf-8"))
        return encoded

    def generate(self, prompt: str, image_paths: list[str] | None = None) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {
                "temperature": settings.answer_temperature,
                "num_predict": settings.answer_max_tokens,
            },
            "messages": [{"role": "user", "content": prompt}],
        }
        if image_paths:
            payload["messages"][0]["images"] = self._encode_images(image_paths)

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "").strip()
        except Exception as exc:  # pragma: no cover - runtime/network dependency
            logger.exception("Ollama call failed: %s", exc)
            return "Не удалось получить ответ от модели. Проверьте запущен ли Ollama с Qwen2.5-VL."

