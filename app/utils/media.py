from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def parse_video_locator(locator: str) -> dict[str, float | str] | None:
    value = (locator or "").strip()
    if not value.startswith("video://"):
        return None
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    try:
        start = float(query.get("start", [""])[0])
        end = float(query.get("end", [""])[0])
    except (TypeError, ValueError):
        return None
    label = str(query.get("label", [""])[0] or "").strip()
    return {"start_sec": max(0.0, start), "end_sec": max(start, end), "label": label}


def format_time_seconds(value: float) -> str:
    total = int(max(0, value))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

