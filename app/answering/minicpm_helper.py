from __future__ import annotations

import logging

from app.config.settings import settings

logger = logging.getLogger(__name__)


class MiniCPMVHelper:
    """
    Optional extension point for MiniCPM-V-based page hints.
    No hard dependency: if model/libs are absent, returns empty hints.
    """

    def __init__(self) -> None:
        self.enabled = settings.minicpm_v_enabled
        self._ready = False
        if not self.enabled:
            return
        try:
            # TODO: optional real integration (transformers/vllm backend).
            self._ready = False
            logger.info("MiniCPM-V helper enabled, running in placeholder mode (no hard dependency).")
        except Exception as exc:  # pragma: no cover
            logger.warning("MiniCPM-V helper unavailable (%s); continuing without it.", exc)
            self.enabled = False
            self._ready = False

    def extract_page_hints(self, image_paths: list[str]) -> list[str]:
        if not self.enabled or not self._ready:
            return []
        # TODO: return compact labels/caption from top visual pages.
        return []
