"""Caption Agent: runs Whisper on voice.mp3 and writes captions.srt."""

from pathlib import Path
from typing import Protocol

from yt_auto.clients.whisper import Segment
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)


class WhisperLike(Protocol):
    async def transcribe(self, audio: Path) -> list[Segment]: ...


def _fmt_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp `HH:MM:SS,mmm`."""
    if seconds < 0:
        seconds = 0
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _segments_to_srt(segments: list[Segment]) -> str:
    cues: list[str] = []
    for i, seg in enumerate(segments, start=1):
        cues.append(
            f"{i}\n{_fmt_srt_time(seg.start_s)} --> {_fmt_srt_time(seg.end_s)}\n{seg.text}\n"
        )
    return "\n".join(cues)


class CaptionAgent:
    name = "caption"

    def __init__(self, whisper: WhisperLike) -> None:
        self._whisper = whisper

    async def run(self, ctx: RunContext) -> StageResult:
        audio = ctx.artifacts["voice.mp3"]
        segments = await self._whisper.transcribe(audio)
        if not segments:
            raise ValueError("whisper returned zero segments")

        srt = _segments_to_srt(segments)
        dest = ctx.run_dir / "captions.srt"
        dest.write_text(srt, encoding="utf-8")

        word_count = sum(len(s.text.split()) for s in segments)
        log.info("caption_done", path=str(dest), segments=len(segments), words=word_count)

        return StageResult(
            artifacts={"captions.srt": dest},
            metadata={"word_count": word_count},
        )
