"""Local faster-whisper wrapper. Sync internals, async surface via to_thread."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_auto.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    text: str


class WhisperClient:
    def __init__(
        self,
        *,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        _model: Any = None,
    ) -> None:
        if _model is not None:
            self._model = _model
        else:
            from faster_whisper import WhisperModel  # lazy import

            self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

    async def transcribe(self, audio: Path) -> list[Segment]:
        def _call() -> list[Segment]:
            segments_iter, info = self._model.transcribe(str(audio))
            out = [
                Segment(start_s=float(s.start), end_s=float(s.end), text=s.text.strip())
                for s in segments_iter
            ]
            log.info(
                "whisper_done",
                segments=len(out),
                language=info.get("language")
                if isinstance(info, dict)
                else getattr(info, "language", None),
            )
            return out

        return await asyncio.to_thread(_call)
