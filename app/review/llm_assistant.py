from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from app.config.settings import settings
from app.review.llm_prompts import (
    EVIDENCE_RENDER_SYSTEM,
    ROLE_TRIAGE_SYSTEM,
    SUGGESTION_RENDER_SYSTEM,
    build_evidence_render_prompt,
    build_role_triage_prompt,
    build_suggestion_render_prompt,
)

logger = logging.getLogger(__name__)


class ReviewLLMAssistant:
    def __init__(self) -> None:
        self.enabled = settings.review_llm_enabled
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.review_llm_timeout_sec
        self.prompt_version = settings.review_llm_prompt_version

    def triage_claim(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        text = self._chat_json(
            system_prompt=ROLE_TRIAGE_SYSTEM,
            user_prompt=build_role_triage_prompt(payload),
            max_tokens=280,
        )
        if not text:
            return None
        data = _extract_json(text)
        if not data:
            return None
        role = str(data.get("role") or "").strip()
        confidence = _to_float(data.get("confidence"), 0.0)
        should_create_issue = bool(data.get("should_create_issue"))
        if role not in {
            "current_state_claim",
            "historical_reference",
            "origin_or_first_version",
            "biography_fact",
            "academic_metadata",
            "example_or_quote",
            "ambiguous_claim",
        }:
            return None
        return {
            "role": role,
            "confidence": max(0.0, min(1.0, confidence)),
            "should_create_issue": should_create_issue,
            "reasoning_short": str(data.get("reasoning_short") or "")[:180],
            "prompt_version": self.prompt_version,
        }

    def render_evidence(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        text = self._chat_json(
            system_prompt=EVIDENCE_RENDER_SYSTEM,
            user_prompt=build_evidence_render_prompt(payload),
            max_tokens=240,
        )
        if not text:
            return None
        data = _extract_json(text)
        if not data:
            return None
        evidence_text = str(data.get("evidence_text") or "").strip()
        if not evidence_text:
            return None
        return {"evidence_text": evidence_text[:220], "prompt_version": self.prompt_version}

    def render_suggestion(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        text = self._chat_json(
            system_prompt=SUGGESTION_RENDER_SYSTEM,
            user_prompt=build_suggestion_render_prompt(payload),
            max_tokens=320,
        )
        if not text:
            return None
        data = _extract_json(text)
        if not data:
            return None
        replacement = str(data.get("replacement_text") or "").strip()
        if not replacement:
            return None
        confidence = _to_float(data.get("confidence"), 0.0)
        notes = str(data.get("notes") or "")[:120]
        return {
            "replacement_text": replacement[:260],
            "confidence": max(0.0, min(1.0, confidence)),
            "notes": notes,
            "prompt_version": self.prompt_version,
        }

    def _chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": max_tokens},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
            return str(content).strip()
        except Exception as exc:  # pragma: no cover - runtime/network dependency
            logger.warning("Review LLM call failed: %s", exc)
            return ""


def _extract_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except Exception:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default
