from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil

from app.config.settings import settings
from app.utils.text import clean_ocr_text

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str
    confidence: float | None = None


class VideoTranscriber:
    def __init__(self) -> None:
        self.model_name = settings.video_asr_model
        self.language = settings.video_asr_language

    def transcribe(self, video_path: Path) -> list[TranscriptSegment]:
        ffmpeg_path = _ensure_ffmpeg_in_path()
        if not ffmpeg_path:
            raise RuntimeError(
                "ffmpeg is not installed or not available in PATH. "
                "Install ffmpeg and restart the API process."
            )
        try:
            import whisper  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("openai-whisper is not installed. Add openai-whisper and ffmpeg.") from exc

        model = whisper.load_model(self.model_name)
        try:
            result = model.transcribe(str(video_path), language=self.language, task="transcribe", verbose=False)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ffmpeg executable is not available for whisper runtime. "
                "Install ffmpeg and restart the API process."
            ) from exc
        segments: list[TranscriptSegment] = []
        for item in result.get("segments", []):
            text = clean_ocr_text(str(item.get("text", "") or "").strip())
            if not text:
                continue
            start_sec = float(item.get("start", 0.0) or 0.0)
            end_sec = float(item.get("end", start_sec) or start_sec)
            if end_sec <= start_sec:
                end_sec = start_sec + 1.0
            conf = item.get("avg_logprob")
            confidence = float(conf) if conf is not None else None
            segments.append(
                TranscriptSegment(
                    start_sec=start_sec,
                    end_sec=end_sec,
                    text=text,
                    confidence=confidence,
                )
            )
        if not segments:
            logger.warning("Video transcription produced no segments for %s", video_path)
        return segments


def _ensure_ffmpeg_in_path() -> str | None:
    existing = shutil.which("ffmpeg")
    if existing:
        return existing
    candidates = (
        "/opt/homebrew/bin/ffmpeg",  # Apple Silicon Homebrew
        "/usr/local/bin/ffmpeg",  # Intel Homebrew
    )
    for candidate in candidates:
        if not Path(candidate).exists():
            continue
        current_path = os.environ.get("PATH", "")
        parts = current_path.split(":") if current_path else []
        bin_dir = str(Path(candidate).parent)
        if bin_dir not in parts:
            os.environ["PATH"] = f"{bin_dir}:{current_path}" if current_path else bin_dir
        return candidate
    return None
