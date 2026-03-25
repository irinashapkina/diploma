from __future__ import annotations

from datetime import datetime, timezone
import logging
import uuid

import requests

from app.reference.baseline import merge_technology_snapshots
from app.reference.extractors import get_extractor
from app.reference.fact_models import build_structured_summary
from app.reference.source_registry import CONCEPT_REFERENCE_SOURCES, SourceSpec, iter_registry_entries
from app.services.json_review_storage import JsonReviewStorage

logger = logging.getLogger(__name__)


class ReferenceSyncService:
    def __init__(self, storage: JsonReviewStorage) -> None:
        self.storage = storage

    def sync(self, include_concepts: bool = True) -> dict:
        run_id = str(uuid.uuid4())
        raw_facts: list[dict] = []
        normalized_facts: list[dict] = []
        baseline: dict[str, dict] = {}

        for entry in iter_registry_entries():
            technology_facts: list[dict] = []
            for source in entry.sources:
                source_result = self._extract_source_fact(
                    technology_name=entry.technology_name,
                    aliases=entry.aliases,
                    source=source,
                )
                raw_facts.append(source_result["raw"])
                if source_result["normalized"]:
                    normalized = source_result["normalized"]
                    normalized_facts.append(normalized)
                    technology_facts.append(normalized)
            merged = merge_technology_snapshots(entry.technology_name, technology_facts)
            if merged:
                baseline[entry.technology_name] = merged

        if include_concepts:
            for source in CONCEPT_REFERENCE_SOURCES:
                concept_name = source.concept_name or source.name
                source_result = self._extract_source_fact(
                    technology_name=concept_name,
                    aliases=source.aliases,
                    source=source,
                )
                raw_facts.append(source_result["raw"])
                if source_result["normalized"]:
                    normalized = source_result["normalized"]
                    normalized_facts.append(normalized)
                    baseline[concept_name] = normalized

        self.storage.save_reference_run(run_id, raw_facts, normalized_facts, baseline)
        return {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_count": len(raw_facts),
            "normalized_count": len(normalized_facts),
            "baseline_items": len(baseline),
        }

    def _extract_source_fact(
        self,
        technology_name: str,
        aliases: list[str],
        source: SourceSpec,
    ) -> dict:
        fetched_at = datetime.now(timezone.utc).isoformat()
        html = ""
        fetch_error = None
        try:
            response = requests.get(source.base_url, timeout=20)
            response.raise_for_status()
            html = response.text
        except Exception as exc:
            fetch_error = str(exc)
            logger.warning("Failed to fetch reference source %s: %s", source.base_url, exc)

        raw_payload = {
            "technology_name": technology_name,
            "source_name": source.name,
            "source_url": source.base_url,
            "source_priority": source.priority,
            "extractor_name": source.extractor,
            "category": source.category,
            "fetched_at": fetched_at,
            "fetch_error": fetch_error,
            "content_size": len(html),
        }
        if not html:
            return {"raw": raw_payload, "normalized": None}

        extractor = get_extractor(source.extractor)
        result = extractor.extract(
            spec=source,
            html=html,
            technology_name=technology_name,
            aliases=aliases,
        )
        fact = result.fact
        if not fact:
            raw_payload["diagnostics"] = result.diagnostics
            return {"raw": raw_payload, "normalized": None}

        payload = fact.to_payload()
        payload["source_priority"] = source.priority
        normalized_payload = {
            "technology_name": technology_name,
            "source_name": source.name,
            "source_url": source.base_url,
            "category": source.category,
            "aliases": aliases,
            "structured_summary": build_structured_summary(technology_name, fact),
            "fact": payload,
        }
        raw_payload["diagnostics"] = result.diagnostics
        raw_payload["excerpt"] = payload.get("raw_excerpt")
        return {"raw": raw_payload, "normalized": normalized_payload}
