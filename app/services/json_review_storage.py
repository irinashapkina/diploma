from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.config.settings import settings


class JsonReviewStorage:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root = root_dir or (settings.data_dir / "review")
        self.reference_raw_dir = self.root / "reference" / "raw"
        self.reference_normalized_dir = self.root / "reference" / "normalized"
        self.reference_baseline_dir = self.root / "reference" / "baseline"
        self.reference_snapshots_dir = self.root / "reference" / "snapshots"
        self.scans_dir = self.root / "scans"
        self.meta_path = self.root / "metadata" / "last_runs.json"
        for path in (
            self.reference_raw_dir,
            self.reference_normalized_dir,
            self.reference_baseline_dir,
            self.reference_snapshots_dir,
            self.scans_dir,
            self.meta_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def save_reference_run(
        self,
        run_id: str,
        raw_facts: list[dict[str, Any]],
        normalized_facts: list[dict[str, Any]],
        baseline: dict[str, Any],
    ) -> None:
        self._atomic_write_json(self.reference_raw_dir / f"{run_id}.json", {"run_id": run_id, "facts": raw_facts})
        self._atomic_write_json(
            self.reference_normalized_dir / f"{run_id}.json",
            {"run_id": run_id, "facts": normalized_facts},
        )
        snapshot = {"run_id": run_id, "updated_at": _utc_now_iso(), "baseline": baseline}
        self._atomic_write_json(self.reference_snapshots_dir / f"{run_id}.json", snapshot)
        self._atomic_write_json(self.reference_baseline_dir / "current.json", snapshot)
        meta = self._read_json_or_default(self.meta_path, {})
        meta["reference_last_run"] = {"run_id": run_id, "updated_at": snapshot["updated_at"]}
        self._atomic_write_json(self.meta_path, meta)

    def get_reference_baseline(self) -> dict[str, Any]:
        return self._read_json_or_default(self.reference_baseline_dir / "current.json", {})

    def get_reference_snapshot(self, run_id: str) -> dict[str, Any]:
        return self._read_json_or_default(self.reference_snapshots_dir / f"{run_id}.json", {})

    def save_scan_run(
        self,
        course_id: str,
        scan_id: str,
        scan_summary: dict[str, Any],
        issues: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
    ) -> None:
        course_dir = self.scans_dir / course_id
        course_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "scan_id": scan_id,
            "course_id": course_id,
            "created_at": _utc_now_iso(),
            "summary": scan_summary,
        }
        self._atomic_write_json(course_dir / f"{scan_id}.json", payload)
        self._atomic_write_json(course_dir / "latest_scan.json", payload)
        self._atomic_write_json(course_dir / "issues.json", {"scan_id": scan_id, "items": issues})
        self._atomic_write_json(course_dir / "suggestions.json", {"scan_id": scan_id, "items": suggestions})
        meta = self._read_json_or_default(self.meta_path, {})
        meta["scan_last_run"] = {"scan_id": scan_id, "course_id": course_id, "updated_at": payload["created_at"]}
        self._atomic_write_json(self.meta_path, meta)

    def get_scan_issues(self, course_id: str) -> list[dict[str, Any]]:
        course_dir = self.scans_dir / course_id
        payload = self._read_json_or_default(course_dir / "issues.json", {})
        return payload.get("items", [])

    def get_scan_latest(self, course_id: str) -> dict[str, Any]:
        return self._read_json_or_default(self.scans_dir / course_id / "latest_scan.json", {})

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_name = tmp.name
        os.replace(temp_name, path)

    @staticmethod
    def _read_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
